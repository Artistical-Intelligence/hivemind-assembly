"""Chrome helper: native messaging bridge, approval-page checks and registration."""

import io
import json
import os
import struct
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from hivemind_assembly.core.common import Blocked
from hivemind_assembly.integrations import chrome_helper
from hivemind_assembly.integrations.quick_connect import Auth

ORIGIN = "https://quiet-river-1.trycloudflare.com"
CLAUDE = "https://claude.ai/api/mcp/auth_callback"
ORIGIN_ARG = "chrome-extension://" + chrome_helper.EXTENSION_ID + "/"


def frames(*messages):
    out = b""
    for m in messages:
        raw = json.dumps(m).encode()
        out += struct.pack("=I", len(raw)) + raw
    return out


def replies(data):
    out, stream = [], io.BytesIO(data)
    while head := stream.read(4):
        out.append(json.loads(stream.read(struct.unpack("=I", head)[0])))
    return out


def test_native_protocol_forwards_only_allowed_requests():
    seen = []

    def requester(path, payload):
        seen.append((path, payload))
        if path == "helper/status":
            return {"state": "ready", "message": "Ready", "token": "secret",
                    "services": {"Claude": {"authorized": True, "secret": "x"}}}
        return {"ok": path}

    out = io.BytesIO()
    code = chrome_helper.native_main(
        ["--data-dir", "/tmp/x", ORIGIN_ARG],
        io.BytesIO(frames({"op": "status"}, {"op": "details", "provider": "Claude"},
                          {"op": "tools", "name": "ha_write_file"}, {"op": "details", "extra": 1})),
        out, requester,
    )
    assert code == 0
    status, details, tools, extra = replies(out.getvalue())
    assert status["ok"] and "token" not in json.dumps(status)
    assert status["value"]["services"]["Claude"] == {"authorized": True}
    assert details == {"ok": True, "value": {"ok": "helper/details"}}
    assert not tools["ok"] and not extra["ok"]
    assert [p for p, _ in seen] == ["helper/status", "helper/details"]


def test_other_extensions_are_refused():
    out = io.BytesIO()
    assert chrome_helper.native_main(["--data-dir", "/tmp/x", "chrome-extension://abc/"],
                                     io.BytesIO(frames({"op": "status"})), out, lambda p, d: {}) == 2
    assert out.getvalue() == b""


def quick_with_flow():
    auth = Auth()
    auth.activate(ORIGIN)
    client = auth.register({"redirect_uris": [CLAUDE]})["client_id"]
    query = {"client_id": client, "redirect_uri": CLAUDE, "response_type": "code",
             "code_challenge": "c" * 43, "code_challenge_method": "S256"}
    flow = auth.begin(query)
    quick = SimpleNamespace(
        gateway=SimpleNamespace(auth=auth),
        status=lambda: {"state": "ready", "endpoint": ORIGIN + "/mcp"},
    )
    return quick, auth, flow, ORIGIN + "/authorize?" + urlencode(query)


def test_pairing_code_is_bound_to_the_real_approval_page():
    quick, auth, flow, page = quick_with_flow()
    result = chrome_helper.pair(quick, "Claude", page, flow)
    assert result["origin"] == ORIGIN and result["endpoint"] == ORIGIN + "/mcp"
    redirect = auth.approve({"flow": flow, "pairing_code": result["pairing_code"]})
    assert redirect.startswith(CLAUDE + "?code=")
    with pytest.raises(Blocked):
        chrome_helper.pair(quick, "Claude", page.replace("quiet-river-1", "evil-host-2"), flow)
    with pytest.raises(Blocked):
        chrome_helper.pair(quick, "ChatGPT", page, flow)
    with pytest.raises(Blocked, match="expired"):
        chrome_helper.pair(quick, "Claude", page, flow)  # the approval already used this request


def test_details_need_a_running_connection():
    quick = SimpleNamespace(gateway=None, status=lambda: {"state": "off", "endpoint": ""})
    with pytest.raises(Blocked, match="Start the browser connection"):
        chrome_helper.details(quick, "ChatGPT")


@pytest.mark.skipif(os.name == "nt", reason="Windows registers in the user registry")
def test_registration_writes_user_level_host_manifests(tmp_path):
    result = chrome_helper.register_native_host(tmp_path / "data", home=tmp_path / "home")
    assert result["extension_id"] == chrome_helper.EXTENSION_ID
    manifest = json.loads(
        (tmp_path / "home/.config/google-chrome/NativeMessagingHosts" / (chrome_helper.HOST_NAME + ".json")).read_text()
    )
    assert manifest["allowed_origins"] == [ORIGIN_ARG]
    launcher = open(manifest["path"]).read()
    assert "chrome-helper --data-dir" in launcher and str((tmp_path / "data").resolve()) in launcher


def test_extension_files_match_the_helper():
    folder = chrome_helper.EXTENSION_DIR
    manifest = json.loads((folder / "manifest.json").read_text())
    assert chrome_helper.extension_id() == chrome_helper.EXTENSION_ID
    assert manifest["optional_host_permissions"] == ["https://*.trycloudflare.com/*"]
    for name in ("background.js", "popup.js"):
        assert chrome_helper.HOST_NAME in (folder / name).read_text()
    for name in ("background.js", "form.js", "navigation.js", "pairing.js", "popup.js", "popup.html", "popup.css",
                 "icons/16.png", "icons/48.png", "icons/128.png"):
        assert (folder / name).is_file(), name
    # The approval page the form helper recognizes is the one HA serves.
    from hivemind_assembly.integrations.quick_connect import APPROVAL_PAGE

    assert "Connect Hivemind Assembly" in APPROVAL_PAGE and 'id="ha-pair-status"' in APPROVAL_PAGE
    assert "connect hivemind assembly" in (folder / "form.js").read_text()


@pytest.mark.skipif(not os.environ.get("WORKBENCH_TEST_CHROME"), reason="needs Chromium")
def test_form_helper_fills_the_code_on_has_approval_page_without_approving():
    import html
    from playwright.sync_api import sync_playwright
    from hivemind_assembly.integrations.quick_connect import APPROVAL_PAGE

    quick, auth, flow, page_url = quick_with_flow()
    code = chrome_helper.pair(quick, "Claude", page_url, flow)
    body = APPROVAL_PAGE.replace("CLIENT", "Claude").replace("FLOW", html.escape(flow))
    posted = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ["WORKBENCH_TEST_CHROME"], args=["--no-sandbox"])
        page = browser.new_page()

        def serve(route):
            if route.request.method == "POST":
                posted.append(route.request.post_data)
            route.fulfill(status=200, content_type="text/html", body=body)

        page.route(ORIGIN + "/**", serve)
        page.goto(page_url)
        page.add_script_tag(content=(chrome_helper.EXTENSION_DIR / "form.js").read_text())
        probe = page.evaluate("globalThis.__haFormHelper.probe()")
        assert probe["kind"] == "pairing" and probe["provider"] == "Claude" and probe["flow"] == flow
        result = page.evaluate("data => globalThis.__haFormHelper.fillPair(data)", code)
        assert result["submitted"] is False
        assert page.locator("input[name=pairing_code]").input_value() == code["pairing_code"]
        assert "Click Approve" in page.locator("#ha-pair-status").inner_text()
        assert posted == []
        browser.close()
