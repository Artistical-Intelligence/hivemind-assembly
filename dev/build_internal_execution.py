"""Build HA's internal editing/process engine from a fixed Codex source snapshot.

Reuse the real parser, streaming parser, newline-preserving editor and process
ownership library. Do not import Codex's model loop, telemetry, updater, skills
loader or execution server. The helper has no network listener and patches only
in-memory data: HA remains responsible for every authorized filesystem write.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, tempfile, zipfile
from pathlib import Path
from acquire_donor_sources import preserve, SOURCES
from build_platform_components import pack
ROOT = Path(__file__).resolve().parents[1]


def remove_function(text, marker):
    start = text.index(marker)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        if text[end] == '{': depth += 1
        if text[end] == '}': depth -= 1
        end += 1
    return text[:start] + text[end:]


def prepare(source, work):
    origin = source / 'codex-rs'
    patch = origin / 'apply-patch/src'
    runtime = work / 'runtime/src'
    runtime.mkdir(parents=True)
    provenance = []
    for name in ('parser.rs', 'streaming_parser.rs', 'text_file.rs', 'seek_sequence.rs'):
        raw = (patch / name).read_bytes()
        text = raw.decode()
        if name == 'parser.rs':
            text = text.replace('#[cfg(test)]\nuse codex_utils_absolute_path::test_support::PathBufExt;\n', '')
            text = text.replace('use codex_utils_path_uri::PathUri;\n', '').replace('use codex_utils_path_uri::PathUriParseError;\n', '')
            text = remove_function(text, '    pub fn resolve_path(')
            text = remove_function(text, '#[test]\nfn test_hunk_resolve_path_accepts_relative_and_absolute_paths()')
        text = '// Adapted for HA: in-memory patch planning; original Apache-2.0 notices retained.\n' + text
        (runtime / name).write_text(text, encoding='utf-8')
        provenance.append({'path': 'codex-rs/apply-patch/src/' + name, 'upstream_sha256': hashlib.sha256(raw).hexdigest(),
                           'change': 'Remove filesystem URI resolution and its test; HA scopes paths' if name == 'parser.rs' else 'Notice only'})
    raw = (patch / 'file_update.rs').read_text()
    calculation = raw[raw.index('fn compute_replacements('):raw.index('/// Intended result of a file update')]
    calculation = calculation.replace('fn compute_replacements(', 'pub(crate) fn compute_replacements(', 1)
    (runtime / 'file_update.rs').write_text(
        '// Extracted from Codex file_update.rs, Apache-2.0. HA supplies in-memory text.\n'
        'use crate::{ApplyPatchError,UpdateFileChunk,seek_sequence};\n'
        'use crate::text_file::Replacement;\n' + calculation, encoding='utf-8')
    provenance.append({'path': 'codex-rs/apply-patch/src/file_update.rs', 'upstream_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                       'change': 'Retain replacement computation; remove external filesystem/network dependencies'})
    shutil.copytree(origin / 'utils/pty/src', work / 'pty/src')
    (work / 'Cargo.toml').write_text('''[workspace]
resolver = "3"
members = ["runtime", "pty"]
[workspace.package]
version = "0.1.0"
edition = "2024"
license = "Apache-2.0"
[workspace.lints]
rust = {}
[workspace.dependencies]
anyhow = "1"
portable-pty = "0.9.0"
tokio = "1"
libc = "0.2.182"
lazy_static = "1.5.0"
log = "0.4"
[profile.release]
strip = true
''')
    pty_manifest = (origin / 'utils/pty/Cargo.toml').read_text()
    pty_manifest = re.sub(r'\[dev-dependencies\][\s\S]*?(?=\[target\.)', '', pty_manifest)
    (work / 'pty/Cargo.toml').write_text(pty_manifest)
    (work / 'runtime/Cargo.toml').write_text('''[package]
name = "ha-runtime"
version.workspace = true
edition.workspace = true
license.workspace = true
[dependencies]
codex-utils-pty = { path = "../pty" }
anyhow = "1"
thiserror = "2.0.17"
serde = { version="1", features=["derive"] }
serde_json = "1"
base64 = "0.22"
tokio = { version="1", features=["io-util","io-std","macros","rt-multi-thread","sync","time"] }
[dev-dependencies]
pretty_assertions = "1.4.1"
''')
    shutil.copy2(ROOT / 'dev/internal_execution_main.rs', runtime / 'main.rs')
    shutil.copy2(source / 'LICENSE', work / 'LICENSE')
    if (source / 'NOTICE').exists(): shutil.copy2(source / 'NOTICE', work / 'NOTICE')
    (work / 'provenance.json').write_text(json.dumps({'repository': SOURCES['codex'][0], 'revision': SOURCES['codex'][1],
        'patch_sources': provenance, 'process_library': 'codex-rs/utils/pty',
        'architecture': 'HA-owned bounded stdin/stdout helper; no network listener, model inference or filesystem patch writes'}, indent=2))


def build(destination, local_source=None):
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ha-execution-build-') as directory:
        base = Path(directory)
        if local_source:
            source = local_source
        else:
            preserve(base / 'archives', ['codex'])
            archive = next((base / 'archives').glob('codex-*.zip'))
            with zipfile.ZipFile(archive) as z: z.extractall(base)
            source = base / 'codex'
        work = base / 'build'
        work.mkdir()
        prepare(source, work)
        env = dict(os.environ, CARGO_TERM_COLOR='never')
        for command in (['cargo','generate-lockfile'], ['cargo','test','--locked','-p','ha-runtime'],
                        ['cargo','build','--locked','--release','-p','ha-runtime']):
            subprocess.run(command, cwd=work, env=env, check=True, timeout=1800)
        payload = base / 'payload'
        payload.mkdir()
        binary = 'ha-runtime.exe' if os.name == 'nt' else 'ha-runtime'
        shutil.copy2(work / 'target/release' / binary, payload / binary)
        for name in ('LICENSE','NOTICE','provenance.json','Cargo.lock'):
            if (work / name).exists(): shutil.copy2(work / name, payload / name)
        subprocess.run([str(payload / binary)], input='{"action":"describe"}\n', text=True, check=True, timeout=20)
        subprocess.run([str(payload / binary)], input='{"action":"plan_patch","patch":"*** Begin Patch\\n*** Add File: a.txt\\n+hello\\n*** End Patch","files":{}}\n', text=True, check=True, timeout=20)
        result = pack(destination,'execution','0.1.0','windows-x64' if os.name == 'nt' else 'linux-x64',payload,binary,
                      [{'repository': SOURCES['codex'][0], 'revision': SOURCES['codex'][1]}])
        cargo_config = subprocess.check_output(['cargo','vendor','--locked','vendor'], cwd=work, env=env, text=True, timeout=1800)
        (work / '.cargo').mkdir(exist_ok=True)
        (work / '.cargo/config.toml').write_text(cargo_config)
        out = destination / ('HA-execution-rebuild-' + result['platform'] + '.zip')
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(work.rglob('*')):
                if path.is_file() and 'target' not in path.relative_to(work).parts:
                    z.write(path,path.relative_to(work).as_posix())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--source',type=Path)
    args=parser.parse_args()
    build(args.destination,args.source)
