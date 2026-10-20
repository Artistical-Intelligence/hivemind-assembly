from __future__ import annotations
import json, time, zipfile, xml.etree.ElementTree as ET
from pathlib import Path
from hivemind_assembly.core.common import (
    uid,
    file_hash,
    canonical,
    ContractError,
    Blocked,
)
from hivemind_assembly.core.artifacts import Artifacts
from .scopes import KnowledgeScopes


class Knowledge:
    def __init__(self, store):
        self.store = store
        self.artifacts = Artifacts(store)
        self.scopes = KnowledgeScopes(store)
        self.scopes.migrate()

    def ingest(self, path, external_allowed=False, tags=None):
        tags = self.scopes.validate_tags(tags if tags is not None else ["unclassified"])
        p = Path(path)
        raw = p.read_bytes()
        revision = file_hash(p)
        gaps = []
        sections = []
        images = []
        if p.suffix.lower() in (".md", ".txt", ".py", ".c", ".h", ".json", ".csv"):
            text = raw.decode("utf-8", errors="strict")
            # Normalize extraction only; the original bytes and revision stay intact.
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            sections = [
                {"id": str(i + 1), "text": part}
                for i, part in enumerate(text.split("\n\n"))
                if part.strip()
            ]
        elif p.suffix.lower() == ".docx":
            with zipfile.ZipFile(p) as z:
                ns = {
                    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                }
                root = ET.fromstring(z.read("word/document.xml"))
                for i, para in enumerate(root.findall(".//w:p", ns)):
                    text = "".join(t.text or "" for t in para.findall(".//w:t", ns))
                    if text:
                        sections.append({"id": str(i + 1), "text": text})
                images = [n for n in z.namelist() if n.startswith("word/media/")]
                if images:
                    gaps.append(
                        "Embedded images inventoried; visual interpretation pending"
                    )
                for name in z.namelist():
                    if name.endswith(".rels") and 'TargetMode="External"' in z.read(
                        name
                    ).decode("utf-8", errors="replace"):
                        gaps.append(
                            "External relationships require separate inspection"
                        )
                        break
        elif p.suffix.lower() == ".pdf":
            try:
                import pypdf

                reader = pypdf.PdfReader(p)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    sections.append({"id": str(i + 1), "text": text})
                    if not text.strip():
                        gaps.append(
                            f"Page {i + 1}: missing text; OCR/visual inspection required"
                        )
                gaps.append("PDF figures and layout require visual inspection")
            except ImportError:
                gaps.append("PDF text extraction dependency not installed")
        else:
            gaps.append("Unsupported extraction format; original preserved")
        key = uid("source")
        artifact = self.artifacts.add(raw, p.name, classification="restricted")
        extraction = {
            "status": "partial" if gaps else "text_extracted",
            "gaps": gaps,
            "images": images,
            "original_artifact": artifact["id"],
            "original_sha256": revision,
        }
        with self.store.tx() as c:
            c.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?,?,?)",
                (
                    key,
                    p.name,
                    revision,
                    int(external_allowed),
                    canonical(extraction),
                    canonical(sections),
                    time.time(),
                ),
            )
        self.scopes.assign("source", key, tags)
        return {
            "tags": tags,
            "id": key,
            "revision": revision,
            **extraction,
            "sections": len(sections),
        }

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

    def search(self, query, role="adviser", external=False, task=None):
        if role not in ("adviser", "controller"):
            raise Blocked("Restricted search")
        if role == "adviser":
            self.scopes.require(task)
        terms = query.lower().split()
        hits = []
        for row in self.store.rows("SELECT id FROM sources"):
            try:
                src = self.source(row["id"], role, external, task)
            except Blocked:
                continue
            for section in src["sections"]:
                score = sum(term in section["text"].lower() for term in terms)
                if score:
                    hits.append(
                        {
                            "source": src["id"],
                            "revision": src["revision"],
                            "section": section["id"],
                            "text": section["text"],
                            "score": score,
                        }
                    )
        return sorted(hits, key=lambda h: -h["score"])[:30]

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
