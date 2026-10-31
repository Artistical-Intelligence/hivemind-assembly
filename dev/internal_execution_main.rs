// HA wrapper for Apache-2.0 Codex patch/process components. No network listener.
mod parser; mod streaming_parser; mod seek_sequence; mod text_file; mod file_update;
use std::collections::{HashMap, HashSet};
use std::io::{BufRead, Read, Write};
use std::path::Path;
use std::time::Duration;
use serde::Deserialize;
use serde_json::{Value, json};
use base64::Engine;
use parser::{Hunk, UpdateFileChunk};
#[derive(Debug, PartialEq)]
pub struct ApplyPatchArgs { pub patch: String, pub hunks: Vec<Hunk>, pub workdir: Option<String>, pub environment_id: Option<String> }
#[derive(Debug, thiserror::Error)]
pub enum ApplyPatchError { #[error("{0}")] ComputeReplacements(String) }
fn emit(value: Value) -> anyhow::Result<()> {
    let mut out=std::io::stdout().lock(); serde_json::to_writer(&mut out,&value)?;
    out.write_all(b"\n")?; out.flush()?; Ok(())
}
fn patch_plan(request:&Value)->anyhow::Result<Value>{
    let patch=request["patch"].as_str().ok_or_else(||anyhow::anyhow!("A patch is required"))?;
    if patch.len()>2*1024*1024 { anyhow::bail!("Patch is too large"); }
    let parsed=parser::parse_patch(patch)?;
    if parsed.environment_id.is_some() || parsed.workdir.is_some(){anyhow::bail!("HA owns environment and workspace selection");}
    if parsed.hunks.len()>200 {anyhow::bail!("Too many changed files");}
    let files=request.get("files").and_then(Value::as_object);
    let mut paths=Vec::new(); let mut changes=Vec::new(); let mut seen=HashSet::new();
    for hunk in parsed.hunks {
        let (path,destination)=match &hunk{
            Hunk::AddFile{path,..}|Hunk::DeleteFile{path}=>(path,None),
            Hunk::UpdateFile{path,move_path,..}=>(path,move_path.as_ref()),
        };
        let path=path.to_str().ok_or_else(||anyhow::anyhow!("Non-UTF8 path"))?.to_owned();
        if !seen.insert(path.to_lowercase()){anyhow::bail!("Patch repeats a path");}
        let destination=destination.map(|p|p.to_str().map(str::to_owned).ok_or_else(||anyhow::anyhow!("Non-UTF8 destination"))).transpose()?;
        if let Some(dest)=&destination{if dest!=&path && !seen.insert(dest.to_lowercase()){anyhow::bail!("Conflicting rename path");}}
        paths.push(json!({"path":path,"destination":destination,"kind":match &hunk{Hunk::AddFile{..}=>"add",Hunk::DeleteFile{..}=>"delete",_=>"update"}}));
        if request["action"]=="describe_patch"{continue;}
        let value=files.and_then(|f|f.get(&path));
        match hunk{
            Hunk::AddFile{contents,..}=>{
                if value.is_some_and(|v|!v.is_null()){anyhow::bail!("Adding a file that already exists");}
                changes.push(json!({"path":path,"kind":"add","content":contents}));
            },
            Hunk::DeleteFile{..}=>{
                if value.and_then(Value::as_str).is_none(){anyhow::bail!("Deleting a file not supplied by HA");}
                changes.push(json!({"path":path,"kind":"delete"}));
            },
            Hunk::UpdateFile{chunks,..}=>{
                let text=value.and_then(Value::as_str).ok_or_else(||anyhow::anyhow!("Missing original file text"))?;
                let mut original=text_file::SourceFile::parse(text);
                let replacements=file_update::compute_replacements(&original.line_texts(),&path,&chunks)?;
                original.apply_replacements(&replacements);
                changes.push(json!({"path":path,"destination":destination,"kind":"update","content":original.into_contents()}));
            }
        }
    }
    Ok(json!({"ok":true,"paths":paths,"changes":changes,"filesystem_modified":false}))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Run{
    action:String,id:String,argv:Vec<String>,cwd:String,environment:HashMap<String,String>,timeout:u64,
    #[serde(default)] pty:bool, #[serde(default="output_cap")] output_limit:usize,
}
fn output_cap()->usize{32*1024*1024}
async fn run_process(request:Value,mut input:std::io::BufReader<std::io::Stdin>)->anyhow::Result<()>{
    let run:Run=serde_json::from_value(request)?;
    if run.action!="run" || run.argv.is_empty() || run.argv.len()>200 || run.id.len()>100 || run.id.is_empty()
        || run.timeout==0 || run.timeout>3600 || run.output_limit>output_cap() || run.environment.len()>100
        || run.argv.iter().any(|a|a.contains('\0')||a.len()>65536)
        || run.environment.iter().any(|(k,v)|k.contains(['\0','='])||v.contains('\0')||v.len()>65536)
        || !Path::new(&run.cwd).is_absolute(){anyhow::bail!("Invalid execution request");}
    let mut child=if run.pty{
        codex_utils_pty::spawn_pty_process(&run.argv[0],&run.argv[1..],Path::new(&run.cwd),&run.environment,
          &None,codex_utils_pty::TerminalSize::default(),codex_utils_pty::ChildFds::Inherited(&[])).await?
    }else{
        codex_utils_pty::spawn_pipe_process_no_stdin(&run.argv[0],&run.argv[1..],Path::new(&run.cwd),&run.environment,&None,&[]).await?
    };
    emit(json!({"type":"started","id":run.id,"pty":run.pty}))?;
    let(tx,mut controls)=tokio::sync::mpsc::channel::<Value>(16);
    std::thread::spawn(move||{
        loop{
            let mut bytes=Vec::new();
            let read=(&mut input).take(65537).read_until(b'\n',&mut bytes);
            if !matches!(read,Ok(n) if n>0 && n<=65536){let _=tx.blocking_send(json!({"action":"terminate"}));break;}
            match serde_json::from_slice::<Value>(&bytes){
                Ok(command)=>if tx.blocking_send(command).is_err(){break;},
                Err(_)=>{let _=tx.blocking_send(json!({"action":"terminate"}));break;}
            }
        }
    });
    let deadline=tokio::time::sleep(Duration::from_secs(run.timeout));tokio::pin!(deadline);
    let(mut offset,mut ended,mut stdout_done,mut stderr_done)=(0usize,None,false,false);
    let mut state="completed";let mut stopping=false;
    let mut drain=Box::pin(tokio::time::sleep(Duration::from_secs(run.timeout+10)));
    loop{
        if stdout_done&&stderr_done&&ended.is_some(){break;}
        tokio::select!{
            data=child.stdout_rx.recv(),if !stdout_done=>{
                if let Some(data)=data{
                    if offset+data.len()>run.output_limit{state="output_limit";stopping=true;child.session.request_terminate();drain.as_mut().reset(tokio::time::Instant::now()+Duration::from_secs(3));}
                    else{emit(json!({"type":"output","id":run.id,"stream":"stdout","offset":offset,"data":base64::engine::general_purpose::STANDARD.encode(&data)}))?;offset+=data.len();}
                }else{stdout_done=true;}
            },
            data=child.stderr_rx.recv(),if !stderr_done=>{
                if let Some(data)=data{
                    if offset+data.len()>run.output_limit{state="output_limit";stopping=true;child.session.request_terminate();drain.as_mut().reset(tokio::time::Instant::now()+Duration::from_secs(3));}
                    else{emit(json!({"type":"output","id":run.id,"stream":"stderr","offset":offset,"data":base64::engine::general_purpose::STANDARD.encode(&data)}))?;offset+=data.len();}
                }else{stderr_done=true;}
            },
            status=&mut child.exit_rx,if ended.is_none()=>{
                ended=Some(status.unwrap_or(-1));drain.as_mut().reset(tokio::time::Instant::now()+Duration::from_secs(3));
            },
            control=controls.recv(),if !stopping=>{
                match control.as_ref().and_then(|v|v["action"].as_str()){
                    Some("interrupt")=>{let _=child.session.signal(codex_utils_pty::ProcessSignal::Interrupt);},
                    Some("write") if run.pty=>{
                        if let Some(text)=control.as_ref().and_then(|v|v["text"].as_str()){if text.len()<=32768{let _=child.session.writer_sender().send(text.as_bytes().to_vec()).await;}}
                    },
                    Some("resize") if run.pty=>{
                        let value=control.as_ref().unwrap();
                        let rows=value["rows"].as_u64().unwrap_or(24).clamp(1,500)as u16;
                        let cols=value["cols"].as_u64().unwrap_or(80).clamp(1,500)as u16;
                        let _=child.session.resize(codex_utils_pty::TerminalSize{rows,cols});
                    },
                    _=>{state="cancelled";stopping=true;child.session.request_terminate();drain.as_mut().reset(tokio::time::Instant::now()+Duration::from_secs(3));}
                }
            },
            _=&mut deadline,if !stopping=>{state="timeout";stopping=true;child.session.request_terminate();drain.as_mut().reset(tokio::time::Instant::now()+Duration::from_secs(3));},
            _=&mut drain=>{child.session.terminate();break;}
        }
    }
    child.session.terminate();
    emit(json!({"type":"finished","id":run.id,"status":state,"exit_code":ended.unwrap_or(-1),"bytes":offset}))
}
fn main(){
    #[cfg(target_os="linux")]
    codex_utils_pty::init_spawn_helper(std::env::args_os());
    let result=(||->anyhow::Result<()>{
        let mut input=std::io::BufReader::new(std::io::stdin());let mut line=Vec::new();
        (&mut input).take(16*1024*1024+1).read_until(b'\n',&mut line)?;
        if line.len()>16*1024*1024{anyhow::bail!("Request is too large");}
        let request:Value=serde_json::from_slice(&line)?;
        match request["action"].as_str(){
            Some("describe")=>emit(json!({"ok":true,"engine":"HA internal runtime","protocol":1,"patch_writes":false,"network_listener":false})),
            Some("describe_patch"|"plan_patch")=>emit(patch_plan(&request)?),
            Some("run")=>tokio::runtime::Builder::new_multi_thread().worker_threads(2).enable_all().build()?.block_on(run_process(request,input)),
            _=>anyhow::bail!("Unknown HA runtime operation"),
        }
    })();
    if let Err(error)=result{let _=emit(json!({"ok":false,"type":"error","message":error.to_string().chars().take(1000).collect::<String>()}));std::process::exit(1);}
}
