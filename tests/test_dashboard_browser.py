"""Actual dashboard and controller over HTTP; no mocked API or model accounts."""

import os
import pytest
from test_app import app, server

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
        page.get_by_role("button", name="Open project files & examples").click()
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
        page.locator('[data-tab="workspace"]').click()
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
        expect(page.locator("#guided-status")).to_contain_text("Checks pinned")
        page.locator("#workspace-check").click()
        expect(page.locator("#workspace-result-summary")).to_contain_text(
            "Checks passed", timeout=20000
        )
        assert errors == []
        browser.close()
