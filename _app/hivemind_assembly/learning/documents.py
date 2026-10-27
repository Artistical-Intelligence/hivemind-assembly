"""Read reference documents into named sections for search and the assistants' tools.

Word files are split at their headings (Heading 1, 2 and 3) into sections. Tables
become Markdown tables in the section text. Pictures become separate image files
linked to their section, with any caption or alt text; a picture never makes a
document "partly read". Links are recorded per section: outside links by address,
links inside the document by the section they point to. Markdown is split at its
headings too, with front matter (title, tags, other names) and its pictures. PDF
pages, plain text and source files become sections of their own kind.

Nothing here runs code or opens links; it only reads the file's bytes.
"""

from __future__ import annotations

import html
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from posixpath import normpath

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
V = "urn:schemas-microsoft-com:vml"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
PACKAGE_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
CODE_LINES = 200  # Source files: one section per 200 lines.
VIEWABLE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MARKDOWN = {".md", ".markdown", ".mdx"}
HTML = {".html", ".htm", ".xhtml"}


def q(ns, tag):
    return "{%s}%s" % (ns, tag)


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


@dataclass
class Parsed:
    title: str
    sections: list = field(default_factory=list)
    pictures: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    names: list = field(default_factory=list)
    tags: list | None = None
    tables: int = 0


class Builder:
    """Collects sections in document order; a heading of level 1–3 starts a new one."""

    def __init__(self, title):
        self.title = title
        self.sections = []
        self.path = []
        self.current = None
        self.anchors = {}

    def start(self, heading, level):
        level = max(1, min(3, level))
        self.path = self.path[: level - 1] + [heading]
        self.current = {
            "id": str(len(self.sections) + 1),
            "title": heading,
            "level": level,
            "path": list(self.path),
            "lines": ["#" * level + " " + heading] if heading else [],
            "links": [],
            "pictures": [],
        }
        self.sections.append(self.current)
        return self.current

    def section(self):
        if self.current is None:
            # Text before the first heading: the document's opening section.
            self.current = {
                "id": "1", "title": self.title, "level": 0, "path": [], "lines": [], "links": [], "pictures": [],
            }
            self.sections.append(self.current)
        return self.current

    def add(self, text):
        self.section()["lines"].append(text)

    def finish(self):
        result = []
        for s in self.sections:
            text = "\n\n".join(line for line in s.pop("lines") if line is not None).strip()
            s["text"] = re.sub(r"\n{3,}", "\n\n", text)
            result.append(s)
        return result


# ------------------------------------------------------------------ Word
class Word:
    def __init__(self, path):
        self.path = Path(path)
        self.zip = zipfile.ZipFile(self.path)
        self.names = set(self.zip.namelist())
        self.styles = self._styles()
        self.rels = self._rels("word/_rels/document.xml.rels")
        self.footnotes = self._notes("word/footnotes.xml", "footnote")
        self.pictures = []
        self.tables = 0
        self.gaps = []
        self.notes_used = []

    def _xml(self, name):
        return ET.fromstring(self.zip.read(name)) if name in self.names else None

    def _styles(self):
        root = self._xml("word/styles.xml")
        styles = {}
        if root is None:
            return styles
        for style in root.iter(q(W, "style")):
            sid = style.get(q(W, "styleId"))
            name = style.find(q(W, "name"))
            based = style.find(q(W, "basedOn"))
            outline = style.find(".//" + q(W, "outlineLvl"))
            styles[sid] = {
                "name": (name.get(q(W, "val")) if name is not None else sid or "").lower(),
                "based": based.get(q(W, "val")) if based is not None else None,
                "outline": int(outline.get(q(W, "val"))) if outline is not None and outline.get(q(W, "val"), "").isdigit() else None,
            }
        return styles

    def _rels(self, name):
        root = self._xml(name)
        rels = {}
        if root is None:
            return rels
        for rel in root.iter(q(PACKAGE_RELS, "Relationship")):
            rels[rel.get("Id")] = {
                "type": rel.get("Type", "").rsplit("/", 1)[-1],
                "target": rel.get("Target", ""),
                "external": rel.get("TargetMode") == "External",
            }
        return rels

    def _notes(self, name, tag):
        root = self._xml(name)
        notes = {}
        if root is None:
            return notes
        for note in root.iter(q(W, tag)):
            key = note.get(q(W, "id"))
            text = " ".join(self.text(p)[0] for p in note.iter(q(W, "p"))).strip()
            if key and text:
                notes[key] = text
        return notes

    def style(self, paragraph):
        props = paragraph.find(q(W, "pPr"))
        sid = None
        own_outline = None
        list_level = None
        if props is not None:
            ps = props.find(q(W, "pStyle"))
            sid = ps.get(q(W, "val")) if ps is not None else None
            ol = props.find(q(W, "outlineLvl"))
            if ol is not None and ol.get(q(W, "val"), "").isdigit():
                own_outline = int(ol.get(q(W, "val")))
            num = props.find(q(W, "numPr"))
            if num is not None:
                ilvl = num.find(q(W, "ilvl"))
                list_level = int(ilvl.get(q(W, "val"))) if ilvl is not None and ilvl.get(q(W, "val"), "").isdigit() else 0
        name, outline, seen = "", None, set()
        current = sid
        while current and current not in seen and current in self.styles:
            seen.add(current)
            info = self.styles[current]
            name = name or info["name"]
            if outline is None:
                outline = info["outline"]
            current = info["based"]
        if own_outline is not None:
            outline = own_outline
        heading = None
        match = re.fullmatch(r"heading\s*(\d)", name or "")
        if match:
            heading = int(match.group(1))
        elif outline is not None and outline < 9:
            heading = outline + 1
        return {"name": name or (sid or "").lower(), "heading": heading, "list": list_level}

    def text(self, paragraph, sink=None):
        """A paragraph's text, with its links and pictures."""
        out, links = [], []

        def walk(node):
            for child in node:
                tag = local(child.tag)
                if tag in ("del", "moveFrom", "instrText", "delText", "rPr", "pPr"):
                    continue
                if tag == "AlternateContent":
                    choice = child.find(q(MC, "Choice"))
                    walk(choice if choice is not None else child)
                elif tag == "hyperlink":
                    start = len(out)
                    walk(child)
                    shown = "".join(out[start:]).strip()
                    rid, anchor = child.get(q(R, "id")), child.get(q(W, "anchor"))
                    rel = self.rels.get(rid) if rid else None
                    if rel and rel["external"]:
                        links.append({"kind": "external", "text": shown, "url": rel["target"] + (("#" + anchor) if anchor else "")})
                    elif anchor:
                        links.append({"kind": "internal", "text": shown, "anchor": anchor})
                elif tag == "t":
                    out.append(child.text or "")
                elif tag == "tab":
                    out.append("\t")
                elif tag in ("br", "cr"):
                    out.append("\n")
                elif tag == "noBreakHyphen":
                    out.append("-")
                elif tag == "footnoteReference":
                    key = child.get(q(W, "id"))
                    if key in self.footnotes:
                        out.append(f"[^{key}]")
                        self.notes_used.append(key)
                elif tag == "bookmarkStart" and sink is not None:
                    sink.setdefault("anchors", []).append(child.get(q(W, "name")))
                elif tag in ("drawing", "pict"):
                    for picture in self.picture(child):
                        out.append(f"[Picture {picture['id']}]")
                        if sink is not None:
                            sink.setdefault("pictures", []).append(picture)
                else:
                    walk(child)

        walk(paragraph)
        return "".join(out), links

    def picture(self, node):
        """The image(s) inside one drawing or VML picture, with their alt text."""
        found = []
        docpr = node.find(".//" + q(WP, "docPr"))
        alt = ""
        if docpr is not None:
            alt = (docpr.get("descr") or docpr.get("title") or "").strip()
        rids = [b.get(q(R, "embed")) or b.get(q(R, "link")) for b in node.iter(q(A, "blip"))]
        for imagedata in node.iter(q(V, "imagedata")):
            rids.append(imagedata.get(q(R, "id")))
            alt = alt or (imagedata.get(q("urn:schemas-microsoft-com:office:office", "title")) or "").strip()
        for shape in node.iter(q(V, "shape")):
            alt = alt or (shape.get("alt") or "").strip()
        for rid in rids:
            rel = self.rels.get(rid)
            if not rel:
                continue
            number = len(self.pictures) + 1
            picture = {"id": f"p{number}", "alt": alt, "caption": "", "external": rel["external"]}
            if rel["external"]:
                picture.update(name=rel["target"], data=None, suffix="")
            else:
                target = normpath("word/" + rel["target"]) if not rel["target"].startswith("/") else rel["target"].lstrip("/")
                suffix = PurePosixPath(target).suffix.lower()
                data = self.zip.read(target) if target in self.names else None
                picture.update(name=f"{self.path.stem}-picture-{number}{suffix}", data=data, suffix=suffix)
                if data is None:
                    self.gaps.append(f"Picture {picture['id']} is missing from the file.")
            self.pictures.append(picture)
            found.append(picture)
        return found

    def table(self, table):
        rows = []
        for tr in table.findall(q(W, "tr")):
            cells = []
            for tc in tr.findall(q(W, "tc")):
                parts = []
                for p in tc.iter(q(W, "p")):
                    text, links = self.text(p, self.sink)
                    self.sink.setdefault("links", []).extend(links)
                    if text.strip():
                        parts.append(text.strip())
                cell = "<br>".join(parts).replace("|", "\\|").replace("\n", "<br>")
                span = tc.find(q(W, "tcPr") + "/" + q(W, "gridSpan"))
                cells.append(cell)
                if span is not None and span.get(q(W, "val"), "1").isdigit():
                    cells.extend([""] * (int(span.get(q(W, "val"))) - 1))
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        self.tables += 1
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join([" --- "] * width) + "|"]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)

    def parse(self):
        root = self._xml("word/document.xml")
        if root is None:
            raise ValueError("this isn't a Word document (no word/document.xml)")
        title = ""
        core = self._xml("docProps/core.xml")
        if core is not None:
            node = core.find("{http://purl.org/dc/elements/1.1/}title")
            title = (node.text or "").strip() if node is not None else ""
        build = Builder(title or self.path.stem.replace("_", " "))
        body = root.find(q(W, "body"))
        if body is None:
            body = root  # A bare document without a body element.
        code = []
        last_pictures = []

        def flush_code():
            if code:
                build.add("```\n" + "\n".join(code) + "\n```")
                code.clear()

        def place(sink, section):
            for anchor in sink.get("anchors", []):
                build.anchors.setdefault(anchor, section["id"])
            for picture in sink.get("pictures", []):
                picture["section"] = section["id"]
                section["pictures"].append(picture["id"])

        def visit(element):
            nonlocal title, last_pictures
            for child in element:
                tag = local(child.tag)
                if tag == "sdt":
                    content = child.find(q(W, "sdtContent"))
                    if content is not None:
                        visit(content)
                    continue
                if tag == "tbl":
                    flush_code()
                    self.sink = {}
                    markdown = self.table(child)
                    section = build.section()
                    place(self.sink, section)
                    section["links"].extend(self.sink.get("links", []))
                    if markdown:
                        build.add(markdown)
                    continue
                if tag != "p":
                    continue
                style = self.style(child)
                sink = {}
                text, links = self.text(child, sink)
                clean = text.strip()
                name = style["name"]
                if name == "title" and clean and not title:
                    title = clean
                    build.title = clean
                if style["heading"] in (1, 2, 3) and clean:
                    flush_code()
                    section = build.start(re.sub(r"\s+", " ", clean), style["heading"])
                    place(sink, section)
                    section["links"].extend(links)
                    last_pictures = []
                    continue
                section = build.section()
                place(sink, section)
                section["links"].extend(links)
                if re.search(r"code|source|preformatted|plain text|listing", name):
                    code.append(text.rstrip())
                    continue
                flush_code()
                if not clean:
                    continue
                if name == "caption" and last_pictures:
                    for picture in last_pictures:
                        picture["caption"] = picture["caption"] or clean
                    build.add("*" + clean + "*")
                    last_pictures = []
                    continue
                # A caption belongs to the pictures in the paragraph just before it.
                last_pictures = list(sink.get("pictures", []))
                if style["heading"]:
                    build.add("#" * min(6, style["heading"]) + " " + clean)
                elif style["list"] is not None or name.startswith("list"):
                    marker = "1." if "number" in name else "-"
                    build.add("  " * (style["list"] or 0) + marker + " " + clean)
                else:
                    build.add(text.strip("\n"))

        self.sink = {}
        visit(body)
        flush_code()
        sections = build.finish()
        for key in dict.fromkeys(self.notes_used):
            # Footnotes go at the end of the section that refers to them.
            for s in sections:
                if f"[^{key}]" in s["text"]:
                    s["text"] += f"\n\n[^{key}]: {self.footnotes[key]}"
                    break
        for s in sections:
            for link in s["links"]:
                if link.get("kind") == "internal":
                    target = build.anchors.get(link.pop("anchor"))
                    if target:
                        link["section"] = target
                    else:
                        link["kind"] = "missing"
            s["links"] = [l for l in s["links"] if l.get("kind") != "missing"]
        return Parsed(build.title, sections, self.pictures, self.gaps, tables=self.tables)


def parse_docx(path):
    with zipfile.ZipFile(path):
        pass  # A clear error for a file that isn't a ZIP package.
    return Word(path).parse()


# -------------------------------------------------------------- Markdown
FRONT = re.compile(r"\A---\s*\n(.*?)\n(?:---|\.\.\.)\s*(?:\n|\Z)", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LINK = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def front_matter(text):
    """YAML front matter: (fields, rest of the text)."""
    match = FRONT.match(text)
    if not match:
        return {}, text
    try:
        import yaml

        data = yaml.safe_load(match.group(1))
    except Exception:
        data = None
    return (data if isinstance(data, dict) else {}), text[match.end():]


def as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,;]", value) if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def parse_markdown(text, name, image=None):
    """Sections at headings 1–3; links and pictures per section. `image(target)`
    returns (bytes, file name) for a picture inside the same collection."""
    fields, body = front_matter(text)
    title = str(fields.get("title") or "").strip()
    stem = PurePosixPath(name).stem
    build = Builder(title or stem)
    names = []
    for key in ("aliases", "alias", "names", "other_names", "also_known_as", "aka"):
        names += as_list(fields.get(key))
    tags = None
    for key in ("tags", "tag", "categories", "category"):
        if key in fields:
            tags = (tags or []) + as_list(fields[key])
    pictures = []
    fenced, paragraph = False, []

    def flush():
        if paragraph:
            build.add("\n".join(paragraph))
            paragraph.clear()

    for line in body.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            paragraph.append(line)
            if not fenced:
                flush()
            continue
        heading = None if fenced else HEADING.match(line)
        if heading and len(heading.group(1)) <= 3:
            flush()
            build.start(heading.group(2).strip(), len(heading.group(1)))
            continue
        if not fenced and not line.strip():
            flush()
            continue
        paragraph.append(line)
        section = build.section()
        if fenced:
            continue
        for bang, shown, target in LINK.findall(line):
            if bang:
                number = len(pictures) + 1
                picture = {"id": f"p{number}", "alt": shown.strip(), "caption": "", "section": section["id"],
                           "external": bool(re.match(r"[a-z][a-z0-9+.-]*:", target, re.I))}
                if picture["external"]:
                    picture.update(name=target, data=None, suffix="")
                else:
                    found = image(target) if image else None
                    data, file_name = found if found else (None, PurePosixPath(target).name)
                    picture.update(name=file_name, data=data, suffix=PurePosixPath(file_name).suffix.lower())
                    picture["missing"] = data is None
                pictures.append(picture)
                section["pictures"].append(picture["id"])
            elif re.match(r"[a-z][a-z0-9+.-]*:", target, re.I):
                section["links"].append({"kind": "external", "text": shown, "url": target})
            else:
                section["links"].append({"kind": "file", "text": shown, "target": target})
    flush()
    sections = build.finish()
    gaps = [f"Picture {p['id']} ({p['name']}) isn't in the imported folder." for p in pictures if p.get("missing")]
    for p in pictures:
        p.pop("missing", None)
    if all(s["level"] == 0 for s in sections) and len(sections) == 1:
        # No headings: one section per paragraph, as plain text.
        plain = parse_text(body, name)
        for p in pictures:
            p["section"] = "1"
        plain.sections[0]["pictures"] = [p["id"] for p in pictures]
        plain.sections[0]["links"] = sections[0]["links"]
        sections = plain.sections
    return Parsed(build.title, sections, pictures, gaps, names, tags)


# -------------------------------------------------------- HTML, text, code
class _Html(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "li", "tr", "br", "pre", "blockquote", "table", "ul", "ol", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.current, self.skip, self.heading = [], [], 0, None
        self.href, self.title = None, ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif re.fullmatch(r"h[1-6]", tag):
            self.end_line()
            self.heading = int(tag[1])
        elif tag == "a" and attrs.get("href"):
            self.href = attrs["href"]
            self.current.append("[")
        elif tag == "img":
            alt = attrs.get("alt") or ""
            self.current.append(f"![{alt}]({attrs.get('src', '')})")
        elif tag in self.BLOCK:
            self.end_line()
            if tag == "li":
                self.current.append("- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif re.fullmatch(r"h[1-6]", tag):
            self.end_line()
        elif tag == "a" and self.href is not None:
            self.current.append(f"]({self.href})")
            self.href = None
        elif tag in self.BLOCK:
            self.end_line()

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title += data
            return
        self.current.append(re.sub(r"\s+", " ", data))

    def end_line(self):
        text = "".join(self.current).strip()
        self.current = []
        if text:
            if self.heading:
                text = "#" * self.heading + " " + text
            self.lines.append(text)
            self.lines.append("")
        self.heading = None


def html_to_markdown(raw):
    parser = _Html()
    parser.feed(raw)
    parser.close()
    parser.end_line()
    return parser.title.strip(), "\n".join(parser.lines)


def parse_text(text, name):
    """Plain text: one section per paragraph."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    stem = PurePosixPath(name).name
    sections = [
        {"id": str(i + 1), "title": stem if i == 0 else f"{stem} (part {i + 1})", "level": 0, "path": [],
         "text": part, "links": [], "pictures": []}
        for i, part in enumerate(p for p in text.split("\n\n") if p.strip())
    ]
    return Parsed(PurePosixPath(name).stem, sections)


def parse_code(text, name):
    """Source and data files: one section per 200 lines, titled by its lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    file_name = PurePosixPath(name).name
    sections = []
    for start in range(0, max(1, len(lines)), CODE_LINES):
        chunk = "\n".join(lines[start:start + CODE_LINES])
        if not chunk.strip():
            continue
        end = min(len(lines), start + CODE_LINES)
        sections.append({
            "id": str(len(sections) + 1),
            "title": f"{file_name}, lines {start + 1}–{end}" if len(lines) > CODE_LINES else file_name,
            "level": 0, "path": [], "text": chunk, "links": [], "pictures": [],
        })
    return Parsed(file_name, sections)


def parse_pdf(path):
    gaps = []
    sections = []
    try:
        import pypdf
    except ImportError:
        return Parsed(Path(path).stem, [], [], ["PDF text extraction isn't installed."])
    import logging

    # Font and encoding notes from odd PDFs aren't problems with the import.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = pypdf.PdfReader(str(path))
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        sections.append({"id": str(i + 1), "title": f"{Path(path).stem}, page {i + 1}", "level": 0, "path": [],
                         "text": text, "links": [], "pictures": []})
        if not text.strip():
            gaps.append(f"Page {i + 1} has no text (a scan or picture); it needs reading by eye.")
    return Parsed(Path(path).stem, sections, [], gaps)


def decode(raw):
    """Text in UTF-8 (with or without a byte order mark) or UTF-16; None otherwise."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\0" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def parse(path, kind, image=None, display=None):
    """Read one file of the given kind: word, markdown, html, pdf, text or code."""
    path = Path(path)
    name = display or path.name
    if kind == "word":
        return parse_docx(path)
    if kind == "pdf":
        return parse_pdf(path)
    text = decode(path.read_bytes())
    if text is None:
        raise ValueError("it isn't UTF-8 or UTF-16 text")
    if kind == "markdown":
        return parse_markdown(text.replace("\r\n", "\n").replace("\r", "\n"), name, image)
    if kind == "html":
        title, markdown = html_to_markdown(text)
        parsed = parse_markdown(markdown, name, image)
        parsed.title = html.unescape(title) or parsed.title
        return parsed
    if kind == "code":
        return parse_code(text, name)
    return parse_text(text, name)


def summary(parsed):
    """Counts shown on the dashboard."""
    return {
        "sections": len(parsed.sections),
        "tables": parsed.tables,
        "pictures": len(parsed.pictures),
        "pictures_not_described": sum(1 for p in parsed.pictures if not (p.get("caption") or p.get("alt"))),
        "links": sum(len(s["links"]) for s in parsed.sections),
    }


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
