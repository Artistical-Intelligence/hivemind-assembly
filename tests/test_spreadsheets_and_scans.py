"""Reference material from Excel workbooks (sheets become Markdown tables) and from
scanned PDF pages (read with Tesseract when it's installed; otherwise a gap says how
to add it, and the next update reads them)."""

import shutil
import zipfile

import pytest

from hivemind_assembly.learning import documents
from hivemind_assembly.learning.collections import KnowledgeCollections
from hivemind_assembly.learning.knowledge import Knowledge

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def workbook(path, sheets, macros=False):
    """sheets: {name: [[cell, ...], ...]}; strings are shared, numbers are values."""
    shared, xml_sheets, rels, listed = [], {}, [], []
    for n, (name, rows) in enumerate(sheets.items(), 1):
        out = []
        for r, row in enumerate(rows, 1):
            cells = []
            for c, value in enumerate(row):
                ref = f"{chr(65 + c)}{r}"
                if value is None:
                    continue
                if isinstance(value, bool):
                    cells.append(f'<c r="{ref}" t="b"><v>{int(value)}</v></c>')
                elif isinstance(value, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                else:
                    shared.append(value)
                    cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
            out.append(f'<row r="{r}">{"".join(cells)}</row>')
        xml_sheets[f"xl/worksheets/sheet{n}.xml"] = f'<worksheet xmlns="{X}"><sheetData>{"".join(out)}</sheetData></worksheet>'
        rels.append(f'<Relationship Id="rId{n}" Type="{REL}/worksheet" Target="worksheets/sheet{n}.xml"/>')
        listed.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{X}" xmlns:r="{REL}"><sheets>{"".join(listed)}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(rels) + "</Relationships>")
        z.writestr("xl/sharedStrings.xml",
                   f'<sst xmlns="{X}">' + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        for name, data in xml_sheets.items():
            z.writestr(name, data)
        if macros:
            z.writestr("xl/vbaProject.bin", b"not run")
    return path


def test_sheets_become_searchable_tables(store, tmp_path):
    book = workbook(tmp_path / "opcodes.xlsx", {
        "Opcodes": [["Opcode", "Mnemonic", "Cycles", "Official"], [0x90, "NOP", 2, True], [0xEA, "NOP|ALT", None, False]],
        "Empty": [],
        "Long": [["Address", "Symbol"]] + [[n, f"sym_{n}"] for n in range(450)],
    })
    knowledge = Knowledge(store)
    added = knowledge.ingest(book, True)
    source = knowledge.source(added["id"], "controller")
    titles = [s["title"] for s in source["sections"]]
    assert titles == ["Opcodes", "Long, rows 2–201", "Long, rows 202–401", "Long, rows 402–451"]
    first = source["sections"][0]["text"]
    assert "| Opcode | Mnemonic | Cycles | Official |" in first
    assert "| 144 | NOP | 2 | TRUE |" in first and "| 234 | NOP\\|ALT |  | FALSE |" in first
    assert source["sections"][2]["text"].splitlines()[2] == "| Address | Symbol |"  # Every part keeps the heading row.
    assert source["extraction"]["counts"]["tables"] == 2 and source["extraction"]["status"] == "text_extracted"
    assert knowledge.search("sym_420", role="controller")[0]["title"] == "Long, rows 402–451"


def test_macro_workbooks_are_read_without_their_macros(store, tmp_path):
    book = workbook(tmp_path / "tools.xlsm", {"Sheet1": [["Tool", "Use"], ["Ghidra", "Disassembly"]]}, macros=True)
    added = Knowledge(store).ingest(book, True)
    assert added["gaps"] == ["The workbook's macros weren't read."]


def test_folders_import_workbooks_and_point_old_ones_to_xlsx(store, tmp_path):
    root = tmp_path / "Research"
    root.mkdir()
    workbook(root / "map.xlsx", {"Memory": [["Start", "Use"], ["0x8000", "ROM"]]})
    (root / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0old")
    (root / "deck.pptx").write_bytes(b"PK")
    collections = KnowledgeCollections(store)
    entry = collections.add({"kind": "folder", "folder": str(root), "external_allowed": True})
    collections.running[entry["id"]].join(120)
    entry = collections._load()[entry["id"]]
    assert entry["report"]["imported"] == 1, entry
    reasons = {x["path"]: x["reason"] for x in entry["report"]["skipped"]}
    assert reasons["old.xls"] == "old Excel format; save it as .xlsx to import it"
    assert reasons["deck.pptx"].startswith("slides and other office formats aren't imported")


def scanned_pdf(path, words):
    from PIL import Image, ImageDraw, ImageFont

    picture = Image.new("L", (1700, 400), 255)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 48)
    except OSError:
        font = ImageFont.load_default(size=48)
    ImageDraw.Draw(picture).text((60, 120), words, fill=0, font=font)
    picture.save(path, resolution=150)
    return path


def test_scanned_pages_say_how_to_read_them_and_are_read_once_tesseract_is_there(store, tmp_path, monkeypatch):
    scan = scanned_pdf(tmp_path / "manual.pdf", "Relocation entries patch pointers")
    knowledge = Knowledge(store)
    monkeypatch.setattr(documents, "tesseract", lambda: None)
    first = knowledge.ingest(scan, True)
    assert "Select Install required tools in Settings to add Tesseract" in first["gaps"][0]
    assert knowledge.search("relocation", role="controller") == []
    assert knowledge.ingest(scan, True).get("unchanged")  # Nothing new to read yet.

    monkeypatch.setattr(documents, "tesseract", lambda: "/installed/tesseract")
    monkeypatch.setattr(documents, "ocr", lambda program, picture: "Relocation entries patch pointers")
    again = knowledge.ingest(scan, True)
    assert not again.get("unchanged") and again["gaps"] == []
    hit = knowledge.search("relocation", role="controller")[0]
    assert hit["title"] == "manual, page 1 (scanned)"
    assert knowledge.source(again["id"], "controller")["extraction"]["counts"]["scanned_pages"] == 1


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract isn't installed")
def test_tesseract_reads_a_real_scan(tmp_path):
    parsed = documents.parse(scanned_pdf(tmp_path / "scan.pdf", "Relocation entries patch pointers"), "pdf")
    assert "Relocation entries patch pointers" in parsed.sections[0]["text"]
    assert parsed.scanned == 1 and parsed.gaps == []
