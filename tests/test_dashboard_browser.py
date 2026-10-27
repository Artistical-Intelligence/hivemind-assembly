"""Actual dashboard and controller over HTTP; no mocked API or model accounts."""

import os
import pytest
import test_app

app, server = test_app.app, test_app.server

pytestmark = pytest.mark.skipif(
    not os.environ.get("WORKBENCH_TEST_CHROME"), reason="Requires real Chromium"
)


def test_edit_upload_check_and_draft_retention(server, app):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="projects"]').click()
        page.evaluate("document.querySelector('#examples-card details').open = true")
        page.get_by_role("button", name="Create register example", exact=True).click()
        expect(page.locator("#file-editor")).to_have_value("8d0437\n")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks passed", timeout=20000
        )
        page.locator("#file-editor").fill("89f829f0\n")
        # Polling, navigation and attempted file opening may not discard the draft.
        page.locator('[data-file="original.hex"]').click()
        expect(page.locator("#workspace-message")).to_contain_text("Save your draft")
        page.evaluate("refresh()")
        expect(page.locator("#file-editor")).to_have_value("89f829f0\n")
        page.locator("#file-save").click()
        expect(page.locator("#file-draft")).to_have_text("Saved on disk")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks did not pass", timeout=20000
        )
        page.locator("#file-upload").set_input_files(
            {
                "name": "input.bin",
                "mimeType": "application/octet-stream",
                "buffer": bytes(range(256)),
            }
        )
        expect(page.locator('[data-file="input.bin"]')).to_be_visible()
        page.locator('[data-file="input.bin"]').click()
        expect(page.locator("#file-binary")).to_contain_text("00 01 02")
        page.locator("#file-path").fill("notes.txt")
        page.locator("#file-new").click()
        page.locator("#file-editor").fill("persist across restart")
        page.locator("#file-save").click()
        expect(page.locator('[data-file="notes.txt"]')).to_be_visible()
        page.reload()
        page.locator('[data-tab="projects"]').click()
        page.evaluate("document.querySelector('#examples-card details').open = true")
        page.locator('[data-file="notes.txt"]').click()
        expect(page.locator("#file-editor")).to_have_value("persist across restart")
        page.locator("#starter-native-allow").check()
        page.get_by_role(
            "button", name="Create native tool example", exact=True
        ).click()
        expect(page.locator("#file-path")).to_have_value("candidate.py")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks passed", timeout=30000
        )
        page.locator("#workspace-last-result").click()
        expect(page.locator("#workspace-result")).to_contain_text("native_tool_tests")
        page.locator('[data-tab="projects"]').click()
        page.locator('#project-form [name="name"]').fill("Guided utility")
        page.locator('#project-form [name="objective"]').fill("Uppercase text")
        page.locator("#project-form button").click()
        expect(page.locator("#workspace-task option:checked")).to_contain_text(
            "Guided utility"
        )
        expect(page.locator("#file-new")).to_be_enabled()
        page.locator("#file-path").fill("tool.py")
        page.locator("#file-new").click()
        page.locator("#file-editor").fill(
            "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read().upper())\n"
        )
        page.locator("#file-save").click()
        expect(page.locator('[data-file="tool.py"]')).to_be_visible()
        page.locator("#guided-candidate").select_option("tool.py")
        page.locator('#guided-cases [data-field="stdin"]').fill("hello\n")
        page.locator('#guided-cases [data-field="stdout"]').fill("HELLO\n")
        page.locator("#guided-native-allow").check()
        page.locator("#guided-pin").click()
        expect(page.locator("#guided-status")).to_contain_text("Checks saved")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks passed", timeout=20000
        )
        assert errors == []
        browser.close()


def test_frame_replay_starter_and_synchronized_capture_inspection(server, app, tmp_path):
    import shutil
    from playwright.sync_api import sync_playwright, expect

    compiler = os.environ.get("HA_TEST_CLANG") or shutil.which("cc") or shutil.which("clang")
    if not compiler:
        pytest.skip("C compiler required for frame replay")
    app.config["foundations"]["c_compiler"] = compiler
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ["WORKBENCH_TEST_CHROME"], headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="projects"]').click()
        page.evaluate("document.querySelector('#examples-card details').open = true")
        page.locator("#starter-native-allow").check()
        page.get_by_role("button", name="Create frame replay example", exact=True).click()
        expect(page.locator("#file-path")).to_have_value("candidate.c", timeout=30000)
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text("Checks passed", timeout=30000)
        code = page.locator("#file-editor").input_value()
        page.locator("#file-editor").fill(code.replace("tick == frame", "tick == frame - 1"))
        page.locator("#file-save").click()
        expect(page.locator("#file-draft")).to_have_text("Saved on disk")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text("Checks did not pass", timeout=30000)
        page.locator("#workspace-captures").click()
        view = page.locator("#workspace-capture-view")
        expect(view.locator("select")).to_be_visible()
        view.locator("select").select_option("1")  # Movement, not stationary.
        expect(view.locator("canvas")).to_have_count(2)
        pixels = "els => els.map(c => Array.from(c.getContext('2d').getImageData(0,0,c.width,c.height).data))"
        reference, candidate = view.locator("canvas").evaluate_all(pixels)
        assert reference != candidate
        slider = view.locator('input[type="range"]')
        slider.fill("15")
        expect(view).to_contain_text("Frame 16 / 16 · index 15")
        reference, candidate = view.locator("canvas").evaluate_all(pixels)
        assert reference == candidate
        view.get_by_role("button", name="Jump to first difference").click()
        expect(slider).to_have_value("0")
        reference, candidate = view.locator("canvas").evaluate_all(pixels)
        assert reference != candidate
        with page.expect_download() as download:
            view.get_by_role("button", name="Download candidate capture", exact=True).click()
        assert download.value.suggested_filename == "candidate-frames.rgba"
        output = tmp_path / "candidate-frames.rgba"
        download.value.save_as(output)
        raw = output.read_bytes()
        assert len(raw) == 16 * 16 * 4 * 16
        assert raw[:16 * 16 * 4] == bytes(candidate)
        assert raw[-16 * 16 * 4:] != raw[:16 * 16 * 4]
        # Switching projects removes the previous project's protected captures.
        page.get_by_role("button", name="Create register example", exact=True).click()
        expect(page.locator("#file-path")).to_have_value("candidate.hex")
        expect(view.locator("canvas")).to_have_count(0)
        expect(page.locator("#workspace-captures")).to_be_disabled()
        assert errors == []
        browser.close()


def test_oauth_dashboard_requests_session_default_and_disconnect(
    server, app, monkeypatch
):
    from playwright.sync_api import sync_playwright, expect

    cfg = app.connections.settings()
    cfg["servers"]["fixture"] = {
        "transport": "http",
        "url": "https://mcp.example/service",
    }
    app.connections.save(cfg)
    calls = []

    def start(*args):
        calls.append(args)
        app.connections.oauth.states["fixture"] = {"stage": "authorization"}
        return {"stage": "authorization"}

    monkeypatch.setattr(app.connections.oauth, "start", start)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="settings"]').click()
        page.get_by_text("Other tools for the assistants (optional)").click()
        # Saved web-address connections are picked from a list.
        page.locator('#mcp-oauth [name="server"]').select_option("fixture")
        expect(page.locator('#mcp-oauth [name="remember"]')).not_to_be_checked()
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(page.locator("#mcp-oauth-status")).to_contain_text("authorization")
        assert calls == [("fixture", False, None, 0, "")]
        page.locator('#mcp-oauth summary').click()
        page.locator('#mcp-oauth [name="client_metadata_url"]').fill('https://ha.example/client.json')
        page.locator('#mcp-oauth [name="port"]').fill('40001')
        page.locator('#mcp-metadata-generate').click()
        expect(page.locator('#mcp-metadata-document')).to_contain_text('http://127.0.0.1:40001/oauth/callback')
        with page.expect_response(lambda response: response.url.endswith('/api/mcp/authorize')):
            page.get_by_role("button", name="Sign in", exact=True).click()
        assert calls[-1] == ('fixture', False, None, 40001, 'https://ha.example/client.json')
        page.locator("#mcp-oauth-forget").click()
        expect(page.locator("#notice")).to_contain_text("removed from HA")
        assert app.connections.settings()["servers"]["fixture"]["auth"] == "none"
        browser.close()


def test_mcp_and_optional_cloud_settings(server, app):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="settings"]').click()
        expect(
            page.locator('#cloud-settings input[name="enabled"]')
        ).not_to_be_checked()
        page.locator('#mcp-access input[name="enabled"]').check()
        page.locator("#mcp-access button").first.click()
        expect(page.locator("#notice")).to_contain_text("Saved.")
        expect(page.locator("#quick-chatgpt")).to_be_visible()
        expect(page.locator("#quick-ready")).to_be_hidden()
        page.get_by_text("Add HA to another app by hand").click()
        page.locator("#mcp-config").click()
        expect(page.locator("#mcp-config-result")).to_contain_text("hivemind-assembly")
        page.get_by_text("OpenAI Secure MCP Tunnel (advanced)").click()
        page.locator('#tunnel-configure input[name="tunnel_id"]').fill(
            "tunnel_0123456789abcdef"
        )
        page.locator('#tunnel-configure input[name="key"]').fill(
            "test-runtime-credential"
        )
        page.locator("#tunnel-configure button").click()
        expect(page.locator("#notice")).to_contain_text("Tunnel configured")
        expect(page.locator('#tunnel-configure input[name="key"]')).to_have_value("")
        assert (
            "test-runtime-credential" not in page.locator("#tunnel-result").inner_text()
        )
        assert app.connections.settings()["enabled"]
        assert not app.codespaces.settings()["enabled"]
        assert errors == []
        browser.close()


def test_activity_logs_filter_by_lists(server, app):
    from playwright.sync_api import sync_playwright, expect

    task = app.store.create_project("Logged project", "Write things down", paused=True)
    app.controller.traces.append(
        task["id"], "message-1", "worker.opus", "response_error", {"error": "timed out"}
    )
    app.controller.traces.append(
        task["id"], "message-1", "worker.opus", "request", {"body": "hello"}
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator("#traces-details > summary").click()
        # Projects and assistants are picked from lists, by name.
        expect(page.locator("#trace-task option", has_text="Logged project")).to_have_count(1)
        expect(page.locator("#trace-route option", has_text="Worker")).not_to_have_count(0)
        page.locator("#trace-task").select_option(task["id"])
        # Choosing from a list searches straight away.
        page.locator('#trace-form [name="kind"]').select_option("response_error")
        expect(page.locator("#trace-list")).to_contain_text("Reply problem")
        expect(page.locator("#trace-list")).to_contain_text("Project: Logged project")
        expect(page.locator("#trace-list")).not_to_contain_text("Message HA sent")
        assert errors == []
        browser.close()


def test_cloud_computers_use_lists_and_plain_commands(server, app, monkeypatch):
    from playwright.sync_api import sync_playwright, expect

    task = app.store.create_project("Cloud project", "Build in the cloud", paused=True)
    app.workspace.write(task["id"], "main.c", "int main(void){return 0;}")
    monkeypatch.setattr(
        app.codespaces,
        "listing",
        lambda: {
            "codespaces": [
                {"name": "fuzzy-space-1", "display_name": "Builder", "state": "Available",
                 "repository": {"full_name": "me/game"}},
            ]
        },
    )
    sent = []
    monkeypatch.setattr(
        app.codespaces, "submit", lambda data: sent.append(data) or {"id": data["request_id"]}
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="settings"]').click()
        page.locator("#cloud-list").click()
        expect(page.locator("#cloud-list-result")).to_contain_text("Found 1 Codespace")
        # Codespaces are ticked by name, not typed.
        page.locator('#cloud-spaces [data-space="fuzzy-space-1"]').check()
        page.locator('#cloud-settings [name="enabled"]').check()
        page.locator('#cloud-settings [name="allow_execution"]').check()
        page.get_by_role("button", name="Save cloud settings").click()
        expect(page.locator("#notice")).to_contain_text("Codespaces settings saved")
        assert app.codespaces.settings()["spaces"] == ["fuzzy-space-1"]
        page.get_by_text("Run a job on a cloud computer (optional)").click()
        expect(page.locator("#cloud-job-space")).to_have_value("fuzzy-space-1")
        # The header project picker chooses the project for this form too.
        page.locator("#workspace-task").select_option(task["id"])
        expect(page.locator("#cloud-task")).to_have_value(task["id"])
        page.locator("#cloud-all-files").click()
        expect(page.locator('#cloud-job [name="files"]')).to_have_value("main.c")
        page.locator('#cloud-job [name="commands"]').fill(
            'cc main.c -o program\nbash -c "./program && echo done"'
        )
        page.locator('#cloud-job [name="timeout_minutes"]').fill("5")
        first_id = page.locator('#cloud-job [name="request_id"]').input_value()
        page.get_by_role("button", name="Run job").click()
        expect(page.locator("#notice")).to_contain_text("is queued")
        assert sent[0]["commands"] == [
            ["cc", "main.c", "-o", "program"],
            ["bash", "-c", "./program && echo done"],
        ]
        assert sent[0]["timeout"] == 300 and sent[0]["files"] == ["main.c"]
        assert sent[0]["request_id"] == first_id
        # The next job gets a new name by itself.
        expect(page.locator('#cloud-job [name="request_id"]')).not_to_have_value(first_id)
        assert errors == []
        browser.close()


def test_other_tools_form_paste_list_and_tick(server, app, monkeypatch):
    import json
    import sys
    from playwright.sync_api import sync_playwright, expect

    project = app.store.create_project("Tool project", "Use tools", paused=True)

    async def external(server_name, *args, **kwargs):
        return [
            {"name": "read_file", "description": "Read a file", "inputSchema": {}},
            {"name": "delete_file", "description": "Delete a file", "inputSchema": {}},
        ]

    monkeypatch.setattr(app.connections, "external", external)
    snippet = json.dumps(
        {"mcpServers": {"file tools": {"command": sys.executable, "args": ["-m", "files"], "env": {"API_KEY": "x"}}}}
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="settings"]').click()
        page.get_by_text("Other tools for the assistants (optional)").click()
        page.get_by_text("Paste a setup from the tool's instructions").click()
        page.locator('#mcp-external [name="spec"]').fill(snippet)
        page.locator("#mcp-paste").click()
        expect(page.locator("#notice")).to_contain_text("API_KEY")
        expect(page.locator('#mcp-external [name="name"]')).to_have_value("file-tools")
        expect(page.locator('#mcp-external [name="command"]')).to_have_value(sys.executable)
        expect(page.locator('#mcp-external [name="args"]')).to_have_value("-m\nfiles")
        page.get_by_role("button", name="Save connection").click()
        expect(page.locator("#notice")).to_contain_text("Select List tools")
        page.locator("#mcp-discover").click()
        expect(page.locator("#mcp-discovery")).to_contain_text("2 tools found")
        page.locator('#mcp-tools input[value="read_file"]').check()
        page.locator(f'#mcp-tool-projects input[value="{project["project_id"]}"]').check()
        page.get_by_role("button", name="Save connection").click()
        expect(page.locator("#notice")).to_have_text("Saved.")
        spec = app.connections.settings()["servers"]["file-tools"]
        assert spec["transport"] == "stdio" and spec["args"] == ["-m", "files"]
        assert spec["tools"] == ["read_file"] and spec["projects"] == [project["project_id"]]
        assert "env" not in spec
        # A saved connection loads back into the form from the list.
        page.reload()
        page.locator('[data-tab="settings"]').click()
        page.get_by_text("Other tools for the assistants (optional)").click()
        page.locator("#mcp-saved").select_option("file-tools")
        expect(page.locator('#mcp-tools input[value="read_file"]')).to_be_checked()
        assert errors == []
        browser.close()


def test_completion_checks_suggest_files_and_insert_examples(server, app):
    from playwright.sync_api import sync_playwright, expect

    task = app.store.create_project("Checked project", "Compare programs", paused=True)
    app.workspace.write(task["id"], "original.elf.txt", "x")
    app.workspace.write(task["id"], "build.json", "{}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="projects"]').click()
        page.locator("#workspace-task").select_option(task["id"])
        page.locator('#acceptance-form [name="original_path"]').focus()
        expect(page.locator('#acceptance-files option[value="build.json"]')).to_have_count(1)
        page.locator("#acceptance-scope").select_option("linux_program")
        cases = page.locator('#acceptance-form [name="program_cases"]')
        cases.locator("xpath=ancestor::label/following-sibling::button[1]").click()
        assert cases.input_value() == cases.get_attribute("placeholder")
        deps = page.locator('#acceptance-form [name="program_dependencies"]')
        deps.fill("{not json")
        cases.focus()
        assert "valid JSON" in deps.evaluate("t => t.validationMessage")
        deps.fill("{}")
        assert deps.evaluate("t => t.validationMessage") == ""
        assert errors == []
        browser.close()


def test_what_ha_sees_shows_the_tab_picture(server, app):
    import time
    from playwright.sync_api import sync_playwright, expect

    route = next(iter(app.config["routes"]))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        # A real JPEG, as HA saves it from an assistant's tab.
        tab = browser.new_page(viewport={"width": 320, "height": 200})
        tab.set_content("<h1>Sign in</h1>")
        picture = app.native_setup.snapshot_path(route)
        picture.parent.mkdir(parents=True, exist_ok=True)
        tab.screenshot(path=str(picture), type="jpeg", quality=70)
        app.native_setup.snapshots[route] = time.time()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="routes"]').click()
        page.locator(f'[data-native-snapshot="{route}"]').click()
        expect(page.locator("#snapshot-view")).to_be_visible()
        expect(page.locator("#snapshot-view p")).to_contain_text("What HA saw in this tab at")
        # The picture must actually load, not show as a broken image.
        page.wait_for_function(
            "() => { const i = document.querySelector('#snapshot-view img'); return i.complete && i.naturalWidth === 320; }",
            timeout=5000,
        )
        assert errors == []
        browser.close()


def test_assistants_page_sign_in_setups_and_model_lists(server, app, monkeypatch):
    import asyncio
    import json
    import time
    from playwright.sync_api import sync_playwright, expect

    # What the services' own model menus offered (as HA reads them with Read choices).
    choices = {
        "read_at": time.time(),
        "openai": {"modes": {
            "Chat": {"GPT-6": ["Instant", "Medium", "High", "Extra High", "Pro"]},
            "Work": {"GPT-6 Astra": ["Low", "Medium", "High", "Extra High"]},
        }},
        "claude": {"modes": {"native": {
            "Opus 5.5": ["Low", "Medium", "High", "Max"],
            "Sonnet 5.5": ["Low", "Medium", "High"],
            "Haiku 5.5": [],
        }}},
    }
    path = app.store.root / "private" / app.CHOICES
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(choices))
    started, opened = [], []
    monkeypatch.setattr(app.native_setup, "run", lambda route: started.append(route) or asyncio.sleep(0))

    class Tab:
        url = "https://claude.ai/new"

        def is_closed(self):
            return False

        async def bring_to_front(self):
            pass

    async def service_page(profile, url, hosts=None):
        opened.append(profile)
        return Tab()

    monkeypatch.setattr(app.browser, "service_page", service_page)
    monkeypatch.setattr(app, "read_model_choices", lambda: {"job": "read"})
    model = lambda p, m, name: json.dumps([p, m, name], separators=(",", ":"))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="routes"]').click()
        # One sign-in button per service, on the top row.
        expect(page.locator("#service-buttons button")).to_have_count(2)
        page.locator('[data-signin="claude"]').click()
        expect(page.locator("#notice")).to_contain_text("Opened Claude in Chrome")
        assert opened == ["claude"]
        # One row per assistant, with the setup already defined saved as Default.
        expect(page.locator("#role-rows th")).to_have_text(["Adviser", "Reviewer", "Worker 1", "Worker 2", "Worker 3"])
        expect(page.locator("#setup-name")).to_have_value("Default")
        expect(page.locator("#setup-state")).to_have_text("In use: Default.")
        expect(page.locator("#choices-state")).to_contain_text("Model lists read from ChatGPT (")
        expect(page.locator("#choices-state")).to_contain_text(") and Claude (")
        opus = page.locator('[data-role-effort="worker.opus"] option')
        expect(opus).to_have_text(["Low", "Medium", "High", "Max"])
        expect(page.locator('[data-role-effort="worker.opus"]')).to_have_value("High")
        expect(page.locator('[data-role-model="worker.astra"] option:checked')).to_have_text("GPT-6 Astra (Work)")
        # Another model keeps the thinking level when it offers it.
        page.locator('[data-role-model="reviewer.high"]').select_option(model("claude", "native", "Sonnet 5.5"))
        expect(page.locator('[data-role-effort="reviewer.high"]')).to_have_value("High")
        page.locator('[data-role-effort="reviewer.high"]').select_option("Low")
        # A model without thinking levels has nothing to choose.
        page.locator('[data-role-model="worker.astra"]').select_option(model("claude", "native", "Haiku 5.5"))
        expect(page.locator('[data-role-effort="worker.astra"]')).to_be_disabled()
        expect(page.locator("#setup-state")).to_contain_text("not in use yet")
        # Polling must not throw away the changes.
        page.evaluate("refresh()")
        expect(page.locator('[data-role-effort="reviewer.high"]')).to_have_value("Low")
        page.locator("#setup-new-name").fill("Fast")
        page.locator("#setup-save-as").click()
        expect(page.locator("#notice")).to_contain_text('Saved as "Fast"')
        fast = app.config["presets"]["Fast"]
        assert fast["reviewer.high"] == {"provider": "claude", "mode": "native", "model": "Sonnet 5.5", "effort": "Low"}
        assert fast["worker.astra"] == {"provider": "claude", "mode": "native", "model": "Haiku 5.5", "effort": ""}
        expect(page.locator("#setup-name")).to_have_value("Fast")
        page.locator("#setup-use").click()
        expect(page.locator("#setup-state")).to_have_text("In use: Fast.")
        assert app.config["active_preset"] == "Fast"
        assert app.config["routes"]["reviewer.high"]["model"] == "Sonnet 5.5"
        for route in ("reviewer.high", "worker.astra"):
            app.native_setup_futures[route].result(5)  # setup runs in the background
        assert sorted(started) == ["reviewer.high", "worker.astra"]
        # Default can be changed and saved over, then used again.
        page.locator("#setup-name").select_option("Default")
        expect(page.locator('[data-role-model="reviewer.high"] option:checked')).to_have_text("GPT-6 (Chat)")
        page.locator('[data-role-effort="adviser.extra"]').select_option("Pro")
        page.locator("#setup-save").click()
        expect(page.locator("#notice")).to_contain_text('Saved as "Default". Select Use')
        assert app.config["presets"]["Default"]["adviser.extra"]["effort"] == "Pro"
        page.locator("#setup-use").click()
        expect(page.locator("#setup-state")).to_have_text("In use: Default.")
        assert app.config["routes"]["adviser.extra"]["effort"] == "Pro"
        assert app.config["routes"]["worker.astra"]["model"] == "GPT-6 Astra"
        page.locator("#choices-read").click()
        expect(page.locator("#notice")).to_contain_text("Reading ChatGPT's and Claude's model menus")
        assert errors == []
        browser.close()


def test_tag_scope_and_optional_learning_controls(server, app, tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    from hivemind_assembly.application import pickers

    source_path = tmp_path / "learning.txt"
    source_path.write_text("Integer arithmetic documentation")
    task = app.store.create_project("Scoped project", "Integer arithmetic", paused=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="routes"]').click()
        # Typing the name fills in the short name.
        page.locator('#knowledge-tag-form [name="label"]').fill("Integer arithmetic")
        expect(page.locator('#knowledge-tag-form [name="id"]')).to_have_value(
            "integer-arithmetic"
        )
        page.locator("#knowledge-tag-form button").click()
        expect(page.locator("#knowledge-catalog")).to_contain_text("integer-arithmetic")
        # Browse fills the path from this computer's own file picker.
        monkeypatch.setattr(pickers, "choose", lambda purpose: {"path": str(source_path)})
        page.locator('#source-form [data-browse="document"]').click()
        expect(page.locator('#source-form [name="path"]')).to_have_value(str(source_path))
        # Categories are ticked, not typed.
        page.locator('#source-form [data-tag="integer-arithmetic"]').check()
        page.get_by_role("button", name="Add document").click()
        expect(page.locator("#source-list")).to_contain_text("learning.txt")
        # The header task picker selects the task for every form, including this one.
        page.locator("#workspace-task").select_option(task["id"])
        expect(page.locator("#knowledge-task")).to_have_value(task["id"])
        page.locator('#knowledge-scope-form [data-tag="integer-arithmetic"]').check()
        page.locator("#knowledge-scope-form button").click()
        expect(page.locator("#knowledge-scope-list")).to_contain_text(
            "Integer arithmetic: integer-arithmetic"
        )
        page.get_by_text("Experiments (optional)").click()
        expect(
            page.locator('#experimental-settings [name="enabled"]')
        ).not_to_be_checked()
        expect(
            page.locator('#experimental-settings [name="chat_only"]')
        ).to_be_checked()
        page.locator('#experimental-settings [name="enabled"]').check()
        # Refresh must not overwrite an unsaved policy edit.
        page.evaluate("refresh()")
        expect(page.locator('#experimental-settings [name="enabled"]')).to_be_checked()
        page.locator("#experimental-settings button").click()
        expect(page.locator("#notice")).to_contain_text("Learning settings saved")
        assert app.team.experimental.settings()["enabled"]
        assert app.team.experimental.settings()["max_turns_per_evaluation"] is None
        page.reload()
        page.locator('[data-tab="routes"]').click()
        page.get_by_text("Experiments (optional)").click()
        expect(page.locator('#experimental-settings [name="enabled"]')).to_be_checked()
        assert errors == []
        browser.close()


@pytest.mark.parametrize("button,old,new", [("Create AArch64 example", "x << 5", "x << 4"), ("Create AArch64 program example", "state + state + state", "state + state")])
def test_aarch64_example_to_x86_candidate_checks(server, app, button, old, new):
    import shutil
    from playwright.sync_api import sync_playwright, expect

    compiler = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
    if not compiler:
        pytest.skip("Clang/LLD required for the AArch64 example")
    app.config["foundations"]["c_compiler"] = compiler
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="projects"]').click()
        page.evaluate("document.querySelector('#examples-card details').open = true")
        page.get_by_role("button", name=button, exact=True).click()
        expect(page.locator("#file-path")).to_have_value("candidate.c", timeout=30000)
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks passed", timeout=30000
        )
        code = page.locator("#file-editor").input_value()
        page.locator("#file-editor").fill(code.replace(old, new))
        page.locator("#file-save").click()
        expect(page.locator("#file-draft")).to_have_text("Saved on disk")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks did not pass", timeout=30000
        )
        assert errors == []
        browser.close()


def test_windows_console_starter_edit_and_protected_check(server, app):
    import shutil
    from playwright.sync_api import sync_playwright, expect

    compiler = os.environ.get("HA_TEST_CLANG") or shutil.which("clang")
    if not compiler:
        pytest.skip("Clang/LLD required")
    app.config["foundations"]["c_compiler"] = compiler
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="projects"]').click()
        page.evaluate("document.querySelector('#examples-card details').open = true")
        page.get_by_role(
            "button", name="Create Windows console example", exact=True
        ).click()
        expect(page.locator("#file-path")).to_have_value("candidate.c", timeout=30000)
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks passed", timeout=30000
        )
        source = page.locator("#file-editor").input_value()
        page.locator("#file-editor").fill(source.replace("+17", "+18"))
        page.locator("#file-save").click()
        expect(page.locator("#file-draft")).to_have_text("Saved on disk")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks did not pass", timeout=30000
        )
        page.locator('[data-tab="projects"]').click()
        page.locator("#acceptance-scope").select_option("windows_program")
        expect(page.locator("#windows-fields")).to_be_visible()
        expect(page.locator("#program-fields")).to_be_hidden()
        assert not errors
        browser.close()


def test_emulated_frames_protected_capture_scrubbing(server, app, tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from test_windows_program import compiler

    app.config["foundations"]["c_compiler"] = compiler()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ["WORKBENCH_TEST_CHROME"], headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="projects"]').click()
        page.evaluate("document.querySelector('#examples-card details').open = true")
        # This example does not request native execution permission.
        page.get_by_role("button", name="Create emulated frame example", exact=True).click()
        expect(page.locator("#file-path")).to_have_value("candidate.c", timeout=30000)
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text("Checks passed", timeout=30000)
        code = page.locator("#file-editor").input_value()
        page.locator("#file-editor").fill(code.replace("if (input[frame])", "if (frame > 0 && input[frame - 1])"))
        page.locator("#file-save").click()
        expect(page.locator("#file-draft")).to_have_text("Saved on disk")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text("Checks did not pass", timeout=30000)
        page.locator("#workspace-captures").click()
        view = page.locator("#workspace-capture-view")
        expect(view.locator("select")).to_be_visible()
        view.locator("select").select_option("1")
        expect(view).to_contain_text("Native timing and repeatability are not measured")
        view.get_by_role("button", name="Jump to first difference").click()
        expect(view.locator('input[type="range"]')).to_have_value("1")
        pixels = "els => els.map(c => Array.from(c.getContext('2d').getImageData(0,0,c.width,c.height).data))"
        reference, candidate = view.locator("canvas").evaluate_all(pixels)
        assert reference != candidate
        view.locator('input[type="range"]').fill("7")
        reference, candidate = view.locator("canvas").evaluate_all(pixels)
        assert reference == candidate
        with page.expect_download() as download:
            view.get_by_role("button", name="Download candidate capture", exact=True).click()
        output = tmp_path / "capture.raw"
        download.value.save_as(output)
        assert len(output.read_bytes()) == 8 * 8 * 4 * 8
        assert output.read_bytes()[-256:] == bytes(candidate)
        assert errors == []
        browser.close()


def test_every_button_has_a_hover_description(server, app):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ["WORKBENCH_TEST_CHROME"],
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="projects"]').click()
        page.evaluate("document.querySelector('#examples-card details').open = true")
        page.get_by_role("button", name="Create register example", exact=True).click()
        page.wait_for_selector("[data-file]")
        missing = page.evaluate(
            "[...document.querySelectorAll('button')].filter(b=>!b.title)"
            ".map(b=>b.id||b.textContent.trim())"
        )
        assert missing == []
        # Buttons the dashboard builds later from saved state.
        samples = [
            '<button data-task="t" data-action="pause">Pause</button>',
            '<button data-native-setup="r">Set up</button>',
            '<button data-native-show="r">Show tab</button>',
            '<button data-native-snapshot="r">What HA sees</button>',
            '<button data-probe="r">Check it works</button>',
            '<button data-native-renew="r">New conversation</button>',
            '<button data-signin="openai"><b>ChatGPT</b><span>Open to sign in</span></button>',
            '<button data-share="l">Allow in tests</button>',
            '<button data-unshare="l">Keep private</button>',
            '<button data-rollback="l">Undo</button>',
            '<button data-evaluation-resume="v">Retry unfinished</button>',
            '<button data-reconcile="o">Check status</button>',
            '<button data-note="1">Save note</button>',
            '<button data-hosted-refresh="r">Check status</button>',
            '<button data-hosted-cancel="r">Cancel</button>',
            '<button data-remove-case>Remove case</button>',
            '<button>Jump to first difference</button>',
            '<button>Download output capture</button>',
            '<button>Check request</button>',
            '<button>Check status</button>',
            '<button>Cancel</button>',
            '<button>Show result</button>',
            '<button data-game-action="jump">jump (4)</button>',
            '<button data-game-replay="0">Replay</button>',
            '<button data-game-shrink="0">Shrink</button>',
            '<button data-game-package="0">Bug package</button>',
            '<button data-game-save="0">Save as regression</button>',
        ]
        untitled = page.evaluate(
            """samples => samples.filter(html => {
                const d = document.createElement('div'); d.innerHTML = html;
                return !window.haDescribeButton(d.firstChild);
            })""",
            samples,
        )
        assert untitled == []
        assert errors == []
        browser.close()


def test_game_panel_plays_explores_shrinks_and_runs_regressions(server, app):
    from playwright.sync_api import sync_playwright, expect
    from test_game_play import _compiler

    app.config["foundations"]["c_compiler"] = _compiler()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ["WORKBENCH_TEST_CHROME"], headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_port}/#{app.token}")
        page.locator('[data-tab="projects"]').click()
        page.evaluate("document.querySelector('#examples-card details').open = true")
        page.get_by_role("button", name="Create game testing example", exact=True).click()
        expect(page.locator("#file-path")).to_have_value("README.txt", timeout=60000)
        page.locator("#game-load").click()
        frames = page.locator("#game-frames canvas")
        expect(page.locator("#game-description")).to_contain_text("Coin cavern", timeout=30000)
        # This game draws its first frame after its first input.
        expect(page.locator("#game-frames")).to_contain_text("No frame yet")
        page.locator('[data-game-action="step_right"]').click()
        expect(frames).to_have_count(1, timeout=30000)
        pixels = "els => els.map(c => Array.from(c.getContext('2d').getImageData(0,0,c.width,c.height).data))"
        before = frames.evaluate_all(pixels)
        page.locator('[data-game-action="run_right"]').click()
        expect(page.locator("#game-status")).to_contain_text("5 ticks")
        assert frames.evaluate_all(pixels) != before
        page.locator('[data-game-action="jump"]').click()
        expect(page.locator("#game-status")).to_contain_text("9 ticks")
        page.locator("#game-undo").click()
        expect(page.locator("#game-status")).to_contain_text("5 ticks")
        page.locator("#game-side").select_option("both")
        expect(frames).to_have_count(2, timeout=30000)
        page.locator("#game-steps").fill("150")
        page.locator("#game-explore").click()
        findings = page.locator("#game-findings")
        expect(findings).to_contain_text("divergence state:y", timeout=120000)
        findings.locator("[data-game-shrink]").first.click()
        expect(findings).to_contain_text("Shrunk from", timeout=120000)
        findings.locator("[data-game-package]").first.click()
        expect(page.locator("#game-status")).to_contain_text("Bug package: divergence", timeout=60000)
        expect(frames).to_have_count(4)
        page.locator("#game-regressions").click()
        expect(page.locator("#game-status")).to_contain_text("2 of 2 passed", timeout=60000)
        assert errors == []
        browser.close()
