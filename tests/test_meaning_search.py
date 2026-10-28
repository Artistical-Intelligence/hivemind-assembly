"""Meaning search over reference material: the tokenizer, chunks, the background index,
how its ranking joins word search, category limits, downloads checked by SHA-256, and
(when HA_TEST_MEANING_MODEL names a folder with the real model) the model itself."""

import hashlib
import io
import os

import numpy
import pytest

from hivemind_assembly.learning import vectors
from hivemind_assembly.learning.knowledge import Knowledge
from hivemind_assembly.learning.scopes import KnowledgeScopes
from hivemind_assembly.learning.vectors import VectorIndex, WordPiece, chunks, fuse

# A stand-in model: words that mean the same thing share a dimension.
MEANINGS = [
    {"headless", "interface", "gui", "window"},
    {"texture", "textures", "image", "upscale"},
    {"mod", "mods", "plugin", "hook"},
    {"ghidra"},
]


class Meanings:
    dims = len(MEANINGS) + 1

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        out = []
        for text in texts:
            words = set(text.lower().replace(".", " ").replace(",", " ").split())
            v = numpy.array([len(words & m) for m in MEANINGS] + [0.01], dtype=numpy.float32)
            out.append(v / numpy.linalg.norm(v))
        return numpy.array(out)


def test_wordpiece_splits_like_bert(tmp_path):
    vocab = tmp_path / "vocab.txt"
    vocab.write_text("\n".join(["[PAD]", "[UNK]", "[CLS]", "[SEP]", "run", "ghidra", "head", "##less", ",", "cafe", "!"]))
    tokens = WordPiece(vocab)
    ids = tokens.encode("Run GHIDRA, headless café! zzz")
    names = {i: w for w, i in tokens.ids.items()}
    assert [names[i] for i in ids] == ["[CLS]", "run", "ghidra", ",", "head", "##less", "cafe", "!", "[UNK]", "[SEP]"]
    assert len(tokens.encode("run " * 1000, limit=16)) == 16


def test_chunks_keep_the_title_with_each_piece():
    body = "word " * 700
    pieces = chunks("Headless runs", body)
    assert len(pieces) == 4 and all(p.startswith("Headless runs. ") for p in pieces)
    assert all(len(p) <= vectors.CHUNK + 20 for p in pieces)
    assert chunks("Only a title", "") == ["Only a title"]


def library(store, tmp_path):
    (tmp_path / "ghidra.md").write_text("# Headless batches\n\nUse analyzeHeadless for every build.\n")
    (tmp_path / "art.md").write_text("# Texture packs\n\nUpscale each image and keep its size.\n")
    (tmp_path / "tool.py").write_text("def headless():\n    return 'gui'\n")
    knowledge = Knowledge(store)
    keys = {name: knowledge.ingest(tmp_path / name, True)["id"] for name in ("ghidra.md", "art.md", "tool.py")}
    return knowledge, keys


def test_meaning_finds_sections_that_share_no_words(store, tmp_path):
    knowledge, keys = library(store, tmp_path)
    assert knowledge.search("without the user interface", role="controller") == []  # No shared words.
    model = Meanings()
    index = VectorIndex(store, folder=tmp_path / "model", embedder=model)
    assert set(index.pending()) == {keys["ghidra.md"], keys["art.md"]}  # Prose only; code is left to word search.
    assert index.build() == 2 and index.pending() == []
    assert index.view()["state"] == "ready"
    hits = knowledge.search("without the user interface", role="controller")
    assert hits[0]["title"] == "Headless batches"
    # Word matches still count: both rankings are combined.
    order, scores = fuse([("a", "1"), ("b", "1")], [("b", "1"), ("c", "1")], 3)
    assert order[0] == ("b", "1") and set(order) == {("a", "1"), ("b", "1"), ("c", "1")}


def test_changed_documents_are_read_again(store, tmp_path):
    knowledge, keys = library(store, tmp_path)
    index = VectorIndex(store, folder=tmp_path / "model", embedder=Meanings())
    index.build()
    (tmp_path / "art.md").write_text("# Mod hooks\n\nWhere a plugin attaches.\n")
    knowledge.ingest(tmp_path / "art.md", True)
    assert index.pending() == [keys["art.md"]]  # Its old vectors are gone with its old text.
    index.build()
    assert knowledge.search("plugin", role="controller")[0]["title"] == "Mod hooks"
    assert knowledge.search("add mods to the game", role="controller")[0]["title"] == "Mod hooks"
    knowledge.remove(keys["ghidra.md"])
    assert not store.rows("SELECT 1 FROM knowledge_vectors WHERE source=?", (keys["ghidra.md"],))


def test_meaning_search_stays_within_the_projects_categories(store, tmp_path):
    scopes = KnowledgeScopes(store)
    scopes.create_tag("tools", "Tools")
    scopes.create_tag("art", "Art")
    knowledge = Knowledge(store)
    (tmp_path / "ghidra.md").write_text("# Headless batches\n\nUse analyzeHeadless.\n")
    (tmp_path / "secret.md").write_text("# GUI window notes\n\nPrivate headless interface notes.\n")
    tools = knowledge.ingest(tmp_path / "ghidra.md", True, tags=["tools"])["id"]
    art = knowledge.ingest(tmp_path / "secret.md", True, tags=["art"])["id"]
    VectorIndex(store, folder=tmp_path / "model", embedder=Meanings()).build()
    task = store.create_project("tools only", "batch analysis")
    scopes.select(task["id"], ["tools"], scopes.catalog()["revision"])
    found = knowledge.tool(task["id"], "search_knowledge", {"query": "without a user interface"})
    assert [h["source"] for h in found["hits"]] == [tools]
    assert art not in {s["source"] for s in found["_knowledge_grant"]["sources"]}


def test_without_the_model_word_search_works_alone(store, tmp_path, monkeypatch):
    knowledge, keys = library(store, tmp_path)
    index = VectorIndex(store, folder=tmp_path / "model")  # No model files.
    assert index.search("anything", {keys["ghidra.md"]: "r"}) == []
    assert knowledge.search("analyzeHeadless", role="controller")[0]["title"] == "Headless batches"
    monkeypatch.setattr(index, "runtime_installed", lambda: False)
    index._step()
    assert index.view()["state"] == "unavailable" and "Word search is used" in index.view()["message"]

    class Broken:
        def embed(self, texts):
            raise RuntimeError("model failed")

    index.model = Broken()
    store.knowledge_vectors = index
    assert knowledge.search("analyzeHeadless", role="controller")[0]["title"] == "Headless batches"


def test_model_download_is_checked_before_use(store, tmp_path, monkeypatch):
    good, bad = b"model bytes", b"vocab bytes"
    monkeypatch.setattr(vectors, "FILES", {
        "model.onnx": ("onnx/model.onnx", hashlib.sha256(good).hexdigest(), len(good)),
        "vocab.txt": ("vocab.txt", hashlib.sha256(b"something else").hexdigest(), len(bad)),
    })
    asked = []

    def opener(request, timeout):
        asked.append(request.full_url)
        return io.BytesIO(good if request.full_url.endswith("model.onnx") else bad)

    index = VectorIndex(store, folder=tmp_path / "model", opener=opener)
    with pytest.raises(ValueError, match="doesn't match its SHA-256"):
        index.download()
    assert (tmp_path / "model" / "model.onnx").read_bytes() == good
    assert not (tmp_path / "model" / "vocab.txt").exists() and not index._files_ready()
    assert all(vectors.REVISION in url for url in asked)


@pytest.mark.skipif(not os.environ.get("HA_TEST_MEANING_MODEL"), reason="Set HA_TEST_MEANING_MODEL to the model folder")
def test_the_real_model_matches_meaning():
    model = vectors.OnnxEmbedder(os.environ["HA_TEST_MEANING_MODEL"])
    query, near, far = model.embed([
        "How do I run Ghidra without the user interface as part of continuous integration?",
        "Run Ghidra headless for batches and CI",
        "Entropy as triage",
    ])
    assert float(query @ near) > 0.5 > float(query @ far) + 0.3


class Counting(Meanings):
    def __init__(self):
        super().__init__()
        self.texts = 0

    def embed(self, texts):
        self.texts += len(texts)
        return super().embed(texts)


def test_an_edit_reuses_the_vectors_of_unchanged_text(store, tmp_path):
    book = tmp_path / "book.md"
    chapters = [f"# Chapter {n}\n\nGhidra notes number {n}.\n" for n in range(1, 21)]
    book.write_text("\n".join(chapters))
    knowledge = Knowledge(store)
    key = knowledge.ingest(book, True)["id"]
    model = Counting()
    index = VectorIndex(store, folder=tmp_path / "model", embedder=model)
    index.build()
    assert model.texts == 20
    chapters[4] = "# Chapter 5\n\nNow about texture upscaling.\n"
    book.write_text("\n".join(chapters))
    knowledge.ingest(book, True)
    # Until it's read again, the changed book isn't searched by meaning with old vectors.
    assert index.search("upscale the textures", {key: "r"}) == []
    index.build()
    assert model.texts == 21  # Only the edited chapter was read by the model again.
    assert knowledge.search("make the image sharper with upscale", role="controller")[0]["title"] == "Chapter 5"


def test_indexes_from_0_34_learn_which_text_each_vector_is_for(tmp_path):
    import sqlite3

    from hivemind_assembly.core.store import Store

    folder = tmp_path / "state"
    store = Store(folder)
    store.close()
    db = sqlite3.connect(folder / "controller.sqlite3")
    db.execute("DROP TABLE knowledge_vectors")
    db.execute("CREATE TABLE knowledge_vectors(source TEXT NOT NULL,section TEXT NOT NULL,chunk INTEGER NOT NULL,"
               "vector BLOB NOT NULL,PRIMARY KEY(source,section,chunk))")
    db.commit()
    db.close()
    store = Store(folder)
    try:
        VectorIndex(store, folder=tmp_path / "model", embedder=Meanings())
        assert "hash" in {r["name"] for r in store.rows("PRAGMA table_info(knowledge_vectors)")}
    finally:
        store.close()
