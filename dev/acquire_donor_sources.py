"""Preserve exact upstream source snapshots without running donor code.

Used by the integration-inputs workflow and by offline-recovery maintainers.
These are full tracked source trees at fixed revisions, not Git-history backups
or an assertion that every runtime/build dependency has been archived.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

SOURCES = {
    'hermes': ('NousResearch/hermes-agent', 'c0015464f0f40d52c5702a84cf58e70361f4a04c'),
    'rea': ('morluto/rea', 'ca71e91d23672646af917ede8ae82c7fea395341'),
    't3': ('pingdotgg/t3code', '08a463e29976617134de01e9341f898bc881d0eb'),
    'codex': ('openai/codex', '4bc746c94fce95ec7ca5f1a91a786156d240c8a2'),
    'agent-reach': ('Panniantong/Agent-Reach', '14c213405669414492bda0f8d52cc6531d062c45'),
    'opencli': ('jackwener/OpenCLI', '97dc0cd5214b9602bcda78d7422f231ee8a803e9'),
}


def git(*args: str, cwd: Path, stdout=None) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1')
    # Do not run caller-configured hooks, credential helpers or smudge filters.
    command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'credential.helper=', *args]
    result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=600, check=True)
    return result.stdout.decode('utf-8').strip() if result.stdout is not None else ''


def preserve(destination: Path, selected: list[str] | None = None) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for name in selected or list(SOURCES):
        repository, revision = SOURCES[name]
        if not re.fullmatch(r'[a-f0-9]{40}', revision):
            raise ValueError('Source must use a full commit identifier')
        with tempfile.TemporaryDirectory(prefix='ha-source-') as directory:
            checkout = Path(directory)
            git('init', '--quiet', cwd=checkout)
            git('remote', 'add', 'origin', 'https://github.com/' + repository + '.git', cwd=checkout)
            git('fetch', '--depth=1', 'origin', revision, cwd=checkout)
            if git('rev-parse', 'FETCH_HEAD^{commit}', cwd=checkout) != revision:
                raise ValueError('Fetched source does not match the requested revision')
            output = destination / (name + '-' + revision + '.zip')
            stage = output.with_suffix('.download')
            with stage.open('wb') as stream:
                git('archive', '--format=zip', '--prefix=' + name + '/', revision, cwd=checkout, stdout=stream)
            digest = hashlib.sha256(stage.read_bytes()).hexdigest()
            if output.exists() and hashlib.sha256(output.read_bytes()).hexdigest() != digest:
                raise ValueError('Preserved archive already exists with different bytes; not overwriting it')
            stage.replace(output)
            record = {'project': name, 'repository': repository, 'commit': revision,
                      'file': output.name, 'bytes': output.stat().st_size, 'sha256': digest,
                      'donor_code_executed': False, 'complete_git_history': False}
            records.append(record)
            print(json.dumps(record), flush=True)
    manifest = {'schema': 1, 'purpose': 'Pinned source preservation; not runtime installation', 'sources': records}
    path = destination / 'source-inventory.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--source', action='append', choices=sorted(SOURCES))
    args = parser.parse_args()
    preserve(args.destination, args.source)
