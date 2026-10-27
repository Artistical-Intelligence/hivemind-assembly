"""The owner's reference material: import, ranked search, and the assistants' tools.

Each imported file becomes one source with named sections (see documents.py). Its
original bytes and pictures are kept as restricted artifacts. Sections are indexed
with SQLite FTS5 for ranked search; titles and other names (front matter aliases,
document titles) can be looked up directly. Importing the same file again replaces
the previous copy instead of adding a second one.

Access never widens: the adviser and the assistants' tools see only material whose
categories the task's knowledge scope allows, and only material the owner allowed to
be sent to the AI services. Pictures never make a document "partly read"; pictures
without a caption or alt text are listed as not yet described.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path, PurePosixPath
from posixpath import normpath

from hivemind_assembly.core.artifacts import Artifacts
from hivemind_assembly.core.common import (
    Blocked,
    ContractError,
    canonical,
    file_hash,
    uid,
)

from . import documents
from .scopes import KnowledgeScopes

TEXT = {".txt", ".rst", ".log", ".tex", ".org", ".adoc", ".asciidoc", ".text", ".me", ".nfo"}
CODE = {
    ".py", ".pyw", ".ps1", ".psm1", ".psd1", ".bat", ".cmd", ".sh", ".bash", ".zsh", ".fish", ".c", ".h", ".cc",
    ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".inl", ".cs", ".java", ".kt", ".kts", ".scala", ".js", ".mjs", ".cjs",
    ".ts", ".tsx", ".jsx", ".go", ".rs", ".lua", ".rb", ".php", ".pl", ".pm", ".swift", ".m", ".mm", ".asm", ".s",
    ".inc", ".sql", ".r", ".gd", ".gdscript", ".cmake", ".mk", ".vb", ".vbs", ".ahk", ".au3", ".ll", ".patch",
    ".diff", ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml",
    ".css", ".scss", ".less", ".gradle", ".properties", ".proto", ".glsl", ".hlsl", ".vert", ".frag", ".shader",
    ".dart", ".zig", ".nim", ".v", ".sv", ".vhd", ".vhdl", ".tcl", ".el", ".clj", ".hs", ".ml", ".fs", ".ex",
    ".exs", ".erl", ".jl", ".ipynb", ".reg", ".def", ".ld", ".idc", ".gitignore", ".gitattributes", ".editorconfig",
}
CODE_NAMES = {"makefile", "dockerfile", "cmakelists.txt", "rakefile", "gemfile", "procfile", "license", "readme", "copying"}
EXCERPT = 1200  # Characters of each search hit sent with it; open_section gives the rest.
PAGE = 12000  # Characters per open_section answer.


def kind_of(name):
    """What a file is for import: word, markdown, html, pdf, text, code, or None."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".docx":
        return "word"
    if suffix in documents.MARKDOWN:
        return "markdown"
    if suffix in documents.HTML:
        return "html"
    if suffix == ".pdf":
        return "pdf"
    if suffix in TEXT:
        return "text"
    if suffix in CODE or PurePosixPath(name).name.lower() in CODE_NAMES:
        return "code"
    return None


def normal_name(name):
    return " ".join(str(name).lower().split())[:200]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def fts_query(text):
    words = [w for w in re.findall(r"\w+", str(text).lower()) if len(w) > 1 or w.isdigit()]
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in list(dict.fromkeys(words))[:32])


class Knowledge:
    def __init__(self, store):
        self.store = store
        self.artifacts = Artifacts(store)
        self.scopes = KnowledgeScopes(store)
        self.scopes.migrate()
        self.fts = self._index()

    # ------------------------------------------------------------- the index
    def _index(self):
        """FTS5 ranked search over sections (built once; older imports are added)."""
        ready = getattr(self.store, "knowledge_fts", None)
        if ready is not None:
            return ready
        try:
            with self.store.lock:
                self.store.db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(title, names, body, "
                    "content='knowledge_sections', content_rowid='rowid', tokenize='porter unicode61 remove_diacritics 2')"
                )
            fts = True
        except sqlite3.OperationalError:
            fts = False  # Without FTS5, search falls back to counting words.
        self.store.knowledge_fts = fts
        missing = self.store.rows(
            "SELECT * FROM sources WHERE id NOT IN (SELECT DISTINCT source FROM knowledge_sections)"
        )
        for row in missing:
            sections = json.loads(row["sections"])
            title = PurePosixPath(row["name"]).stem
            for s in sections:
                s.setdefault("title", title if s["id"] == "1" else f"{row['name']} (part {s['id']})")
            with self.store.tx() as db:
                self._write_sections(db, row["id"], sections, title, [])
        self.fts = fts
        self._upgrade()
        return fts

    def _upgrade(self):
        """Read documents imported by older versions again, from the original HA kept:
        Word files get their heading sections, tables and pictures, and a picture no
        longer marks them as partly read. IDs, categories and permission stay."""
        import tempfile

        for row in self.store.rows("SELECT id,name,external_allowed,extraction FROM sources"):
            extraction = json.loads(row["extraction"])
            if (
                extraction.get("format") == 2
                or not extraction.get("original_artifact")
                or kind_of(row["name"]) is None
                or self.store.rows("SELECT 1 FROM records WHERE kind='knowledge_upgrade_failed' AND id=?", (row["id"],))
            ):
                continue
            try:
                data = self.artifacts.read(extraction["original_artifact"], "controller")
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / PurePosixPath(row["name"]).name
                    path.write_bytes(data)
                    self.ingest(path, bool(row["external_allowed"]), None, {"kind": "legacy", "name": row["name"]},
                                display=row["name"], replace=row["id"])
                self.store.event(row["id"], "knowledge_source_upgraded", {"message": f"{row['name']} was read again with headings, tables and pictures."})
            except Exception as error:
                self.store.put("knowledge_upgrade_failed", row["id"], {"reason": str(error)[:300]})

    def _legacy(self, name):
        """A document with this name that an older version imported (it didn't record
        where documents came from), so adding the file again replaces it."""
        rows = self.store.rows(
            "SELECT id FROM sources WHERE lower(name)=lower(?) AND (json_extract(extraction,'$.origin') IS NULL "
            "OR json_extract(extraction,'$.origin.kind')='legacy')",
            (name,),
        )
        # Only when exactly one matches; with several, HA doesn't guess which.
        return rows[0]["id"] if len(rows) == 1 else None

    def _write_sections(self, db, key, sections, title, names):
        for ord_, s in enumerate(sections):
            extra = [*(names if s["id"] == sections[0]["id"] else []), *s.get("path", [])[:-1]]
            if s["id"] == sections[0]["id"] and title and title != s.get("title"):
                extra.append(title)
            cur = db.execute(
                "INSERT INTO knowledge_sections(source,section,ord,title,names,body,level,path,links,pictures) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    key, s["id"], ord_, s.get("title") or title, " · ".join(extra), s["text"], s.get("level", 0),
                    documents.dumps(s.get("path", [])), documents.dumps(s.get("links", [])),
                    documents.dumps(s.get("pictures", [])),
                ),
            )
            if self.fts:
                db.execute(
                    "INSERT INTO knowledge_fts(rowid,title,names,body) VALUES(?,?,?,?)",
                    (cur.lastrowid, s.get("title") or title, " · ".join(extra), s["text"]),
                )
            for name in {normal_name(n) for n in [s.get("title") or "", *(extra if s["id"] == sections[0]["id"] else [])] if n}:
                db.execute("INSERT INTO knowledge_names VALUES(?,?,?)", (name, key, s["id"]))

    def _clear_sections(self, db, key):
        if self.fts:
            for row in db.execute("SELECT rowid,title,names,body FROM knowledge_sections WHERE source=?", (key,)).fetchall():
                db.execute(
                    "INSERT INTO knowledge_fts(knowledge_fts,rowid,title,names,body) VALUES('delete',?,?,?,?)", tuple(row)
                )
        db.execute("DELETE FROM knowledge_sections WHERE source=?", (key,))
        db.execute("DELETE FROM knowledge_names WHERE source=?", (key,))

    # ---------------------------------------------------------------- import
    def origin_source(self, origin):
        rows = self.store.rows("SELECT source FROM knowledge_origins WHERE origin=?", (canonical(origin),))
        if rows and self.store.rows("SELECT 1 FROM sources WHERE id=?", (rows[0]["source"],)):
            return rows[0]["source"]
        return None

    def ingest(self, path, external_allowed=False, tags=None, origin=None, kind=None, image=None, display=None,
               replace=None):
        """Import one file; importing it again replaces the previous copy."""
        p = Path(path)
        origin = origin or {"kind": "file", "path": str(p.resolve())}
        previous = replace or self.origin_source(origin) or (self._legacy(p.name) if origin["kind"] == "file" else None)
        if tags is None:
            tags = self.scopes.tags("source", previous) if previous else ["unclassified"]
        tags = self.scopes.validate_tags(tags)
        revision = file_hash(p)
        if previous:
            old = self.store.one("SELECT revision,external_allowed,extraction FROM sources WHERE id=?", (previous,))
            if (
                old["revision"] == revision
                and bool(old["external_allowed"]) == bool(external_allowed)
                and self.scopes.tags("source", previous) == tags
                and json.loads(old["extraction"]).get("format") == 2
            ):
                kept = json.loads(old["extraction"])
                if kept.get("origin") != origin:
                    # The same file, now known by where it is: later imports find it there.
                    kept["origin"] = origin
                    with self.store.tx() as db:
                        db.execute("UPDATE sources SET extraction=? WHERE id=?", (canonical(kept), previous))
                        db.execute(
                            "INSERT INTO knowledge_origins VALUES(?,?) ON CONFLICT(origin) DO UPDATE SET source=excluded.source",
                            (canonical(origin), previous),
                        )
                return {"id": previous, "revision": revision, "unchanged": True, "tags": tags,
                        **kept, "sections": kept.get("counts", {}).get("sections", 0)}
        kind = kind or kind_of(p.name) or "unsupported"
        gaps = []
        if kind == "unsupported":
            parsed = documents.Parsed(p.stem, [], [], ["Unsupported extraction format; original preserved"])
        else:
            try:
                parsed = documents.parse(p, kind, image, display)
            except Exception as error:
                raise ContractError(f"{display or p.name} couldn't be read: {error}") from None
        gaps += parsed.gaps
        artifact = self.artifacts.add_file(p, p.name, classification="restricted")
        pictures = []
        for picture in parsed.pictures:
            data = picture.get("data")
            stored = self.artifacts.add(data, picture["name"], classification="restricted") if data else None
            described = picture.get("caption") or picture.get("alt") or ""
            pictures.append({
                "id": picture["id"],
                "section": picture.get("section", "1"),
                "name": picture["name"],
                "artifact": stored["id"] if stored else None,
                "size": len(data) if data else 0,
                "alt": picture.get("alt", ""),
                "caption": picture.get("caption", ""),
                "described": bool(described),
                "description": described,
                "viewable": bool(data) and picture.get("suffix") in documents.VIEWABLE,
                "linked": bool(picture.get("external")),
            })
        sections = [
            {k: s[k] for k in ("id", "title", "level", "path", "text", "links", "pictures")} for s in parsed.sections
        ]
        counts = documents.summary(parsed)
        extraction = {
            "format": 2,
            "status": "partial" if gaps else "text_extracted",
            "gaps": gaps,
            "kind": kind,
            "title": parsed.title,
            "names": parsed.names,
            "counts": counts,
            "images": [p["name"] for p in pictures],
            "pictures": pictures,
            "original_artifact": artifact["id"],
            "original_sha256": revision,
            "origin": origin,
        }
        name = display or p.name
        with self.store.tx() as db:
            key = previous or uid("source")
            if previous:
                self._clear_sections(db, key)
                db.execute(
                    "UPDATE sources SET name=?,revision=?,external_allowed=?,extraction=?,sections=?,created=? WHERE id=?",
                    (name, revision, int(bool(external_allowed)), canonical(extraction), canonical(sections), time.time(), key),
                )
            else:
                db.execute(
                    "INSERT INTO sources VALUES(?,?,?,?,?,?,?)",
                    (key, name, revision, int(bool(external_allowed)), canonical(extraction), canonical(sections), time.time()),
                )
            if sections:
                self._write_sections(db, key, sections, parsed.title, parsed.names)
            db.execute(
                "INSERT INTO knowledge_origins VALUES(?,?) ON CONFLICT(origin) DO UPDATE SET source=excluded.source",
                (canonical(origin), key),
            )
        if not previous or self.scopes.tags("source", key) != tags:
            self.scopes.assign("source", key, tags)
        return {
            "tags": tags,
            "id": key,
            "revision": revision,
            "replaced": bool(previous),
            **extraction,
            "sections": len(sections),
        }

    def waiting_pictures(self, key):
        """Pictures with no caption, alt text or description that an assistant could look at."""
        row = self.store.one("SELECT extraction FROM sources WHERE id=?", (key,))
        return [
            p for p in json.loads(row["extraction"]).get("pictures", [])
            if not p.get("described") and p.get("viewable") and p.get("artifact")
        ]

    def describe(self, key, revision, descriptions, by="adviser"):
        """Record picture descriptions. Each appears in its section's text, so search finds it."""
        with self.store.tx() as db:
            row = db.execute("SELECT revision,extraction,sections FROM sources WHERE id=?", (key,)).fetchone()
            if row is None or row["revision"] != revision:
                raise Blocked("The document changed; ask again for its current pictures.")
            extraction, sections = json.loads(row["extraction"]), json.loads(row["sections"])
            added = {}
            for p in extraction.get("pictures", []):
                text = " ".join(str(descriptions.get(p["id"], "")).split())
                if text and not p.get("described"):
                    p.update(described=True, description=text, described_by=by)
                    added.setdefault(p["section"], []).append(p)
            if not added:
                return 0
            counts = extraction.setdefault("counts", {})
            counts["pictures_not_described"] = sum(1 for p in extraction["pictures"] if not p.get("described"))

            def text_with(body, pictures):
                for p in pictures:
                    marker, full = f"[Picture {p['id']}]", f"[Picture {p['id']}: {p['description']}]"
                    body = body.replace(marker, full) if marker in body else body + "\n\n" + full
                return body

            for s in sections:
                if s["id"] in added:
                    s["text"] = text_with(s["text"], added[s["id"]])
            db.execute(
                "UPDATE sources SET extraction=?,sections=? WHERE id=?",
                (canonical(extraction), canonical(sections), key),
            )
            for section, pictures in added.items():
                old = db.execute(
                    "SELECT rowid,title,names,body FROM knowledge_sections WHERE source=? AND section=?", (key, section)
                ).fetchone()
                if old is None:
                    continue
                body = text_with(old["body"], pictures)
                if self.fts:
                    db.execute(
                        "INSERT INTO knowledge_fts(knowledge_fts,rowid,title,names,body) VALUES('delete',?,?,?,?)", tuple(old)
                    )
                    db.execute(
                        "INSERT INTO knowledge_fts(rowid,title,names,body) VALUES(?,?,?,?)",
                        (old["rowid"], old["title"], old["names"], body),
                    )
                db.execute("UPDATE knowledge_sections SET body=? WHERE rowid=?", (body, old["rowid"]))
        return sum(len(p) for p in added.values())

    def remove(self, key):
        """Forget an imported copy (its file was removed from the imported folder)."""
        with self.store.tx() as db:
            self._clear_sections(db, key)
            db.execute("DELETE FROM sources WHERE id=?", (key,))
            db.execute("DELETE FROM knowledge_assignments WHERE kind='source' AND item_id=?", (key,))
            db.execute("DELETE FROM knowledge_origins WHERE source=?", (key,))

    # ---------------------------------------------------------------- access
    def source(self, key, role, external=False, task=None):
        if role not in ("adviser", "ingestion", "controller"):
            raise Blocked("Source collection is restricted")
        if role == "adviser":
            self.scopes.check(task, "source", key)
        row = self.store.one("SELECT * FROM sources WHERE id=?", (key,))
        if external and not row["external_allowed"]:
            raise Blocked("Source not authorized for external processing")
        row["sections"] = json.loads(row["sections"])
        row["extraction"] = json.loads(row["extraction"])
        return row

    def allowed(self, role, external, task):
        """The sources this role may read for this task, with their revisions."""
        if role not in ("adviser", "controller", "worker"):
            raise Blocked("Restricted search")
        rows = self.store.rows("SELECT id,revision,external_allowed FROM sources")
        if external or role == "worker":
            rows = [r for r in rows if r["external_allowed"]]
        if role == "controller":
            return {r["id"]: r["revision"] for r in rows}
        scope = set(self.scopes.require(task)["tags"])
        tags = {
            r["item_id"]: set(json.loads(r["tags"]))
            for r in self.store.rows("SELECT item_id,tags FROM knowledge_assignments WHERE kind='source'")
        }
        return {r["id"]: r["revision"] for r in rows if tags.get(r["id"], {"unclassified"}) & scope}

    def search(self, query, role="adviser", external=False, task=None, limit=20):
        """Ranked search (FTS5, BM25) within what this role and task may read."""
        allowed = self.allowed(role, external, task)
        match = fts_query(query)
        if not allowed or not match:
            return []
        limit = max(1, min(50, int(limit)))
        if self.fts:
            with self.store.lock:
                rows = self.store.db.execute(
                    "SELECT s.source,s.section,s.title,s.path,s.body,"
                    "snippet(knowledge_fts,2,'«','»',' … ',24) AS snippet,"
                    "bm25(knowledge_fts,8.0,4.0,1.0) AS rank "
                    "FROM knowledge_fts JOIN knowledge_sections s ON s.rowid=knowledge_fts.rowid "
                    "WHERE knowledge_fts MATCH ? AND s.source IN (SELECT value FROM json_each(?)) "
                    "ORDER BY rank LIMIT ?",
                    (match, json.dumps(sorted(allowed)), limit),
                ).fetchall()
            found = [(dict(r), -r["rank"]) for r in rows]
        else:
            terms = [w.strip('"') for w in match.split(" OR ")]
            found = []
            for r in self.store.rows(
                "SELECT source,section,title,path,body FROM knowledge_sections WHERE source IN (SELECT value FROM json_each(?))",
                (json.dumps(sorted(allowed)),),
            ):
                text = (r["title"] + " " + r["body"]).lower()
                score = sum(text.count(t) for t in terms)
                if score:
                    found.append(({**r, "snippet": r["body"][:200]}, score))
            found = sorted(found, key=lambda x: -x[1])[:limit]
        hits = []
        for r, score in found:
            hits.append({
                "source": r["source"],
                "revision": allowed[r["source"]],
                "section": r["section"],
                "title": r["title"],
                "path": json.loads(r["path"]),
                "snippet": r["snippet"],
                "text": r["body"][:EXCERPT],
                "truncated": len(r["body"]) > EXCERPT,
                "score": round(score, 3),
            })
        return hits

    def lookup(self, name, role="adviser", external=False, task=None):
        """Sections whose title or other name is exactly this (any letter case)."""
        allowed = self.allowed(role, external, task)
        rows = self.store.rows(
            "SELECT DISTINCT n.source,n.section,s.title,s.path FROM knowledge_names n "
            "JOIN knowledge_sections s ON s.source=n.source AND s.section=n.section "
            "WHERE n.name=? AND n.source IN (SELECT value FROM json_each(?)) ORDER BY s.source,s.ord LIMIT 50",
            (normal_name(name), json.dumps(sorted(allowed))),
        )
        return [{**r, "path": json.loads(r["path"]), "revision": allowed[r["source"]]} for r in rows]

    def _section(self, key, section):
        rows = self.store.rows("SELECT * FROM knowledge_sections WHERE source=? AND section=?", (key, str(section)))
        if not rows:
            raise ContractError("That section doesn't exist in this document.")
        return rows[0]

    def _check(self, task, key, role="worker"):
        allowed = self.allowed(role, True, task)
        if key not in allowed:
            if self.store.rows("SELECT 1 FROM sources WHERE id=?", (key,)):
                raise Blocked("That material is outside this project's categories, or not allowed to be sent to the assistants.")
            raise ContractError("Unknown reference document.")
        return allowed[key]

    def open_section(self, task, key, section, offset=0, role="worker"):
        revision = self._check(task, key, role)
        row = self._section(key, section)
        extraction = json.loads(self.store.one("SELECT extraction FROM sources WHERE id=?", (key,))["extraction"])
        names = {p["id"]: p for p in extraction.get("pictures", [])}
        offset = max(0, int(offset))
        body = row["body"]

        def beside(step):
            found = self.store.rows(
                "SELECT section FROM knowledge_sections WHERE source=? AND ord=?", (key, row["ord"] + step)
            )
            return found[0]["section"] if found else None

        return {
            "source": key,
            "revision": revision,
            "document": self.store.one("SELECT name FROM sources WHERE id=?", (key,))["name"],
            "section": row["section"],
            "title": row["title"],
            "path": json.loads(row["path"]),
            "text": body[offset:offset + PAGE],
            "offset": offset,
            "next_offset": offset + PAGE if offset + PAGE < len(body) else None,
            "length": len(body),
            "links": [{"link": i, **l} for i, l in enumerate(json.loads(row["links"]))],
            "pictures": [
                {
                    "id": pid,
                    "description": names.get(pid, {}).get("description") or "Not yet described",
                    "described": bool(names.get(pid, {}).get("described")),
                    "can_be_shown": bool(names.get(pid, {}).get("viewable")),
                }
                for pid in json.loads(row["pictures"])
            ],
            "previous_section": beside(-1),
            "next_section": beside(1),
        }

    def follow_link(self, task, key, section, link, role="worker"):
        self._check(task, key, role)
        links = json.loads(self._section(key, section)["links"])
        if not isinstance(link, int) or not 0 <= link < len(links):
            raise ContractError("Choose a link number from the section's links.")
        target = links[link]
        if target["kind"] == "external":
            return {"link": link, "url": target["url"], "text": target.get("text", ""),
                    "note": "An outside web page. HA doesn't open web pages for the assistants."}
        if target["kind"] == "internal":
            return {"link": link, "followed": self.open_section(task, key, target["section"], role=role)}
        origin = json.loads(self.store.one("SELECT extraction FROM sources WHERE id=?", (key,))["extraction"]).get("origin", {})
        path, _, anchor = target.get("target", "").partition("#")
        if origin.get("kind") != "collection" or not path:
            if anchor:
                found = self._anchor(key, anchor)
                if found:
                    return {"link": link, "followed": self.open_section(task, key, found, role=role)}
            raise ContractError("That link points to a file that wasn't imported with this document.")
        here = PurePosixPath(origin["path"]).parent.as_posix()
        joined = normpath((here + "/" if here != "." else "") + path)
        other = self.origin_source({**origin, "path": joined})
        if other is None:
            raise ContractError(f"{joined} wasn't imported with this collection.")
        found = self._anchor(other, anchor) if anchor else None
        return {"link": link, "followed": self.open_section(task, other, found or "1", role=role)}

    def _anchor(self, key, anchor):
        wanted = slug(anchor)
        for row in self.store.rows("SELECT section,title FROM knowledge_sections WHERE source=? ORDER BY ord", (key,)):
            if slug(row["title"]) == wanted:
                return row["section"]
        return None

    def pictures(self, task, key, section, ids=None, role="worker"):
        """A section's pictures as images the next turn can look at (at most 4 at once)."""
        self._check(task, key, role)
        row = self._section(key, section)
        wanted = json.loads(row["pictures"])
        if ids is not None:
            if not isinstance(ids, list) or any(i not in wanted for i in ids):
                raise ContractError("Choose pictures from this section's picture list.")
            wanted = ids
        extraction = json.loads(self.store.one("SELECT extraction FROM sources WHERE id=?", (key,))["extraction"])
        meta = {p["id"]: p for p in extraction.get("pictures", [])}
        images, listed = [], []
        for pid in wanted:
            p = meta.get(pid, {})
            item = {"id": pid, "description": p.get("description") or "Not yet described"}
            if p.get("viewable") and p.get("artifact") and len(images) < 4 and p.get("size", 0) <= 2_000_000:
                images.append({"name": f"{pid}{Path(p['name']).suffix.lower()}",
                               "data": self.artifacts.read(p["artifact"], "controller")})
                item["shown"] = True
            else:
                item["shown"] = False
                item["why_not"] = (
                    "a linked picture outside the document" if p.get("linked")
                    else "this picture format can't be shown" if not p.get("viewable")
                    else "too large to show, or more than 4 asked for at once"
                )
            listed.append(item)
        return {"source": key, "section": row["section"], "pictures": listed, "_images": images}

    TOOLS = ("search_knowledge", "lookup_knowledge", "open_section", "follow_link", "section_pictures")

    def tool(self, task, name, args):
        """The assistants' reference tools, limited to the project's allowed categories."""
        if not isinstance(args, dict):
            raise ContractError("Tool arguments must be an object.")

        def text(field, limit=500):
            value = args.get(field)
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                raise ContractError(f"{field} must be text of 1–{limit} characters.")
            return value

        if name == "search_knowledge":
            if set(args) - {"query", "limit"}:
                raise ContractError("search_knowledge takes query and an optional limit.")
            limit = args.get("limit", 10)
            if type(limit) is not int or not 1 <= limit <= 20:
                raise ContractError("limit must be 1–20.")
            hits = self.search(text("query"), "worker", True, task, limit)
            for h in hits:
                h.pop("text")
                h.pop("truncated")
            result = {"hits": hits}
            sources = {(h["source"], h["revision"]) for h in hits}
        elif name == "lookup_knowledge":
            if set(args) != {"name"}:
                raise ContractError("lookup_knowledge takes name.")
            found = self.lookup(text("name", 200), "worker", True, task)
            result = {"matches": found}
            sources = {(h["source"], h["revision"]) for h in found}
        else:
            key, section = text("source", 100), args.get("section")
            if not isinstance(section, (str, int)) or not str(section).isdigit():
                raise ContractError("section must be a section number from search or the document.")
            section = str(section)
            if name == "open_section":
                if set(args) - {"source", "section", "offset"}:
                    raise ContractError("open_section takes source, section and an optional offset.")
                offset = args.get("offset", 0)
                if type(offset) is not int or offset < 0:
                    raise ContractError("offset must be a whole number of characters.")
                result = self.open_section(task, key, section, offset)
                sources = {(result["source"], result["revision"])}
            elif name == "follow_link":
                if set(args) != {"source", "section", "link"}:
                    raise ContractError("follow_link takes source, section and link.")
                result = self.follow_link(task, key, section, args["link"])
                sources = {(key, self._check(task, key))}
                if "followed" in result:
                    sources.add((result["followed"]["source"], result["followed"]["revision"]))
            elif name == "section_pictures":
                if set(args) - {"source", "section", "pictures"}:
                    raise ContractError("section_pictures takes source, section and optional pictures.")
                result = self.pictures(task, key, section, args.get("pictures"))
                sources = {(key, self._check(task, key))}
            else:
                raise ContractError("Unknown reference tool.")
        result["_knowledge_grant"] = {
            "task": task,
            "sources": [{"source": s, "revision": r} for s, r in sorted(sources)],
        }
        return result

    # ---------------------------------------------------------------- reading
    def reading(self, obligations, role="adviser", external=True, task=None):
        records = []
        gaps = []
        for item in obligations:
            try:
                s = self.source(item["source"], role, external, task)
                if s["revision"] != item["revision"]:
                    raise Blocked("Required source revision changed")
                matches = [p for p in s["sections"] if p["id"] == item["section"]]
                if not matches:
                    raise Blocked("Required section is missing")
                records.append(
                    {
                        **item,
                        "text": matches[0]["text"],
                        "status": "retrieved",
                        "incorporation": "not_verified",
                    }
                )
                if s["extraction"]["gaps"] and item.get(
                    "requires_complete_extraction", True
                ):
                    raise Blocked("; ".join(s["extraction"]["gaps"]))
            except (Blocked, ContractError) as e:
                gaps.append(
                    {**item, "reason": str(e), "critical": item.get("critical", True)}
                )
        key = uid("reading")
        result = {
            "id": key,
            "records": records,
            "gaps": gaps,
            "critical_gaps": [g for g in gaps if g["critical"]],
            "coverage_claim": "Declared obligations only; undiscovered sources and comprehension are not certified",
        }
        self.store.put("reading", key, result)
        return result

    def authorize_excerpt(self, source, revision, section, project, task=None):
        if not task or self.store.task(task)["project_id"] != project:
            raise Blocked("Excerpt requires a matching scoped task")
        src = self.source(source, "adviser", external=True, task=task)
        if src["revision"] != revision:
            raise Blocked("Stale source")
        items = [p for p in src["sections"] if p["id"] == section]
        if not items:
            raise Blocked("Section missing")
        return self.artifacts.add(
            canonical(
                {
                    "source": source,
                    "revision": revision,
                    "section": section,
                    "text": items[0]["text"],
                }
            ),
            "excerpt.json",
            project,
            "task",
            knowledge_grant={"task": task, "source": source, "revision": revision},
        )
