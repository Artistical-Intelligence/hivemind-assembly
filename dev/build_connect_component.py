"""Build the selected T3 Connect protocol code as a private HA component.

The source build uses T3's documented public client configuration; no private
service identity or infrastructure secret is copied. The bundled component has
no listener or model/provider adapter. HA owns account consent and permissions.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, tempfile, zipfile
from pathlib import Path
from acquire_donor_sources import preserve, SOURCES
from build_platform_components import pack
ROOT = Path(__file__).resolve().parents[1]
FILES = ['relayJwt.ts', 'relayAuth.ts', 'relayUrl.ts', 'connectAuth.ts',
         'dpop.ts', 'dpopCommon.ts', 'relaySigning.ts']


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ha-connect-build-') as directory:
        base=Path(directory)
        preserve(base/'archives',['t3'])
        archive=next((base/'archives').glob('t3-*.zip'))
        with zipfile.ZipFile(archive) as z: z.extractall(base)
        source=base/'t3'
        work=base/'build'; work.mkdir()
        donor=work/'donor'; donor.mkdir()
        originals=[]
        for name in FILES:
            path=source/'packages/shared/src'/name
            shutil.copy2(path,donor/name)
            originals.append({'path':'packages/shared/src/'+name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'modified':False})
        path=source/'apps/server/src/cloud/linkChecks.ts'
        shutil.copy2(path,donor/'linkChecks.ts')
        originals.append({'path':'apps/server/src/cloud/linkChecks.ts','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'modified':False})
        # connectAuth needs only this pure hash parser, not the unrelated remote
        # client contracts. Extract the exact declaration from the pinned source.
        original=(source/'packages/shared/src/remote.ts').read_text()
        start=original.index('export const readHashParams =')
        end=original.index(';',start)+1
        (donor/'remote.ts').write_text('// Selected T3 implementation; MIT notice retained.\n'+original[start:end]+'\n')
        originals.append({'path':'packages/shared/src/remote.ts','sha256':hashlib.sha256(original.encode()).hexdigest(),'selection':'readHashParams'})
        shutil.copy2(ROOT/'dev/connect_component_main.ts',work/'main.ts')
        package={'name':'ha-internal-connect','version':'0.1.0','private':True,'type':'module',
                 'dependencies':{'effect':'4.0.5','jose':'6.2.2','@noble/curves':'1.9.1','@noble/hashes':'1.8.0'},
                 'devDependencies':{'esbuild':'0.28.2'}}
        (work/'package.json').write_text(json.dumps(package,indent=2)+'\n')
        env=dict(os.environ,npm_config_ignore_scripts='true',npm_config_audit='false',npm_config_fund='false',DO_NOT_TRACK='1')
        subprocess.run(['npm','install','--ignore-scripts','--no-audit','--no-fund'],cwd=work,env=env,check=True,timeout=600)
        payload=base/'payload';payload.mkdir()
        subprocess.run(['node','node_modules/esbuild/bin/esbuild','main.ts','--bundle','--platform=node','--format=esm',
                        '--target=node24','--legal-comments=linked','--outfile='+str(payload/'connect.mjs')],cwd=work,env=env,check=True,timeout=120)
        shutil.copy2(source/'LICENSE',payload/'LICENSE-T3')
        shutil.copy2(source/'.env.example',work/'T3-public-source-build.env.example')
        licenses=payload/'licenses';licenses.mkdir()
        for dependency in ('effect','jose','@noble/curves','@noble/hashes'):
            directory=work/'node_modules'/dependency
            for name in ('LICENSE','LICENSE.md','LICENSE.txt'):
                if (directory/name).is_file():
                    shutil.copy2(directory/name,licenses/(dependency.replace('/','-').replace('@','')+'-'+name))
        provenance={'repository':SOURCES['t3'][0],'revision':SOURCES['t3'][1],'files':originals,
                    'entrypoint':'HA-owned bounded stdin/stdout wrapper; no automatic provider or network setup',
                    'public_client_configuration':'Pinned T3 .env.example; not a private credential'}
        (payload/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
        shutil.copy2(work/'package-lock.json',payload/'package-lock.json')
        subprocess.run(['node',str(payload/'connect.mjs')],input='{"action":"selftest"}\n',text=True,check=True,timeout=30)
        record=pack(destination,'connect','0.1.0','any',payload,'connect.mjs',[provenance])
        with zipfile.ZipFile(destination/'HA-connect-rebuild-source.zip','w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(work.rglob('*')):
                if path.is_file() and not path.is_symlink(): z.write(path,path.relative_to(work).as_posix())
            z.write(source/'LICENSE','LICENSE-T3')
        print(json.dumps(record),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    build(parser.parse_args().destination)
