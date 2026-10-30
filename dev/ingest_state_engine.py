"""Reproduce selected HA storage/task code from a pinned Hermes source tree.

Parse source rather than import it. Preserve storage algorithms and schemas while
removing unused agent launchers, provider clients and automatic plugin discovery.
Generated code needs independent review and compatibility tests before release.
"""
from pathlib import Path
import argparse, ast, collections, json, shutil, hashlib, copy

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
parser.add_argument("--namespace", default="hivemind_assembly.automation.state_engine")
args = parser.parse_args()
BASE, OUT, PREFIX = args.source.resolve(), args.destination.resolve(), args.namespace
if not (BASE / "hermes_state.py").is_file() or not (BASE / "LICENSE").is_file():
    raise SystemExit("Expected the pinned complete Hermes source tree")
if OUT == BASE or OUT in BASE.parents or BASE in OUT.parents:
    raise SystemExit("Output must be separate from source")
if OUT.exists() and any(OUT.iterdir()):
    raise SystemExit("Destination must be empty; never overwrite local changes")

# These integration seams belong to HA, not to an upstream launcher. Unsupported
# upstream PR contracts fail closed; HA's independent acceptance stays unchanged.
SHIMS = {
    "toolsets": "def get_toolset_names():\n    return ['all', 'none']\n",
    "hermes_cli.worktree_ops": "def release_lsp_clients(*args, **kwargs):\n    return None\n",
    "hermes_startup_watchdog": "def report_startup_progress(*args, **kwargs):\n    return None\n",
    "hermes_cli.kanban_pr_acceptance": '''import re
_PR = re.compile(r"pr:(?P<repo>[^/]+/[^/]+)")
def validate_contract(value):
    if value is None or value == "": return None
    raise ValueError("Use HA acceptance contracts; upstream PR execution is not enabled")
def collect_acceptance(*args, **kwargs):
    return {"ok": False, "classification": "unsupported", "head_sha": None, "pr_url": None, "checks": [], "recovery": "Use HA independent acceptance. No upstream credential lookup was performed."}
''',
    "hermes_cli.config": "def load_config_readonly(*args, **kwargs):\n    return {}\ndef load_config(*args, **kwargs):\n    return load_config_readonly()\n",
    "hermes_cli.lifecycle": "def invoke_hook(*args, **kwargs):\n    return None\n",
}
mods = {}
for p in BASE.rglob("*.py"):
    if any(v in p.parts for v in ("tests", ".venv")): continue
    m = ".".join(p.relative_to(BASE).with_suffix("").parts)
    if m.endswith(".__init__"): m = m[:-9]
    mods[m] = p
cache = {}

def bindings(n):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): return {n.name}
    if isinstance(n, ast.Import): return {a.asname or a.name.split('.')[0] for a in n.names}
    if isinstance(n, ast.ImportFrom): return {a.asname or a.name for a in n.names}
    if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
        return {s.id for t in targets for s in ast.walk(t) if isinstance(s, ast.Name) and isinstance(s.ctx, ast.Store)}
    if isinstance(n, (ast.Try, ast.If, ast.With)):
        nodes = n.body + getattr(n, 'orelse', []) + [y for h in getattr(n, 'handlers', []) for y in h.body]
        return set().union(*(bindings(x) for x in nodes))
    return set()

def info(m):
    if m not in cache:
        t = ast.parse(SHIMS[m] if m in SHIMS else mods[m].read_text(encoding='utf-8-sig'))
        idx = collections.defaultdict(set)
        for i, n in enumerate(t.body):
            for b in bindings(n): idx[b].add(i)
        cache[m] = t, idx
    return cache[m]

selected, required = collections.defaultdict(set), collections.defaultdict(set)
state_methods = {'__init__', '__del__', '__enter__', '__exit__', 'close', 'create_session', 'append_message', 'get_session', 'get_messages', 'list_sessions', 'message_count'}
class_methods = collections.defaultdict(set)
changes = False

def request(m, names):
    global changes
    if m not in mods and m not in SHIMS: return
    t, idx = info(m)
    if '*' in names: names = set(idx)
    for name in sorted(names):
        if name not in required[m]: required[m].add(name); changes = True
        if name not in idx:
            sub = m + '.' + name
            if sub in mods: request(sub, {'*'})
            continue
        for i in sorted(idx[name]):
            if i not in selected[m]: selected[m].add(i); changes = True

def state_class(n):
    return isinstance(n, ast.ClassDef) and (n.name == 'SessionDB' or n.name.startswith('Session') and n.name.endswith('Mixin'))

def trimmed(m, n):
    if isinstance(n, (ast.Import, ast.ImportFrom)) and getattr(n, 'module', None) != '__future__':
        n = copy.deepcopy(n)
        n.names = [a for a in n.names if (a.asname or (a.name.split('.')[0] if isinstance(n, ast.Import) else a.name)) in required[m]]
    if state_class(n):
        n = copy.deepcopy(n)
        n.body = [x for x in n.body if not isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) or x.name in state_methods or x.name.startswith('__')]
        if not n.body: n.body = [ast.Pass()]
    elif isinstance(n, ast.ClassDef) and n.name == 'ContextCompressor':
        n = copy.deepcopy(n)
        n.bases = []  # Only retained deterministic transcript-classification helpers.
        n.body = [x for x in n.body if not isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) or x.name in class_methods[n.name]]
        if not n.body: n.body = [ast.Pass()]
    return n

def imports(m, node):
    aliases = {}
    for x in ast.walk(node):
        if isinstance(x, ast.ImportFrom):
            mod = x.module or ''
            if x.level:
                par = m if mods.get(m, Path('x')).name == '__init__.py' else m.rpartition('.')[0]
                bits = par.split('.')
                mod = '.'.join(bits[:len(bits) - x.level + 1] + ([mod] if mod else []))
            for a in x.names:
                if a.name == '*': request(mod, {'*'}); continue
                child = mod + '.' + a.name
                if child in mods: aliases[a.asname or a.name] = child
                elif mod in mods or mod in SHIMS: request(mod, {a.name})
        elif isinstance(x, ast.Import):
            for a in x.names:
                if a.name in mods: aliases[a.asname or a.name.split('.')[0]] = a.name
    for alias, mod in aliases.items():
        attrs = {x.attr for x in ast.walk(node) if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) and x.value.id == alias}
        if attrs: request(mod, attrs)
        elif any(isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.id == alias for x in ast.walk(node)):
            request(mod, {'*'})

request('hermes_state', {'SessionDB'})
request('hermes_constants', {'set_hermes_home_override', 'reset_hermes_home_override'})
request('hermes_cli.kanban_db', {'create_task', 'recompute_ready', 'get_task', 'heartbeat_claim', 'claim_task', 'complete_task', 'link_tasks', 'block_task', 'list_tasks'})
request('hermes_cli.kanban_db_connect', {'connect'})
for iteration in range(120):
    if len(selected) > 128: raise SystemExit('Unexpected dependency expansion; review boundaries')
    changes = False
    for m, ids in sorted(list(selected.items())):
        t, idx = info(m)
        for i in sorted(ids):
            node = trimmed(m, t.body[i])
            loads = {x.id for x in ast.walk(node) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}
            loads |= {x.value for x in ast.walk(node) if isinstance(x, ast.Constant) and isinstance(x.value, str) and x.value.startswith('_') and x.value in idx}
            request(m, loads & set(idx))
            methods = state_methods if state_class(node) else class_methods['ContextCompressor'] if isinstance(node, ast.ClassDef) and node.name == 'ContextCompressor' else None
            if methods is not None:
                for x in node.body:
                    if isinstance(x, (ast.Assign, ast.AnnAssign)):
                        for y in ast.walk(x):
                            if isinstance(y, ast.Name) and isinstance(y.ctx, ast.Load) and y.id not in methods:
                                methods.add(y.id); changes = True
            for x in ast.walk(node):
                if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name):
                    if x.value.id in {'self', 'cls'} and m.startswith('hermes_state'):
                        if x.attr not in state_methods: state_methods.add(x.attr); changes = True
                    if x.value.id == 'ContextCompressor' or x.value.id == 'cls' and m == 'agent.context_compressor':
                        if x.attr not in class_methods['ContextCompressor']: class_methods['ContextCompressor'].add(x.attr); changes = True
        imports(m, ast.Module(body=[trimmed(m, t.body[i]) for i in sorted(ids)], type_ignores=[]))
    if not changes: break
if changes: raise SystemExit('Dependency analysis did not converge')
if any(m.startswith(('plugins.', 'providers.', 'agent.auxiliary', 'agent.credential')) for m in selected):
    raise SystemExit('Provider/plugin code escaped the retained storage boundary')
OUT.mkdir(parents=True, exist_ok=True)

class Namespace(ast.NodeTransformer):
    def visit_ImportFrom(self, n):
        if n.level == 0 and (n.module in mods or n.module in SHIMS): n.module = PREFIX + '.' + n.module
        return self.generic_visit(n)
    def visit_Import(self, n):
        out = []
        for a in n.names:
            if a.name in mods:
                if a.asname:
                    out.append(ast.Import(names=[ast.alias(name=PREFIX + '.' + a.name, asname=a.asname)]))
                elif '.' not in a.name:
                    out.append(ast.ImportFrom(module=PREFIX, names=[ast.alias(name=a.name)], level=0))
                else:
                    out.append(ast.Import(names=[ast.alias(name=PREFIX + '.' + a.name, asname='_ha_import_' + a.name.replace('.', '_'))]))
                    out.append(ast.ImportFrom(module=PREFIX, names=[ast.alias(name=a.name.split('.')[0])], level=0))
            else: out.append(ast.Import(names=[a]))
        return out

manifest = []
for m, ids in sorted(selected.items()):
    t, idx = info(m)
    nodes = [trimmed(m, n) for i, n in enumerate(t.body) if i in ids or isinstance(n, ast.ImportFrom) and n.module == '__future__']
    nodes = [n for n in nodes if not isinstance(n, (ast.Import, ast.ImportFrom)) or n.names]
    tree = Namespace().visit(ast.Module(body=nodes, type_ignores=[]))
    ast.fix_missing_locations(tree)
    path = OUT / Path(*m.split('.')).with_suffix('.py')
    path.parent.mkdir(parents=True, exist_ok=True)
    text = '# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.\n# MIT; copyright (c) 2025 Nous Research. See LICENSE.\n# Modified for HA: selected storage/task code; private imports; no upstream launcher.\n' + ast.unparse(tree) + '\n'
    text = text.replace('restart Hermes', 'restart HA').replace('See `hermes doctor`.', 'Use HA Settings > Check installation.').replace('stop every Hermes process', 'stop HA and every process using this database')
    path.write_text(text, encoding='utf-8')
    manifest.append({'path': path.relative_to(OUT).as_posix(), 'upstream': mods[m].relative_to(BASE).as_posix() if m in mods else m, 'ha_owned_seam': m in SHIMS, 'symbols': sorted(required[m]), 'sha256': hashlib.sha256(text.encode()).hexdigest()})
for p in list(OUT.rglob('*.py')):
    par = p.parent
    while par.is_relative_to(OUT):
        init = par / '__init__.py'
        if not init.exists(): init.write_text('"""HA-owned storage/task implementation; no upstream initialization."""\n', encoding='utf-8')
        if par == OUT: break
        par = par.parent
shutil.copyfile(BASE / 'LICENSE', OUT / 'LICENSE')
(OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
(OUT / 'STATUS.md').write_text('CHECKS PENDING: generated state engine — independent source review, storage compatibility, recovery and Windows checks.\n', encoding='utf-8')
print(json.dumps({'modules': len(selected), 'bytes': sum(p.stat().st_size for p in OUT.rglob('*.py')), 'reviewed': False}))
