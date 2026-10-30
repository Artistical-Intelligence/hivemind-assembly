"""Build HA-owned browser assets and outcomes from exact OpenCLI/Agent-Reach inputs.

Only TypeScript compilation and a fixed JavaScript source generator run here.
No website adapters, npm lifecycle hooks, daemon, cookies or upstream skills run.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('opencli', type=Path)
p.add_argument('reach', type=Path)
p.add_argument('destination', type=Path)
a = p.parse_args()
root = a.destination
root.mkdir(parents=True, exist_ok=True)
originals = root / 'originals'
originals.mkdir(exist_ok=True)
records = []
for name, source, revision, paths in (
    ('opencli', a.opencli, '97dc0cd5214b9602bcda78d7422f231ee8a803e9', ['LICENSE', 'src/browser/dom-snapshot.ts', 'src/browser/compound.ts', 'src/browser/dom-helpers.ts']),
    ('agent-reach', a.reach, '14c213405669414492bda0f8d52cc6531d062c45', ['LICENSE', 'agent_reach/runtime/result.py', 'agent_reach/utils/text.py']),
):
    for path in paths:
        data = (source / path).read_bytes()
        dest = originals / name / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        records.append({'project': name, 'revision': revision, 'path': path, 'sha256': hashlib.sha256(data).hexdigest()})

with tempfile.TemporaryDirectory() as directory:
    work = Path(directory)
    for name in ('dom-snapshot.ts', 'compound.ts', 'dom-helpers.ts'):
        shutil.copyfile(a.opencli / 'src/browser' / name, work / name)
    compiler = shutil.which('tsc')
    if not compiler:
        raise SystemExit('TypeScript 5.8.3 is required to regenerate; installed HA needs no compiler')
    version = subprocess.check_output([compiler, '--version'], text=True).strip()
    if version != 'Version 5.8.3':
        raise SystemExit('Regeneration requires the recorded TypeScript 5.8.3 compiler')
    subprocess.run([compiler, '--target', 'ES2022', '--module', 'commonjs', '--skipLibCheck', '--outDir', str(work / 'js'), str(work / 'dom-snapshot.ts'), str(work / 'compound.ts'), str(work / 'dom-helpers.ts')], check=True)
    generator = """const s=require('./js/dom-snapshot.js');const d=require('./js/dom-helpers.js');
process.stdout.write(JSON.stringify({snapshot:s.generateSnapshotJs({includeIframes:false,maxDepth:30,maxTextLength:100,markdownTables:false,reportHidden:false}),stable:d.waitForDomStableJs(800,100)}));"""
    (work / 'generate.cjs').write_text(generator)
    result = json.loads(subprocess.check_output(['node', str(work / 'generate.cjs')], text=True, cwd=work))

snapshot = result['snapshot']
snapshot = snapshot.replace("'id', 'name', 'type', 'value', 'placeholder'", "'id', 'name', 'type', 'placeholder'")
start = snapshot.index('    // Synthetic attributes')
end = snapshot.index("    return parts.join(' ');", start)
snapshot = snapshot[:start] + "    // HA: form values are private; state inspection exposes labels, not secrets.\n" + snapshot[end:]
snapshot = snapshot.replace('  let interactiveIndex = 0;', '  let visitedNodes = 0;\n  let interactiveIndex = 0;')
snapshot = snapshot.replace('    if (depth > MAX_DEPTH) return false;', '    if (++visitedNodes > 5000 || depth > MAX_DEPTH) return false;')
start = snapshot.index('  // Compound sidecar')
end = snapshot.index('  // Footer', start)
snapshot = snapshot[:start] + '  // HA: compound values are not returned.\n' + snapshot[end:]
snapshot = snapshot.replace('data-opencli-ref', 'data-ha-ref').replace('__opencli_', '__ha_browser_')
snapshot = snapshot.replace("location.href", "location.origin + location.pathname")
snapshot = snapshot.replace("if (u.origin === location.origin) val = u.pathname + u.search + u.hash;", "val = u.origin === location.origin ? u.pathname : u.origin + u.pathname;")
snapshot = snapshot.replace("  return lines.join('\\n');", "  return lines.join('\\n').slice(0, 131072);")
result['snapshot'] = snapshot
result['source'] = {'project': 'jackwener/OpenCLI', 'commit': '97dc0cd5214b9602bcda78d7422f231ee8a803e9', 'license': 'Apache-2.0'}
result['modifications'] = ['HA ref namespace', 'no field values or compound sidecar', 'no query/fragment in URLs', 'bounded tree and output', 'no iframe traversal', 'existing HA browser lifecycle']
(root / 'browser_scripts.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')

text = (a.reach / 'agent_reach/utils/text.py').read_text()
(root / 'redaction.py').write_text('# Derived from Panniantong/Agent-Reach 14c213405669414492bda0f8d52cc6531d062c45; MIT.\n# Copyright (c) Agent-Reach contributors. See originals/agent-reach/LICENSE.\n' + text, encoding='utf-8')
outcomes = (a.reach / 'agent_reach/runtime/result.py').read_text().replace('from agent_reach.utils.text import', 'from .redaction import')
outcomes = outcomes.replace('`agent-reach doctor`', 'HA Settings > Check installation').replace('`agent-reach channels`', 'HA Automation').replace('`agent-reach update`', 'a reviewed HA update')
outcomes = outcomes.replace('Reach pauses this channel', 'HA pauses this capability')
(root / 'outcomes.py').write_text('# Derived from Panniantong/Agent-Reach 14c213405669414492bda0f8d52cc6531d062c45; MIT.\n# Modified: private HA imports and user-facing recovery text. Original license retained.\n' + outcomes, encoding='utf-8')
(root / '__init__.py').write_text('"""Reviewed-scope automation donors; no automatic upstream initialization."""\n')
(root / 'manifest.json').write_text(json.dumps({'compiler': version, 'sources': records, 'generated': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*') if p.is_file() and p.name not in ('manifest.json', 'STATUS.md')}}, indent=2) + '\n')
(root / 'STATUS.md').write_text('CHECKS PENDING: automation assets — independent source review and browser/privacy acceptance.\n')
print(json.dumps({'generated': str(root), 'sources': len(records), 'upstream_installers_executed': False}))
