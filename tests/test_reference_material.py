"""Reference material: Word files with headings, tables and pictures; whole folders and
GitHub repositories (a local Git remote stands in for GitHub); FTS5 ranking; and the
assistants' reference tools, which stay within the project's categories."""

import base64
import json
import subprocess
import zipfile

import pytest

from hivemind_assembly.core.common import Blocked, ContractError
from hivemind_assembly.learning.collections import KnowledgeCollections
from hivemind_assembly.learning.knowledge import Knowledge
from hivemind_assembly.learning.scopes import KnowledgeScopes

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' \
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ' \
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' \
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'


def para(text, style=None, extra=""):
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{props}{extra}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def drawing(rid, alt):
    return (
        '<w:r><w:drawing><wp:inline><wp:docPr id="1" name="Picture"'
        + (f' descr="{alt}"' if alt else "")
        + '/><a:graphic><a:graphicData><pic:pic><pic:blipFill>'
        + f'<a:blip r:embed="{rid}"/></pic:blipFill></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
    )


def cell(text):
    return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"


def word(path, extra_heading="Tools"):
    """A small textbook: headings 1–3, a table, two pictures (one captioned), links."""
    body = "".join([
        para("Machine Guide", "Title"),
        para("Memory", "Heading1"),
        "<w:p><w:r><w:t xml:space=\"preserve\">See </w:t></w:r>"
        '<w:hyperlink r:id="rId10"><w:r><w:t>the manual</w:t></w:r></w:hyperlink>'
        "<w:r><w:t xml:space=\"preserve\"> and </w:t></w:r>"
        '<w:hyperlink w:anchor="regs"><w:r><w:t>the registers</w:t></w:r></w:hyperlink></w:p>',
        "<w:tbl><w:tr>" + cell("Address") + cell("Use") + "</w:tr><w:tr>" + cell("0x0000")
        + cell("Boot ROM") + "</w:tr><w:tr>" + cell("0x8000") + cell("Video RAM") + "</w:tr></w:tbl>",
        "<w:p>" + drawing("rId20", "Memory map") + "</w:p>",
        para("Figure 1: The memory map", "Caption"),
        para("Registers", "Heading2", '<w:bookmarkStart w:id="0" w:name="regs"/><w:bookmarkEnd w:id="0"/>'),
        para("The accumulator holds arithmetic results."),
        "<w:p>" + drawing("rId21", "") + "</w:p>",
        para(extra_heading, "Heading1"),
        para("Ghidra", "ListBullet"),
        para("REA", "ListBullet"),
        para("ghidra -import game.bin", "CodeBlock"),
        para("Decompiler", "Heading3"),
        para("Calling conventions decide where arguments live."),
    ])
    styles = "".join(
        f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/></w:style>'
        for sid, name in (("Title", "Title"), ("Heading1", "heading 1"), ("Heading2", "heading 2"),
                          ("Heading3", "heading 3"), ("Caption", "caption"), ("ListBullet", "List Bullet"),
                          ("CodeBlock", "CodeBlock"))
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId10" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com/manual" TargetMode="External"/>'
        '<Relationship Id="rId20" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>'
        '<Relationship Id="rId21" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image2.png"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", f"<w:styles {W}>{styles}</w:styles>")
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("word/media/image1.png", PNG)
        z.writestr("word/media/image2.png", PNG + b"2")
    return path


def test_word_file_becomes_sections_with_tables_pictures_and_links(store, tmp_path):
    knowledge = Knowledge(store)
    result = knowledge.ingest(word(tmp_path / "guide.docx"), True)
    # Pictures don't make the document partly read.
    assert result["status"] == "text_extracted" and result["gaps"] == []
    source = knowledge.source(result["id"], "controller")
    titles = [(s["title"], s["level"]) for s in source["sections"]]
    assert titles == [("Machine Guide", 0), ("Memory", 1), ("Registers", 2), ("Tools", 1), ("Decompiler", 3)]
    memory, registers, tools = source["sections"][1], source["sections"][2], source["sections"][3]
    # The table stays a table.
    assert "| Address | Use |\n| --- | --- |\n| 0x0000 | Boot ROM |\n| 0x8000 | Video RAM |" in memory["text"]
    # Pictures are separate images linked to their section, with caption or alt text.
    pictures = {p["id"]: p for p in source["extraction"]["pictures"]}
    assert pictures["p1"]["section"] == memory["id"] and pictures["p1"]["caption"] == "Figure 1: The memory map"
    assert pictures["p1"]["alt"] == "Memory map" and pictures["p1"]["described"]
    assert pictures["p2"]["section"] == registers["id"] and not pictures["p2"]["described"]
    assert knowledge.artifacts.read(pictures["p1"]["artifact"], "controller") == PNG
    assert "[Picture p1]" in memory["text"] and memory["pictures"] == ["p1"]
    # Links are recorded per section: outside by address, inside by section.
    assert {"kind": "external", "text": "the manual", "url": "https://example.com/manual"} in memory["links"]
    assert {"kind": "internal", "text": "the registers", "section": registers["id"]} in memory["links"]
    assert "- Ghidra\n\n- REA" in tools["text"] and "```\nghidra -import game.bin\n```" in tools["text"]
    assert source["sections"][4]["path"] == ["Tools", "Decompiler"]
    # Required reading of a section with a picture isn't blocked.
    reading = knowledge.reading(
        [{"source": result["id"], "revision": result["revision"], "section": memory["id"]}], role="controller"
    )
    assert reading["records"] and not reading["gaps"]
    assert knowledge.search("memory map", role="controller")[0]["section"] == memory["id"]


def test_importing_the_same_document_again_replaces_it(store, tmp_path):
    knowledge = Knowledge(store)
    path = word(tmp_path / "guide.docx")
    first = knowledge.ingest(path, True)
    assert knowledge.ingest(path, True)["unchanged"]
    word(path, extra_heading="Toolbox")
    second = knowledge.ingest(path, True)
    assert second["id"] == first["id"] and second["replaced"] and second["revision"] != first["revision"]
    assert store.one("SELECT COUNT(*) AS n FROM sources")["n"] == 1
    assert knowledge.search("toolbox", role="controller")[0]["title"] == "Toolbox"
    titles = [s["title"] for s in knowledge.source(first["id"], "controller")["sections"]]
    assert "Toolbox" in titles and "Tools" not in titles


def git(*args, cwd=None):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def collection(tmp_path):
    root = tmp_path / "Research"
    (root / "notes").mkdir(parents=True)
    (root / "guides").mkdir()
    (root / "src").mkdir()
    (root / "images").mkdir()
    (root / ".git").mkdir()
    (root / "notes" / "registers.md").write_text(
        "---\ntitle: CPU registers\ntags: [arithmetic, Audio Formats]\naliases: [regs, register file]\n---\n"
        "# Accumulator\n\nHolds results. ![Diagram](diagram.png)\n\nSee [the guide](../guides/book.docx) "
        "and [opcodes](https://example.com/opcodes).\n\n## Flags\n\nZero and carry.\n"
    )
    (root / "notes" / "diagram.png").write_bytes(PNG)
    word(root / "guides" / "book.docx")
    (root / "src" / "tool.py").write_text("def main():\n    return 0\n")
    (root / "data.bin").write_bytes(b"\0\1\2\3" * 100)
    (root / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0")
    with zipfile.ZipFile(root / "archive.zip", "w") as z:
        z.writestr("inside.md", "# Inside\n")
    (root / "images" / "unused.png").write_bytes(PNG)
    return root


def run(collections, entry):
    collections.running[entry["id"]].join(120)
    return collections._load()[entry["id"]]


def test_folder_import_takes_categories_lists_skips_and_replaces_on_reimport(store, tmp_path):
    root = collection(tmp_path)
    collections = KnowledgeCollections(store)
    entry = run(collections, collections.add({"kind": "folder", "folder": str(root), "external_allowed": True}))
    assert entry["state"] == "done", entry["message"]
    report = entry["report"]
    assert (report["documents"], report["imported"], report["failed"]) == (3, 3, [])
    reasons = {x["path"]: x["reason"] for x in report["skipped"]}
    assert reasons[".git/"] == "Git's own records"
    assert reasons["archive.zip"].startswith("archive (.zip)")
    assert reasons["data.bin"].startswith("binary data")
    assert reasons["old.doc"].startswith("old Word format")
    assert reasons["images/unused.png"] == "picture no imported document shows"
    assert "notes/diagram.png" not in reasons  # Shown by registers.md, so imported with it.
    scopes = KnowledgeScopes(store)
    knowledge = Knowledge(store)
    by_path = {json.loads(r["extraction"])["origin"]["path"]: r["id"]
               for r in store.rows("SELECT id,extraction FROM sources")}
    # Front matter tags first; otherwise folder names. The folder's own name is a category too.
    assert scopes.tags("source", by_path["notes/registers.md"]) == ["arithmetic", "audio-formats", "research"]
    assert scopes.tags("source", by_path["guides/book.docx"]) == ["guides", "research"]
    assert scopes.tags("source", by_path["src/tool.py"]) == ["research", "src"]
    notes = knowledge.source(by_path["notes/registers.md"], "controller")
    assert [s["title"] for s in notes["sections"]] == ["Accumulator", "Flags"]
    assert notes["extraction"]["pictures"][0]["viewable"]
    # Other names from the front matter can be looked up.
    assert knowledge.lookup("Register File", role="controller")[0]["source"] == by_path["notes/registers.md"]
    # Import again: changed files are read again, gone files are removed, nothing is doubled.
    (root / "notes" / "registers.md").write_text("# Accumulator\n\nHolds results, changed.\n")
    (root / "src" / "tool.py").unlink()
    (root / "notes" / "new.md").write_text("# New page\n\nFresh notes.\n")
    collections.start(entry["id"])
    entry = run(collections, entry)
    report = entry["report"]
    assert (report["updated"], report["unchanged"], report["imported"], report["removed"]) == (1, 1, 1, 1)
    assert store.one("SELECT COUNT(*) AS n FROM sources")["n"] == 3
    assert by_path["src/tool.py"] not in {r["id"] for r in store.rows("SELECT id FROM sources")}
    # Without front matter, registers.md now takes its folder's name.
    assert scopes.tags("source", by_path["notes/registers.md"]) == ["notes", "research"]


def test_github_repository_import_and_update(store, tmp_path):
    work = tmp_path / "work"
    (work / "docs").mkdir(parents=True)
    (work / "docs" / "intro.md").write_text("# Introduction\n\nStart here.\n")
    word(work / "book.docx")
    git("init", "-q", "-b", "main", cwd=work)
    git("add", ".", cwd=work)
    git("-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-qm", "first", cwd=work)
    remote = tmp_path / "github" / "owner" / "notes.git"
    git("clone", "-q", "--bare", str(work), str(remote))
    collections = KnowledgeCollections(store, remote_url=lambda owner, name: remote.as_uri())
    entry = run(collections, collections.add({"kind": "github", "repository": "owner/notes", "external_allowed": True,
                                              "schedule_minutes": 1440}))
    assert entry["state"] == "done", entry["message"]
    assert entry["report"]["documents"] == 2 and entry["commit"]
    assert KnowledgeScopes(store).tags("source", Knowledge(store).origin_source(
        {"kind": "collection", "collection": entry["id"], "path": "docs/intro.md"})) == ["docs", "notes"]
    collections.start(entry["id"])
    assert run(collections, entry)["message"] == "Already up to date with GitHub."
    (work / "docs" / "intro.md").write_text("# Introduction\n\nStart here, updated.\n")
    git("-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-qam", "second", cwd=work)
    git("push", "-q", str(remote), "main", cwd=work)
    collections.start(entry["id"])
    entry = run(collections, entry)
    assert entry["report"]["updated"] == 1 and entry["report"]["unchanged"] == 1
    hits = Knowledge(store).search("updated", role="controller")
    assert hits and hits[0]["title"] == "Introduction"
    # The scheduled update is due a day later.
    collections.clock = lambda: entry["last_check"] + 86400
    assert collections.due() == [entry["id"]]
    collections.running[entry["id"]].join(120)


def test_ranked_search_prefers_titles_and_relevant_sections(store, tmp_path):
    knowledge = Knowledge(store)
    (tmp_path / "a.md").write_text(
        "# Calling conventions\n\nWhere arguments go.\n\n# Graphics\n\n" + "Calling the renderer. " * 3 + "\n"
    )
    (tmp_path / "b.md").write_text("# Audio\n\nMixing samples.\n")
    knowledge.ingest(tmp_path / "a.md", True)
    knowledge.ingest(tmp_path / "b.md", True)
    hits = knowledge.search("calling conventions", role="controller")
    assert [h["title"] for h in hits] == ["Calling conventions", "Graphics"]
    assert hits[0]["score"] > hits[1]["score"] and "«" in hits[0]["snippet"]
    assert knowledge.lookup("CALLING CONVENTIONS", role="controller")[0]["title"] == "Calling conventions"


def test_identical_copies_of_a_section_come_back_once(store, tmp_path):
    scopes = KnowledgeScopes(store)
    scopes.create_tag("control-flow", "Control flow")
    knowledge = Knowledge(store)
    copy = "# Jump tables\n\nA switch becomes a table of addresses.\n\n# Loops\n\nCounting down.\n"
    for name in ("book.md", "draft.md", "snapshot.md"):
        (tmp_path / name).write_text(copy)
    (tmp_path / "notes.md").write_text("# Jump tables\n\nMy own notes on a switch table.\n")
    keys = [knowledge.ingest(tmp_path / n, True, tags=["control-flow"])["id"]
            for n in ("book.md", "draft.md", "snapshot.md", "notes.md")]
    assert len(set(keys)) == 4
    hits = knowledge.search("switch jump tables", role="controller", limit=2)
    # The copies don't crowd out the different section; where they are is still listed.
    assert [h["title"] for h in hits] == ["Jump tables", "Jump tables"]
    grouped = next(h for h in hits if h.get("copies"))
    assert {grouped["source"], *(c["source"] for c in grouped["copies"])} == set(keys[:3])
    assert next(h for h in hits if not h.get("copies"))["source"] == keys[3]
    # An assistant's answer depends on every copy it names, so each one is part of its grant.
    task = store.create_project("copies", "jump tables")
    scopes.select(task["id"], ["control-flow"], scopes.catalog()["revision"])
    found = knowledge.tool(task["id"], "search_knowledge", {"query": "switch jump tables", "limit": 2})
    assert {s["source"] for s in found["_knowledge_grant"]["sources"]} == set(keys)


def test_reference_tools_stay_within_the_projects_categories(store, tmp_path):
    scopes = KnowledgeScopes(store)
    scopes.create_tag("arithmetic", "Arithmetic")
    scopes.create_tag("audio", "Audio")
    knowledge = Knowledge(store)
    root = tmp_path / "Lib"
    (root / "math").mkdir(parents=True)
    (root / "sound").mkdir()
    (root / "math" / "adding.md").write_text(
        "---\ntags: [arithmetic]\n---\n# Adding\n\nCarry flags. ![Carry](carry.png) See [mixing](../sound/mixing.md).\n"
    )
    (root / "math" / "carry.png").write_bytes(PNG)
    (root / "sound" / "mixing.md").write_text("---\ntags: [audio]\n---\n# Mixing\n\nSECRET audio notes about carry.\n")
    collections = KnowledgeCollections(store)
    run(collections, collections.add({"kind": "folder", "folder": str(root), "external_allowed": True}))
    task = store.create_project("scoped", "arithmetic task")
    with pytest.raises(Blocked, match="scope"):
        knowledge.tool(task["id"], "search_knowledge", {"query": "carry"})
    scopes.select(task["id"], ["arithmetic"], scopes.catalog()["revision"])
    found = knowledge.tool(task["id"], "search_knowledge", {"query": "carry"})
    assert [h["title"] for h in found["hits"]] == ["Adding"]
    adding, mixing = found["hits"][0]["source"], knowledge.origin_source(
        {"kind": "collection", "collection": collections.view()[0]["id"], "path": "sound/mixing.md"})
    opened = knowledge.tool(task["id"], "open_section", {"source": adding, "section": "1"})
    assert "Carry flags" in opened["text"] and opened["pictures"][0]["can_be_shown"]
    with pytest.raises(Blocked, match="outside this project's categories"):
        knowledge.tool(task["id"], "open_section", {"source": mixing, "section": "1"})
    link = next(l["link"] for l in opened["links"] if l.get("target") == "../sound/mixing.md")
    with pytest.raises(Blocked, match="outside this project's categories"):
        knowledge.tool(task["id"], "follow_link", {"source": adding, "section": "1", "link": link})
    assert knowledge.tool(task["id"], "lookup_knowledge", {"name": "Mixing"})["matches"] == []
    shown = knowledge.tool(task["id"], "section_pictures", {"source": adding, "section": "1"})
    assert shown["_images"][0]["data"] == PNG and shown["pictures"][0]["shown"]
    with pytest.raises(ContractError):
        knowledge.tool(task["id"], "open_section", {"source": adding, "section": "1", "path": "../x"})
    # Material the owner didn't allow to be sent to the assistants stays out.
    with store.tx() as db:
        db.execute("UPDATE sources SET external_allowed=0 WHERE id=?", (adding,))
    assert knowledge.tool(task["id"], "search_knowledge", {"query": "carry"})["hits"] == []


def test_broker_reference_answers_follow_later_scope_changes(ready, tmp_path):
    from hivemind_assembly.core.broker import Broker

    controller, task, epoch = ready
    store = controller.store
    scopes = KnowledgeScopes(store)
    scopes.create_tag("arithmetic", "Arithmetic")
    (tmp_path / "adding.md").write_text("# Adding\n\nCarry flags matter.\n")
    Knowledge(store).ingest(tmp_path / "adding.md", True, ["arithmetic"])
    scopes.select(task["id"], ["arithmetic"], scopes.catalog()["revision"])
    # Choosing categories asks for a new briefing before the next step.
    controller.brief(task["id"], {"revision": 0}, {"procedure": "read", "acceptance": "cited"}, {"critical_gaps": []}, [])
    broker = Broker(controller, {})
    result = broker.execute({
        "id": "search-op", "task_id": task["id"], "owner": "worker.opus", "epoch": epoch, "revision": 0,
        "tool": "search_knowledge", "args": {"query": "carry"},
    })
    assert result["hits"][0]["title"] == "Adding" and "_knowledge_grant" not in result
    read = lambda: broker.artifacts.read(result["result_artifact"], "worker", task["project_id"], task=task["id"])
    assert b"Adding" in read()
    scopes.select(task["id"], [], scopes.catalog()["revision"])
    with pytest.raises(Blocked):
        read()


def test_adviser_describes_pictures_only_for_material_it_may_read(store, tmp_path):
    import asyncio
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace

    from hivemind_assembly.core.controller import Controller
    from hivemind_assembly.learning.curation import KnowledgeCuration

    knowledge = Knowledge(store)
    controller = Controller(store)
    sent = []

    class Browser:
        config = {"routes": {"adviser.extra": {"conversation_url": "pictures-only"}}}

        async def exchange(self, route, message, attachments=()):
            payload = json.loads(message["payload"])
            sent.append(([p["id"] for p in payload["pictures"]], [Path(a["path"]).name for a in attachments]))
            response = {
                "request_id": message["id"],
                "type": "picture_descriptions",
                "descriptions": [{"id": "p2", "description": "A register diagram with the accumulator"},
                                 {"id": "p9", "description": "Not one of the pictures asked about"}],
            }
            controller.message_state(message["id"], "validated", json.dumps(response))
            return response

    class Isolated:
        async def isolated_browser(self, task, route, identity):
            return Browser()

        async def release_isolated(self, identity):
            pass

    team = SimpleNamespace(
        store=store, controller=controller, sessions=Isolated(),
        observations={"adviser.extra": SimpleNamespace(eligible=lambda: True)},
        learning_budget=lambda *args: nullcontext(),
    )
    curation = KnowledgeCuration(team)
    private = knowledge.ingest(word(tmp_path / "private.docx"), False)
    with pytest.raises(Blocked, match="not authorized"):
        curation.queue_pictures(private["id"])
    allowed = knowledge.ingest(word(tmp_path / "guide.docx"), True)
    key = curation.queue_pictures(allowed["id"])["id"]
    asyncio.run(curation.supervise(key))
    assert curation.status(key)["stage"] == "completed" and curation.status(key)["described"] == 1
    # Only the picture without a caption or alt text was sent.
    assert sent == [(["p2"], ["p2.png"])]
    source = knowledge.source(allowed["id"], "controller")
    p2 = {p["id"]: p for p in source["extraction"]["pictures"]}["p2"]
    assert p2["described"] and p2["described_by"] == "adviser"
    assert source["extraction"]["counts"]["pictures_not_described"] == 0
    assert "[Picture p2: A register diagram with the accumulator]" in source["sections"][2]["text"]
    assert knowledge.search("accumulator diagram", role="controller")[0]["title"] == "Registers"
    with pytest.raises(ContractError, match="no pictures waiting"):
        curation.queue_pictures(allowed["id"])


def test_documents_from_older_versions_are_read_again_and_replaced_on_re_add(store, tmp_path):
    import hashlib
    import time

    from hivemind_assembly.core.artifacts import Artifacts
    from hivemind_assembly.core.common import canonical

    path = word(tmp_path / "guide.docx")
    raw = path.read_bytes()
    original = Artifacts(store).add(raw, "guide.docx", classification="restricted")
    # What versions before 0.33 stored: paragraphs, and a picture recorded as a gap.
    old = {
        "status": "partial",
        "gaps": ["Embedded images inventoried; visual interpretation pending"],
        "images": ["word/media/image1.png"],
        "original_artifact": original["id"],
        "original_sha256": hashlib.sha256(raw).hexdigest(),
    }
    with store.tx() as db:
        db.execute(
            "INSERT INTO sources VALUES(?,?,?,?,?,?,?)",
            ("source_old", "guide.docx", hashlib.sha256(raw).hexdigest(), 1, canonical(old),
             canonical([{"id": "1", "text": "Machine Guide"}, {"id": "2", "text": "Memory"}]), time.time()),
        )
    scopes = KnowledgeScopes(store)
    scopes.create_tag("machines", "Machines")
    scopes.assign("source", "source_old", ["machines"])
    knowledge = Knowledge(store)  # The first use reads it again from the kept original.
    source = knowledge.source("source_old", "controller")
    assert source["extraction"]["status"] == "text_extracted" and source["extraction"]["format"] == 2
    assert [s["title"] for s in source["sections"]][:2] == ["Machine Guide", "Memory"]
    assert scopes.tags("source", "source_old") == ["machines"] and source["external_allowed"] == 1
    # Adding the same file again replaces that copy instead of adding a second one.
    assert knowledge.ingest(path, True)["id"] == "source_old"
    word(path, extra_heading="Toolbox")
    assert knowledge.ingest(path, True)["id"] == "source_old"
    assert store.one("SELECT COUNT(*) AS n FROM sources")["n"] == 1


def test_turning_off_reading_applies_at_once_even_when_the_folder_is_gone(store, tmp_path):
    import shutil

    root = collection(tmp_path)
    collections = KnowledgeCollections(store)
    entry = run(collections, collections.add({"kind": "folder", "folder": str(root), "external_allowed": True}))
    allowed = lambda: {r["external_allowed"] for r in store.rows("SELECT external_allowed FROM sources")}
    assert allowed() == {1}
    shutil.rmtree(root)  # Like an unplugged drive: importing again can't work.
    collections.settings(entry["id"], {"external_allowed": False})
    assert allowed() == {0}
    scopes = KnowledgeScopes(store)
    task = store.create_project("everything", "use all reference material")
    scopes.select(task["id"], [t["id"] for t in scopes.catalog()["tags"] if t["id"] != "unclassified"],
                  scopes.catalog()["revision"])
    assert Knowledge(store).tool(task["id"], "search_knowledge", {"query": "accumulator"})["hits"] == []
    # A failed import afterwards doesn't bring the old permission back.
    collections.start(entry["id"])
    assert run(collections, entry)["state"] == "failed" and allowed() == {0}
    assert store.rows("SELECT 1 FROM events WHERE kind='knowledge_collection_permission'")
    # An import that was already running uses the owner's latest choice for every copy.
    (root.parent / "Research").mkdir()
    (root.parent / "Research" / "page.md").write_text("# Page\n\nText.\n")
    collections.settings(entry["id"], {"external_allowed": True})
    collections.permission[entry["id"]] = False  # As settings() leaves it when turned off mid-import.
    collections.start(entry["id"])
    run(collections, entry)
    assert allowed() == {0}


def test_links_in_a_folder_are_listed_not_followed(store, tmp_path):
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    (outside / "private.txt").write_text("SECRET notes from elsewhere\n")
    (outside / "sub" / "elsewhere.md").write_text("# Elsewhere\n\nSECRET too.\n")
    root = tmp_path / "Notes"
    root.mkdir()
    (root / "readme.md").write_text("# Readme\n\nHello.\n")
    try:
        (root / "linked.txt").symlink_to(outside / "private.txt")
        (root / "linked-folder").symlink_to(outside / "sub", target_is_directory=True)
    except OSError:
        pytest.skip("This computer doesn't allow creating links")
    collections = KnowledgeCollections(store)
    entry = run(collections, collections.add({"kind": "folder", "folder": str(root), "external_allowed": True}))
    reasons = {x["path"]: x["reason"] for x in entry["report"]["skipped"]}
    assert reasons["linked.txt"].startswith("a link to another file")
    assert reasons["linked-folder/"].startswith("a link to another folder")
    assert entry["report"]["documents"] == 1
    assert Knowledge(store).search("SECRET", role="controller") == []


def test_a_folder_that_holds_has_data_skips_it(tmp_path):
    from hivemind_assembly.core.store import Store

    home = tmp_path / "home"
    store = Store(home / "HA data")
    try:
        (home / "notes.md").write_text("# Notes\n\nMine.\n")
        (home / "HA data" / "private").mkdir(parents=True, exist_ok=True)
        (home / "HA data" / "private" / "endpoint.json").write_text('{"token": "dashboard"}')
        collections = KnowledgeCollections(store)
        entry = run(collections, collections.add({"kind": "folder", "folder": str(home)}))
        reasons = {x["path"]: x["reason"] for x in entry["report"]["skipped"]}
        assert reasons["HA data/"] == "HA's own data"
        assert entry["report"]["documents"] == 1
    finally:
        store.close()


def test_a_different_file_with_an_older_documents_name_is_added_beside_it(store, tmp_path):
    import time

    from hivemind_assembly.core.common import canonical

    with store.tx() as db:
        db.execute(
            "INSERT INTO sources VALUES(?,?,?,?,?,?,?)",
            ("source_notes", "notes.md", "0" * 64, 0, canonical({"status": "text_extracted", "gaps": []}),
             canonical([{"id": "1", "text": "Project A notes"}]), time.time()),
        )
    knowledge = Knowledge(store)
    (tmp_path / "projB").mkdir()
    (tmp_path / "projB" / "notes.md").write_text("# Project B\n\nDifferent notes.\n")
    result = knowledge.ingest(tmp_path / "projB" / "notes.md", True)
    assert result["id"] != "source_notes" and result["older_copy"] == "source_notes"
    assert store.one("SELECT COUNT(*) AS n FROM sources")["n"] == 2
    assert "source_notes" in {h["source"] for h in knowledge.search("Project A notes", role="controller")}


def test_update_keeps_the_owners_category_changes(store, tmp_path):
    root = collection(tmp_path)
    collections = KnowledgeCollections(store)
    entry = run(collections, collections.add({"kind": "folder", "folder": str(root), "external_allowed": True}))
    scopes = KnowledgeScopes(store)
    notes = Knowledge(store).origin_source({"kind": "collection", "collection": entry["id"], "path": "notes/registers.md"})
    assert scopes.tags("source", notes) == ["arithmetic", "audio-formats", "research"]
    scopes.assign("source", notes, ["research"])  # The owner narrows it.
    collections.start(entry["id"])
    entry = run(collections, entry)
    assert scopes.tags("source", notes) == ["research"] and entry["report"]["updated"] == 0
    (root / "notes" / "registers.md").write_text("---\ntags: [arithmetic]\n---\n# Accumulator\n\nChanged.\n")
    collections.start(entry["id"])
    entry = run(collections, entry)
    assert entry["report"]["updated"] == 1 and scopes.tags("source", notes) == ["research"]


def test_missing_pictures_never_block_and_picture_links_resolve(store, tmp_path):
    root = tmp_path / "Docs"
    (root / "docs" / "img").mkdir(parents=True)
    (root / "docs" / "img" / "My Pic.png").write_bytes(PNG)
    (root / "docs" / "img" / "top.png").write_bytes(PNG + b"t")
    (root / "docs" / "page.md").write_text(
        "# Page\n\n![spaced](img/My%20Pic.png) ![from the top](/docs/img/top.png) ![gone](img/missing.png)\n"
    )
    collections = KnowledgeCollections(store)
    entry = run(collections, collections.add({"kind": "folder", "folder": str(root), "external_allowed": True}))
    knowledge = Knowledge(store)
    key = knowledge.origin_source({"kind": "collection", "collection": entry["id"], "path": "docs/page.md"})
    source = knowledge.source(key, "controller")
    assert source["extraction"]["status"] == "text_extracted" and source["extraction"]["gaps"] == []
    pictures = source["extraction"]["pictures"]
    assert [bool(p["artifact"]) for p in pictures] == [True, True, False] and pictures[2]["missing"]
    assert not any(x["path"].startswith("docs/img/") for x in entry["report"]["skipped"])
    read = knowledge.reading(
        [{"source": key, "revision": source["revision"], "section": source["sections"][0]["id"]}], role="controller"
    )
    assert read["critical_gaps"] == [] and read["records"]


def test_word_file_with_a_picture_in_a_footnote(store, tmp_path):
    plain = word(tmp_path / "plain.docx")
    path = tmp_path / "noted.docx"
    with zipfile.ZipFile(plain) as source, zipfile.ZipFile(path, "w") as z:
        for item in source.namelist():
            data = source.read(item)
            if item == "word/document.xml":
                data = data.replace(
                    b"The accumulator holds arithmetic results.</w:t></w:r>",
                    b'The accumulator holds arithmetic results.</w:t></w:r><w:r><w:footnoteReference w:id="1"/></w:r>',
                )
            z.writestr(item, data)
        z.writestr("word/footnotes.xml", f'<w:footnotes {W}><w:footnote w:id="1"><w:p><w:r><w:t>See the figure.</w:t></w:r>'
                   + drawing("rId1", "Footnote figure") + "</w:p></w:footnote></w:footnotes>")
        z.writestr("word/_rels/footnotes.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                   'Target="media/image3.png"/></Relationships>')
        z.writestr("word/media/image3.png", PNG + b"3")
    result = Knowledge(store).ingest(path, True)
    assert result["status"] == "text_extracted"
    stored = [p for p in result["pictures"] if p["description"] == "Footnote figure"]
    assert len(stored) == 1 and stored[0]["artifact"]


def test_imported_files_are_not_left_open(store, tmp_path):
    """On Windows a file HA keeps open can't be edited, moved or deleted."""
    import os
    from pathlib import Path

    fds = Path("/proc/self/fd")
    if not fds.is_dir():
        pytest.skip("Listing open files needs /proc; the Windows run shows it by deleting the folder")
    path = word(tmp_path / "guide.docx")
    Knowledge(store).ingest(path, True)
    still_open = set()
    for fd in fds.iterdir():
        try:
            still_open.add(os.readlink(fd))
        except OSError:
            pass
    assert str(path.resolve()) not in still_open
