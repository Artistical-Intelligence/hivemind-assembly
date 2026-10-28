"""Meaning search for the owner's reference material, on this computer.

Word search (SQLite FTS5) finds sections that use the words of a search. Meaning
search adds the sections whose text means something close, even in other words
("without the user interface" finds "headless"). A small sentence model,
all-MiniLM-L6-v2 in its 8-bit form (23 MB), turns each part of a prose section into a
vector; a search compares the vector of its words with them. The two rankings are
combined, so a section either one finds well comes near the top.

Everything runs here: nothing is sent to an AI service, and no tokens are used. The
model is downloaded once from Hugging Face at a pinned revision and checked by
SHA-256. Only prose is indexed (Word, Markdown, HTML and PDF documents); code and data
files are left to word search, which handles names better. Without ONNX Runtime or
the model, word search works alone and the reference page says why.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import unicodedata
import urllib.request
from pathlib import Path

MODEL_ID = "all-MiniLM-L6-v2-qint8"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
SOURCE = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{revision}/{path}"
FILES = {
    "model.onnx": ("onnx/model_qint8_avx512.onnx", "4278337fd0ff3c68bfb6291042cad8ab363e1d9fbc43dcb499fe91c871902474", 23026053),
    "vocab.txt": ("vocab.txt", "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3", 231508),
}
PROSE = {"word", "markdown", "html", "pdf"}
CHUNK = 1000  # characters per vector; about the 256 tokens the model reads
MAX_TOKENS = 256
BATCH = 16
RRF = 60  # rank fusion constant: a section near the top of either list ranks well


# ------------------------------------------------------------- tokenizer
def _punctuation(ch):
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _cjk(cp):
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF or 0x2A700 <= cp <= 0x2B73F
            or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


class WordPiece:
    """BERT's lowercase WordPiece tokenizer (the one all-MiniLM-L6-v2 was trained with)."""

    def __init__(self, vocab_path):
        words = Path(vocab_path).read_text(encoding="utf-8").split("\n")
        self.ids = {w: i for i, w in enumerate(words) if w}
        self.unk, self.cls, self.sep = self.ids["[UNK]"], self.ids["[CLS]"], self.ids["[SEP]"]
        self.cache = {}

    def _basic(self, text):
        out = []
        for ch in text:
            cp = ord(ch)
            if cp == 0 or cp == 0xFFFD or (unicodedata.category(ch).startswith("C") and ch not in "\t\n\r"):
                continue
            out.append(f" {ch} " if _cjk(cp) else " " if ch.isspace() else ch)
        text = unicodedata.normalize("NFD", "".join(out).lower())
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        tokens = []
        for word in text.split():
            current = ""
            for ch in word:
                if _punctuation(ch):
                    if current:
                        tokens.append(current)
                    tokens.append(ch)
                    current = ""
                else:
                    current += ch
            if current:
                tokens.append(current)
        return tokens

    def _pieces(self, word):
        found = self.cache.get(word)
        if found is not None:
            return found
        if len(word) > 100:
            pieces = [self.unk]
        else:
            pieces, start = [], 0
            while start < len(word):
                end, piece = len(word), None
                while start < end:
                    sub = ("##" if start else "") + word[start:end]
                    if sub in self.ids:
                        piece = self.ids[sub]
                        break
                    end -= 1
                if piece is None:
                    pieces = [self.unk]
                    break
                pieces.append(piece)
                start = end
        if len(self.cache) < 200_000:
            self.cache[word] = pieces
        return pieces

    def encode(self, text, limit=MAX_TOKENS):
        ids = [self.cls]
        for word in self._basic(text):
            ids.extend(self._pieces(word))
            if len(ids) >= limit - 1:
                break
        return ids[: limit - 1] + [self.sep]


# ---------------------------------------------------------------- model
class OnnxEmbedder:
    """all-MiniLM-L6-v2: mean of the token vectors, scaled to length 1 (384 numbers)."""

    dims = 384

    def __init__(self, folder, threads=None):
        import numpy
        import onnxruntime

        self.np = numpy
        options = onnxruntime.SessionOptions()
        # Half the processor at most, so Ghidra, builds and the dashboard stay responsive.
        options.intra_op_num_threads = threads or max(1, (os.cpu_count() or 2) // 2)
        options.inter_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(str(Path(folder) / "model.onnx"), options,
                                                    providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.tokenizer = WordPiece(Path(folder) / "vocab.txt")

    def embed(self, texts):
        np = self.np
        encoded = [self.tokenizer.encode(t) for t in texts]
        width = max(len(e) for e in encoded)
        ids = np.zeros((len(encoded), width), dtype=np.int64)
        mask = np.zeros((len(encoded), width), dtype=np.int64)
        for row, e in enumerate(encoded):
            ids[row, : len(e)] = e
            mask[row, : len(e)] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self.session.run(None, feed)[0]
        weights = mask[:, :, None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
        return pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)


def chunks(title, body):
    """The pieces of a section that each get a vector: its title leads every piece."""
    text = re.sub(r"\s+", " ", body or "").strip()
    head = (title or "").strip()
    if not text:
        return [head] if head else []
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK)
        if end < len(text):
            space = text.rfind(" ", start + CHUNK // 2, end)
            end = space if space > start else end
        out.append((head + ". " if head else "") + text[start:end].strip())
        start = end
    return out


# ---------------------------------------------------------------- index
class VectorIndex:
    """The meaning index of one store, kept up to date in the background."""

    def __init__(self, store, folder=None, embedder=None, opener=None, clock=time.time):
        self.store = store
        self.folder = Path(folder) if folder else Path(store.root) / "models" / MODEL_ID
        self.model = embedder
        self.opener = opener or urllib.request.urlopen
        self.clock = clock
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread = None
        self.cache = None
        self.status = {"state": "waiting", "message": "Meaning search starts after the first reference material is added."}
        store.knowledge_vectors = self

    # ------------------------------------------------------------ setup
    def runtime_installed(self):
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
        except Exception:
            return False
        return True

    def _files_ready(self):
        for name, (_, sha, size) in FILES.items():
            path = self.folder / name
            if not path.is_file() or path.stat().st_size != size:
                return False
        marker = self.folder / "verified.json"
        return marker.is_file() and json.loads(marker.read_text(encoding="utf-8")).get("revision") == REVISION

    def download(self, progress=None):
        """Fetch the model files at the pinned revision; each must match its SHA-256."""
        self.folder.mkdir(parents=True, exist_ok=True)
        total = sum(size for _, _, size in FILES.values())
        done = 0
        for name, (path, sha, size) in FILES.items():
            target = self.folder / name
            if target.is_file() and target.stat().st_size == size and _sha256(target) == sha:
                done += size
                continue
            part = target.with_suffix(target.suffix + ".download")
            digest = hashlib.sha256()
            request = urllib.request.Request(SOURCE.format(revision=REVISION, path=path),
                                             headers={"User-Agent": "Hivemind-Assembly"})
            with self.opener(request, timeout=120) as response, open(part, "wb") as out:
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    out.write(block)
                    digest.update(block)
                    done += len(block)
                    if progress:
                        progress(min(99, done * 100 // total))
            if digest.hexdigest() != sha:
                part.unlink(missing_ok=True)
                raise ValueError(f"The downloaded {name} doesn't match its SHA-256; it wasn't used.")
            os.replace(part, target)
        (self.folder / "verified.json").write_text(json.dumps({"model": MODEL_ID, "revision": REVISION}), encoding="utf-8")

    def embedder(self):
        if self.model is None:
            self.model = OnnxEmbedder(self.folder)
        return self.model

    # ------------------------------------------------------------ status
    def _set(self, state, message, **extra):
        with self.lock:
            self.status = {"state": state, "message": message, **extra}

    def view(self):
        with self.lock:
            return dict(self.status)

    def _counts(self):
        prose = ",".join(f"'{k}'" for k in sorted(PROSE))
        total = self.store.one(
            f"SELECT COUNT(*) AS n FROM sources WHERE json_extract(extraction,'$.kind') IN ({prose})")["n"]
        done = self.store.one("SELECT COUNT(*) AS n FROM knowledge_vector_sources WHERE model=?", (MODEL_ID,))["n"]
        return total, done

    def pending(self):
        prose = ",".join(f"'{k}'" for k in sorted(PROSE))
        return [r["id"] for r in self.store.rows(
            f"SELECT id FROM sources WHERE json_extract(extraction,'$.kind') IN ({prose}) "
            "AND id NOT IN (SELECT source FROM knowledge_vector_sources WHERE model=?) ORDER BY created",
            (MODEL_ID,),
        )]

    # ------------------------------------------------------------ building
    def build(self, limit=None):
        """Index every prose document that has no current vectors. Returns how many."""
        todo = self.pending()[:limit] if limit else self.pending()
        if not todo:
            total, done = self._counts()
            self._set("ready", f"Meaning search is ready ({done} documents).", documents=done)
            return 0
        model = self.embedder()
        total, done = self._counts()
        for n, key in enumerate(todo):
            if self.stopping.is_set():
                break
            rows = self.store.rows("SELECT section,title,body FROM knowledge_sections WHERE source=? ORDER BY ord", (key,))
            pieces = [(r["section"], i, text) for r in rows for i, text in enumerate(chunks(r["title"], r["body"]))]
            vectors = []
            for start in range(0, len(pieces), BATCH):
                if self.stopping.is_set():
                    return n
                batch = pieces[start: start + BATCH]
                vectors.extend(model.embed([text for _, _, text in batch]))
                time.sleep(0.001)  # Let other work run between batches.
            with self.store.tx() as db:
                exists = db.execute("SELECT 1 FROM sources WHERE id=?", (key,)).fetchone()
                db.execute("DELETE FROM knowledge_vectors WHERE source=?", (key,))
                db.execute("DELETE FROM knowledge_vector_sources WHERE source=?", (key,))
                if exists:
                    db.executemany(
                        "INSERT INTO knowledge_vectors(source,section,chunk,vector) VALUES(?,?,?,?)",
                        [(key, s, i, _pack(v)) for (s, i, _), v in zip(pieces, vectors)],
                    )
                    db.execute("INSERT INTO knowledge_vector_sources VALUES(?,?,?)", (key, MODEL_ID, len(pieces)))
            self._set("indexing", f"Preparing meaning search: {done + n + 1} of {total} documents.",
                      percent=int((done + n + 1) * 100 / max(1, total)))
        total, done = self._counts()
        self._set("ready", f"Meaning search is ready ({done} documents).", documents=done)
        return len(todo)

    def start(self, every=60):
        """Keep the index current in the background (download the model on first need)."""

        def loop():
            while not self.stopping.is_set():
                try:
                    self._step()
                except Exception as error:  # Shown on the reference page; word search goes on.
                    self._set("unavailable", f"Meaning search isn't available ({error}); word search is used.")
                self.wake.wait(every)
                self.wake.clear()

        if self.thread is None:
            self.thread = threading.Thread(target=loop, daemon=True)
            self.thread.start()

    def poke(self):
        self.wake.set()

    def close(self):
        self.stopping.set()
        self.wake.set()

    def _step(self):
        if not self.pending():
            total, done = self._counts()
            if done:
                self._set("ready", f"Meaning search is ready ({done} documents).", documents=done)
            return
        if not self.runtime_installed():
            self._set("unavailable", "Meaning search needs ONNX Runtime; run Install required tools under Settings. Word search is used.")
            return
        if self.model is None and not self._files_ready():
            self._set("downloading", "Downloading the meaning search model (23 MB, once)…", percent=0)
            self.download(lambda p: self._set("downloading", f"Downloading the meaning search model (23 MB, once): {p}%", percent=p))
        self.build()

    # ------------------------------------------------------------ search
    def _matrix(self):
        np = __import__("numpy")
        stamp = self.store.one("SELECT COUNT(*) AS n, COALESCE(MAX(rowid),0) AS m FROM knowledge_vectors")
        key = (stamp["n"], stamp["m"])
        with self.lock:
            if self.cache and self.cache[0] == key:
                return self.cache[1:]
        rows = self.store.rows("SELECT source,section,vector FROM knowledge_vectors ORDER BY rowid")
        if not rows:
            matrix = np.zeros((0, OnnxEmbedder.dims), dtype=np.float32)
        else:
            matrix = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float16).reshape(len(rows), -1).astype(np.float32)
        places = [(r["source"], r["section"]) for r in rows]
        numbers = {}
        # Sources as small numbers: choosing the allowed ones is then quick.
        sources = np.array([numbers.setdefault(r["source"], len(numbers)) for r in rows], dtype=np.int32)
        with self.lock:
            self.cache = (key, places, (numbers, sources), matrix)
        return places, (numbers, sources), matrix

    def search(self, query, allowed, limit=50):
        """[(source, section, similarity)] for sections of the allowed sources, best first."""
        if not allowed or not query.strip():
            return []
        if self.model is None and not (self.runtime_installed() and self._files_ready()):
            return []
        np = __import__("numpy")
        places, (numbers, sources), matrix = self._matrix()
        if not len(places):
            return []
        mask = np.isin(sources, np.array([numbers[a] for a in allowed if a in numbers], dtype=np.int32))
        if not mask.any():
            return []
        query_vector = self.embedder().embed([query])[0].astype(np.float32)
        scores = matrix @ query_vector
        scores[~mask] = -2.0
        best = {}
        for i in np.argsort(-scores)[: limit * 6]:
            if scores[i] <= -2.0:
                break
            place = places[i]
            if place not in best:
                best[place] = float(scores[i])
                if len(best) >= limit:
                    break
        return [(s, sec, score) for (s, sec), score in best.items()]


def _pack(vector):
    import numpy

    return numpy.asarray(vector, dtype=numpy.float16).tobytes()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fuse(word_ranked, meaning_ranked, limit):
    """Reciprocal rank fusion of two best-first lists of (source, section) places."""
    scores = {}
    for ranked in (word_ranked, meaning_ranked):
        for rank, place in enumerate(ranked, 1):
            scores[place] = scores.get(place, 0.0) + 1.0 / (RRF + rank)
    return sorted(scores, key=lambda p: -scores[p])[:limit], scores
