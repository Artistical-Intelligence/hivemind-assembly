"""Apply narrowly fenced integration edits, preserving unrelated concurrent work.

Run from a checked-out HA tree. --commit saves/pushes each file separately and
never force-pushes. This is a reproducible migration of source, not user data.
"""
from pathlib import Path
import argparse, subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--commit', action='store_true')
a = p.parse_args()
ROOT = Path(__file__).resolve().parents[1]


def update(path, replacements):
    target = ROOT / path
    text = target.read_text(encoding='utf-8')
    original = text
    for before, after in replacements:
        if before == after:
            continue
        count = text.count(before)
        if (after and after in text) or (not after and count == 0):
            continue
        if count != 1:
            raise SystemExit(f'Reconcile {path}: expected one unchanged integration anchor, found {count}')
        text = text.replace(before, after, 1)
    if text == original:
        return
    marker = target.parent / 'STATUS.md'
    old_marker = marker.read_text() if marker.exists() else ''
    line = f'CHECKS PENDING: {target.name} — unified HA integration; regression checks and independent source review.\n'
    if line not in old_marker:
        marker.write_text(old_marker + line, encoding='utf-8')
        if a.commit:
            relative = marker.relative_to(ROOT).as_posix()
            subprocess.run(['git', 'add', '--', relative], cwd=ROOT, check=True)
            subprocess.run(['git', 'commit', '-m', 'Track pending HA integration review: ' + target.parent.name], cwd=ROOT, check=True)
            subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=ROOT, check=True)
    target.write_text(text, encoding='utf-8', newline='\n')
    print(path, flush=True)
    if a.commit:
        subprocess.run(['git', 'add', '--', path], cwd=ROOT, check=True)
        subprocess.run(['git', 'commit', '-m', 'Wire built-in HA capability: ' + target.name], cwd=ROOT, check=True)
        subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=ROOT, check=True)


update('_app/hivemind_assembly/automation/hermes_board.py', [
    ('from hermes_cli import kanban_db', 'from .state_engine.hermes_cli import kanban_db'),
    ('from hermes_cli.kanban_db_connect import connect', 'from .state_engine.hermes_cli.kanban_db_connect import connect'),
    ('        conn = self.connect(self.path)\n        try:\n            yield conn\n        finally:\n            conn.close()', '        from .hermes import state_home\n\n        with state_home(self.path.parent):\n            conn = self.connect(self.path)\n            try:\n                yield conn\n            finally:\n                conn.close()'),
    ('Hermes did not accept task completion; dependencies remain', 'HA did not accept task completion; dependencies remain'),
])
update('_app/hivemind_assembly/automation/team.py', [
    ('if self.host is None and self.config["foundations"].get("hermes_home"):', 'if self.host is None:  # Built-in storage; legacy external path is not required.'),
])
update('_app/hivemind_assembly/automation/native.py', [
    ('async def service_page(self, profile, url, allowed_hosts=None):', 'async def service_page(self, profile, url, allowed_hosts=None, *, prepare=None):'),
    ('            self.service_pages.add(page)\n            await page.goto(url, wait_until="domcontentloaded")', '            self.service_pages.add(page)\n            if prepare is not None:\n                await prepare(page)\n            await page.goto(url, wait_until="domcontentloaded")'),
])
update('_app/hivemind_assembly/automation/browser_actions.py', [
    ('                    await route.continue_()', '                    await route.fallback()'),
    ("'text': scrub_url_credentials(text), 'origin': session['origin']}", "'text': scrub_url_credentials(text), 'origin': session['origin'],\n                        'controls': [{'ref': ref, 'tag': ident['tag'], 'label': ident['label'] or ident['name'] or ident['text'] or ident['id'] or ident['tag']} for ref, (_, ident) in handles.items()]}"),
    ('                await element.fill(value, timeout=15000)', '                if identity["tag"] == "SELECT":\n                    await element.select_option(label=value, timeout=15000)\n                else:\n                    await element.fill(value, timeout=15000)'),
])
update('_app/hivemind_assembly/application/setup.py', [
    ('for name, label, weight in (("hermes", "Downloading Hermes", 60), ("rea", "Downloading REA", 20)):', 'for name, label, weight in (("rea", "Preparing analysis commands", 20),):'),
    ('for name in ("hermes", "rea"):', 'for name in ("rea",):  # HA sessions/tasks are embedded, not downloaded.'),
    ('progress.begin("Downloading Hermes" if name == "hermes" else "Downloading REA")', 'progress.begin("Preparing analysis commands")'),
    ('        hermes_home=str(destination / ("hermes-" + PINS["hermes"]["commit"][:12])),\n', '        # Preserve any legacy source path in settings; it is no longer imported.\n'),
    ('            "Hermes full source",', '            "HA built-in sessions and tasks",'),
])
update('_app/hivemind_assembly/application/app.py', [
    ('        self.native_signin = NativeSignIn(self.browser)\n', '''        self.native_signin = NativeSignIn(self.browser)
        from hivemind_assembly.automation.browser_actions import BrowserActions
        from hivemind_assembly.integrations.remote_access import RemoteAccess

        self.browser_actions = BrowserActions(self.browser, self.store.root)
        self.remote_access = RemoteAccess(self.store.root, self.token)
'''),
    ('            "application": "Hivemind Assembly",\n', '''            "application": "Hivemind Assembly",
            "experience": {
                "state_engine": (APP_ROOT / "hivemind_assembly/automation/state_engine/hermes_state.py").is_file(),
                "automation": self.browser_actions.status(),
                "remote": self.remote_access.snapshot(),
                "profiles": sorted({route["profile"] for route in self.config["routes"].values()}),
            },
'''),
    ('        installing = any(\n            job["name"] == "Install pinned foundations"', '        present["hermes_home"] = (APP_ROOT / "hivemind_assembly/automation/state_engine/hermes_state.py").is_file()\n        installing = any(\n            job["name"] == "Install pinned foundations"'),
    ('    def _action(self, path, data):\n', '''    def _action(self, path, data):
        if path == "/api/automation/command":
            return self.submit(self.browser_actions.run(data)).result(timeout=45)
        if path in ("/api/remote/check", "/api/remote/enable", "/api/remote/disable"):
            operation = path.rsplit("/", 1)[1]
            return self.background_job("HA private remote access", getattr(self.remote_access, operation))
        if path == "/api/remote/pair":
            return self.remote_access.pair(data.get("label", ""), data.get("days", 30))
        if path == "/api/remote/revoke":
            return self.remote_access.revoke(data.get("device", ""))
'''),
    ('        self.tunnel.close()\n        self.debugging.stop()', '        self.remote_access.close()\n        self.tunnel.close()\n        self.debugging.stop()'),
    ('                "/app.js": ("app.js", "text/javascript"),', '                "/app.js": ("app.js", "text/javascript"),\n                "/unified.js": ("unified.js", "text/javascript"),'),
    ('    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)\n', '    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)\n    app.remote_access.bind(server.server_port)\n'),
])
update('_app/hivemind_assembly/application/static/index.html', [
    ('<article id="tools-card"><h2>Tools</h2>', '<article id="ha-experience"></article><article id="tools-card"><h2>Analysis setup</h2>'),
    ("Installs the programs HA needs: Ghidra and REA (for taking programs apart), Hermes (runs the assistants' tools), Git, Node.js, Java, LLVM (compilers), the GitHub CLI and the connection helpers. Programs you already have are reused.", 'Prepare HA\'s analysis and build capabilities here. Sessions, task scheduling and browser inspection are built in. Existing installations are reused; advanced engine details remain in settings and third-party notices.'),
    ('>Install required tools</button><button id="verify-foundations">Check installed tools', '>Prepare HA analysis</button><button id="verify-foundations">Check analysis setup'),
    ('<script src="/help.js"></script></body>', '<script src="/help.js"></script><script src="/unified.js"></script></body>'),
])
update('_app/hivemind_assembly/application/static/app.js', [
    ('window.renderWorkspace?.(s);', 'window.renderCapabilities?.(s);window.renderWorkspace?.(s);'),
])
update('tests/test_hermes_board.py', [
    ('"""Integration with an actual pinned Hermes checkout, not a replacement scheduler."""', '"""Integration with HA\'s extracted, real storage/task engine; no external checkout."""'),
    ('pytestmark = pytest.mark.skipif(\n    not os.environ.get("HA_TEST_HERMES"),\n    reason="Set HA_TEST_HERMES to the pinned complete Hermes checkout",\n)\n', '# The retained scheduling implementation now runs in ordinary offline tests.\n'),
    ('    monkeypatch.syspath_prepend(os.environ["HA_TEST_HERMES"])\n', ''),
])

update('_app/hivemind_assembly/automation/hermes_board.py', [
    ('        from .state_engine.hermes_cli import kanban_db\n        from .state_engine.hermes_cli.kanban_db_connect import connect\n', '        from .hermes import state_home\n\n        with state_home(root):\n            from .state_engine.hermes_cli import kanban_db\n            from .state_engine.hermes_cli.kanban_db_connect import connect\n'),
])
update('dev/ingest_automation.py', [
    ("result['snapshot'] = snapshot", "snapshot = snapshot.replace('  function getDirectText(el) {', \"  function getDirectText(el) {\\n    if (['INPUT','TEXTAREA','SELECT','OPTION'].includes(el.tagName) || el.isContentEditable) return '';\")\nsnapshot = snapshot.replace('      const compound = compoundInfoOf(el);', '      const compound = null; // HA never reads private current form values.')\nresult['snapshot'] = snapshot"),
])

update('_app/hivemind_assembly/integrations/remote_access.py', [
    ('''        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if saved.get("version") != 1 or not isinstance(saved.get("devices"), list):
                raise Blocked("Remote access settings need recovery; existing data was left unchanged")
            self.state.update(saved)
            self.state["transport"] = "unchecked"
''', '''        self.settings_error = False
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if (not isinstance(saved, dict) or saved.get("version") != 1 or
                        type(saved.get("enabled")) is not bool or
                        not isinstance(saved.get("devices"), list) or
                        len(saved["devices"]) > 32 or
                        saved.get("gateway_port") is not None and
                        (type(saved["gateway_port"]) is not int or not 0 < saved["gateway_port"] < 65536)):
                    raise ValueError("Invalid retained remote settings")
                for device in saved["devices"]:
                    if (not isinstance(device, dict) or
                            not re.fullmatch(r"[a-f0-9]{24}", device.get("id", "")) or
                            not re.fullmatch(r"[a-f0-9]{64}", device.get("hash", "")) or
                            not isinstance(device.get("label"), str) or
                            not 1 <= len(device["label"]) <= 80 or
                            not isinstance(device.get("created"), (float, int)) or
                            not isinstance(device.get("expires"), (float, int))):
                        raise ValueError("Invalid retained device")
                origin = saved.get("origin")
                if origin is not None and not re.fullmatch(r"https://[a-z0-9][a-z0-9.-]*\.ts\.net:8443", origin):
                    raise ValueError("Invalid retained network identity")
                self.state.update(saved)
                self.state["transport"] = "unchecked"
            except (ValueError, OSError, TypeError, KeyError):
                self.settings_error = True
                self.state["transport"] = "settings_need_recovery"
'''),
    ('    def save(self):\n        self.folder.mkdir', '    def save(self):\n        if self.settings_error:\n            raise Blocked("Remote settings need recovery; the original file was preserved. Local HA remains available.")\n        self.folder.mkdir'),
    ('        status = self.cli_json(["status", "--json"])', '        if self.settings_error:\n            raise Blocked("Remote settings need recovery; no network settings were changed")\n        status = self.cli_json(["status", "--json"])'),
    ('''    def disable(self):
        with self.lock:
            config = self.cli_json(["serve", "status", "--json"])
            current = self.mapping(config)
            if current and current != self.proxy_url():
                raise Blocked("The remote mapping no longer belongs to HA. No other application's mapping was removed.")
            if current:
                self.runner(["serve", f"--https={HTTPS_PORT}", "off"])
            self.state["enabled"] = False
            self.state["devices"] = []
            self.state["transport"] = "disabled"
            self.save()
        self.close()
        return self.snapshot()
''', '''    def disable(self):
        # Revoke locally before calling a possibly unavailable network service.
        with self.lock:
            self.state["enabled"] = False
            self.state["devices"] = []
            self.state["transport"] = "disabled"
            self.save()
        try:
            config = self.cli_json(["serve", "status", "--json"])
            current = self.mapping(config)
            if current and current != self.proxy_url():
                raise Blocked("The remote mapping no longer belongs to HA. No other application's mapping was removed.")
            if current:
                self.runner(["serve", f"--https={HTTPS_PORT}", "off"])
        except (Blocked, OSError):
            with self.lock:
                self.state["transport"] = "disabled_cleanup_pending"
                self.save()
            return self.snapshot()
        self.close()
        return self.snapshot()
'''),
    ('                origin = remote.state.get("origin")', '                if not remote.state["enabled"]:\n                    return self.reject(403)\n                origin = remote.state.get("origin")'),
])
