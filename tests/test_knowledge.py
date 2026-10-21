import zipfile
import pytest
from workbench.common import file_hash, Blocked, ContractError
from workbench.knowledge import Knowledge, Learning
from workbench.artifacts import Artifacts, export_package


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"])
def test_source_newlines_preserve_original_bytes(store, tmp_path, newline):
    p = tmp_path / "source.md"
    original = b"Semantics" + newline * 2 + b"Exception: overflow matters."
    p.write_bytes(original)
    before = file_hash(p)
    k = Knowledge(store)
    result = k.ingest(p)
    source = k.source(result["id"], "controller")
    assert [section["text"] for section in source["sections"]] == [
        "Semantics",
        "Exception: overflow matters.",
    ]
    assert result["original_sha256"] == before
    assert p.read_bytes() == original


def test_non_destructive_ingest(store, tmp_path):
    p = tmp_path / "source.md"
    p.write_text("Semantics\n\nException: overflow matters.")
    before = file_hash(p)
    k = Knowledge(store)
    s = k.ingest(p)
    assert file_hash(p) == before
    assert s["sections"] == 2
    with pytest.raises(Blocked):
        k.source(s["id"], "worker")
    with pytest.raises(Blocked):
        k.source(s["id"], "adviser", external=True)
    assert "overflow" in k.search("overflow", role="controller")[0]["text"]


def test_required_revision_and_missing_section(store, tmp_path):
    p = tmp_path / "source.txt"
    p.write_text("Hello")
    k = Knowledge(store)
    s = k.ingest(p, True)
    item = {"source": s["id"], "revision": s["revision"], "section": "1"}
    assert not k.reading([item], role="controller")["critical_gaps"]
    assert k.reading([{**item, "section": "missing"}], role="controller")[
        "critical_gaps"
    ]
    assert k.reading([{**item, "revision": "wrong"}], role="controller")[
        "critical_gaps"
    ]


def test_missing_source(store):
    r = Knowledge(store).reading(
        [{"source": "missing", "revision": "x", "section": "1"}]
    )
    assert r["critical_gaps"]


def test_docx_image_gap(store, tmp_path):
    p = tmp_path / "image.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:document>',
        )
        z.writestr("word/media/test.png", b"image")
    s = Knowledge(store).ingest(p, True)
    assert s["status"] == "partial" and s["images"]


def test_protected_artifacts(store):
    a = Artifacts(store)
    x = a.add("truth", "secret.txt", classification="protected")
    with pytest.raises(Blocked):
        a.read(x["id"], "worker")
    assert a.read(x["id"], "evaluator") == b"truth"


def test_artifact_project_and_integrity(store):
    a = Artifacts(store)
    x = a.add("data", "a.txt", "p1")
    with pytest.raises(Blocked):
        a.read(x["id"], "worker", "p2")
    assert a.read(x["id"], "worker", "p1") == b"data"
    (a.root / x["sha256"][:2] / x["sha256"]).write_text("tampered")
    with pytest.raises(ContractError):
        a.read(x["id"], "worker", "p1")


def test_learning_promotion_and_rollback(store):
    l = Learning(store)
    p = {
        "scope": ["x86"],
        "preconditions": ["scalar"],
        "exclusions": ["FP"],
        "evidence": ["retained-test"],
        "content": "method",
    }
    a = l.propose("method", "procedure", p)
    with pytest.raises(Blocked):
        l.evaluate(a, {}, {}, [], {}, "worker")
    supplied = l.evaluate(
        a,
        {"reg": {"passed": True, "elapsed": 2}},
        {"reg": {"passed": True, "elapsed": 1}, "held": {"passed": True, "elapsed": 1}},
        ["held"],
        {},
        "evaluator",
    )
    # Caller-supplied results are advisory; promotion needs a host-run suite.
    with pytest.raises(Blocked, match="protected suite"):
        l.promote(a, supplied, "evaluator")
    from hivemind_assembly.learning.experiments import Experiments

    experiments = Experiments(store, lambda content, inputs: {"ok": content == "method"}, "fixture")
    suite = experiments.protect(
        [
            {"id": "reg", "family": "a", "project": "one", "split": "regression", "inputs": {}, "expected": {"ok": True}},
            {"id": "held", "family": "b", "project": "two", "split": "holdout", "inputs": {}, "expected": {"ok": True}},
        ]
    )
    ev = experiments.evaluate(a, None, suite, 3)
    l.promote(a, ev["evaluation"], "evaluator")
    assert (
        store.one("SELECT status FROM lessons WHERE id=?", (a,))["status"] == "active"
    )
    b = l.propose("method", "procedure", {**p, "content": "new"})
    bad = l.evaluate(
        b,
        {"reg": {"passed": True}},
        {"reg": {"passed": False}, "held": {"passed": True}},
        ["held"],
        {},
        "evaluator",
    )
    with pytest.raises(Blocked):
        l.promote(b, bad, "evaluator")
    l.rollback(a)
    assert (
        store.one("SELECT status FROM lessons WHERE id=?", (a,))["status"]
        == "rolled_back"
    )


@pytest.mark.parametrize(
    "text",
    [
        'password = "supersecretvalue"',
        "/home/person/private",
        "C:\\Users\\Private\\x",
        "-----BEGIN RSA PRIVATE KEY-----",
    ],
)
def test_export_rejects_metadata(tmp_path, text):
    p = tmp_path / "safe.txt"
    p.write_text(text)
    with pytest.raises(Blocked):
        export_package(tmp_path, ["safe.txt"], tmp_path / "out.zip")


def test_allowlist_export(tmp_path):
    (tmp_path / "code.py").write_text("print(1)")
    r = export_package(tmp_path, ["code.py"], tmp_path / "out.zip")
    assert r["files"] == 1
    with pytest.raises(ContractError):
        export_package(tmp_path, ["../outside"], tmp_path / "bad.zip")
