"""OOXML checks and ordered body extraction, without Office or external fetches."""

import io
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from backend.app.core.document_limits import DocumentError
from backend.app.services.contract_text import table_text


def preflight_docx(stream, budget):
    total, main = 0, False
    try:
        with ZipFile(stream) as archive:
            entries = archive.infolist()
            if len(entries) > 2000:
                raise DocumentError("DOCUMENT_LIMIT_EXCEEDED")
            names = [item.filename for item in entries]
            if len(set(names)) != len(names) or not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= set(names):
                raise DocumentError("UNSAFE_DOCUMENT")
            for item in entries:
                budget.check()
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename or "vbaproject" in item.filename.lower():
                    raise DocumentError("UNSAFE_DOCUMENT")
                if item.flag_bits & 1:
                    raise DocumentError("ENCRYPTED_DOCUMENT")
                xml = item.filename.endswith((".xml", ".rels"))
                if item.file_size > 50 * 1024 * 1024 or (xml and item.file_size > 10 * 1024 * 1024):
                    raise DocumentError("DOCUMENT_LIMIT_EXCEEDED")
                if item.file_size > max(1, item.compress_size) * 1000:
                    raise DocumentError("UNSAFE_DOCUMENT")
                chunks, size = [], 0
                with archive.open(item) as member:
                    while chunk := member.read(65536):
                        budget.check()
                        total += len(chunk)
                        size += len(chunk)
                        if total > 50 * 1024 * 1024 or (xml and size > 10 * 1024 * 1024):
                            raise DocumentError("DOCUMENT_LIMIT_EXCEEDED")
                        if xml:
                            chunks.append(chunk)
                if not xml:
                    continue
                data = b"".join(chunks)
                depth, nodes = 0, 0
                context = etree.iterparse(io.BytesIO(data), events=("start", "end"),
                                          resolve_entities=False, no_network=True, load_dtd=False)
                for event, element in context:
                    if event == "start":
                        depth += 1
                        nodes += 1
                        if depth > 64 or nodes > 100000:
                            raise DocumentError("DOCUMENT_LIMIT_EXCEEDED")
                    else:
                        depth -= 1
                root = context.root
                if root.getroottree().docinfo.doctype:
                    raise DocumentError("UNSAFE_DOCUMENT")
                if item.filename == "[Content_Types].xml":
                    main = any(e.get("PartName") == "/word/document.xml" and e.get("ContentType") ==
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" for e in root)
                if item.filename == "word/document.xml":
                    unsupported = {qn("w:ins"), qn("w:del"), qn("w:moveFrom"), qn("w:moveTo"),
                                   qn("w:txbxContent"), qn("w:altChunk"), qn("w:object"),
                                   qn("w:sdt"), qn("w:fldSimple"), qn("w:sym"), qn("m:oMath")}
                    if any(e.tag in unsupported for e in root.iter()):
                        raise DocumentError("INCOMPLETE_EXTRACTION")
                if item.filename in {"word/footnotes.xml", "word/endnotes.xml"}:
                    if any((e.text or "").strip() for e in root.iter(qn("w:t"))):
                        raise DocumentError("INCOMPLETE_EXTRACTION")
            if not main:
                raise DocumentError("FILE_TYPE_MISMATCH", status=415)
    except (BadZipFile, etree.XMLSyntaxError, KeyError, EOFError, ValueError):
        raise DocumentError("CORRUPTED_DOCUMENT") from None
    finally:
        stream.seek(0)


class Numbering:
    def __init__(self, doc):
        try:
            self.root = doc.part.numbering_part.element
        except (KeyError, NotImplementedError):
            self.root = None
        self.counters = {}

    def prefix(self, paragraph):
        props = paragraph._p.pPr
        num = props.numPr if props is not None else None
        if num is None and paragraph.style is not None:
            props = paragraph.style.element.pPr
            num = props.numPr if props is not None else None
        if num is None or num.numId is None or num.numId.val == 0:
            return ""
        if self.root is None:
            raise DocumentError("INCOMPLETE_EXTRACTION")
        num_id, level = num.numId.val, num.ilvl.val if num.ilvl is not None else 0
        definitions = self.root.xpath(f'./w:num[@w:numId="{num_id}"]')
        if not definitions:
            raise DocumentError("INCOMPLETE_EXTRACTION")
        abstract = definitions[0].find(qn("w:abstractNumId")).get(qn("w:val"))
        levels = self.root.xpath(f'./w:abstractNum[@w:abstractNumId="{abstract}"]/w:lvl[@w:ilvl="{level}"]')
        if not levels:
            raise DocumentError("INCOMPLETE_EXTRACTION")
        definition = levels[0]
        overrides = definitions[0].xpath(f'./w:lvlOverride[@w:ilvl="{level}"]')
        if overrides and overrides[0].find(qn("w:lvl")) is not None:
            definition = overrides[0].find(qn("w:lvl"))
        def value(name, default):
            node = definition.find(qn("w:" + name))
            return node.get(qn("w:val")) if node is not None else default
        start = int(value("start", "1"))
        if overrides and overrides[0].find(qn("w:startOverride")) is not None:
            start = int(overrides[0].find(qn("w:startOverride")).get(qn("w:val")))
        key = (num_id, level)
        self.counters[key] = self.counters.get(key, start - 1) + 1
        for old in list(self.counters):
            if old[0] == num_id and old[1] > level:
                del self.counters[old]
        fmt = value("numFmt", "decimal")
        if fmt == "bullet":
            return "• "
        if fmt != "decimal":
            raise DocumentError("INCOMPLETE_EXTRACTION")
        label = value("lvlText", "%1.")
        for i in range(9):
            label = label.replace(f"%{i + 1}", str(self.counters.get((num_id, i), 1)))
        return label + " "


def parse_docx(stream, budget):
    preflight_docx(stream, budget)
    doc = Document(stream)
    budget.check()
    numbering = Numbering(doc)
    tables = 0
    def content(container, depth=0):
        nonlocal tables
        if depth > 8:
            raise DocumentError("DOCUMENT_LIMIT_EXCEEDED")
        pieces = []
        for block in container.iter_inner_content():
            budget.check()
            if isinstance(block, Paragraph):
                value = numbering.prefix(block) + block.text
                budget.check(value)
                pieces.append(value)
            elif isinstance(block, Table):
                tables += 1
                seen, rows = set(), []
                for row in block.rows:
                    budget.check(cells=len(row.cells))
                    values = [""] * row.grid_cols_before
                    for cell in row.cells:
                        if cell._tc in seen:
                            values.append("")
                        else:
                            seen.add(cell._tc)
                            values.append(content(cell, depth + 1))
                    values.extend([""] * row.grid_cols_after)
                    rows.append(values)
                pieces.append(table_text(rows))
        return "\n".join(pieces)
    text = content(doc)
    warnings = []
    if any(part.partname.startswith(("/word/header", "/word/footer")) and
           any((e.text or "").strip() for e in part.element.iter(qn("w:t")))
           for part in doc.part.related_parts.values() if hasattr(part, "element")):
        warnings.append({"code": "HEADER_FOOTER_REVIEW", "message": "页眉页脚未纳入正文，请核对其中是否有补充约定。", "pages": []})
    if doc.inline_shapes or doc.element.xpath(".//w:pict|.//w:drawing"):
        if not text.strip():
            raise DocumentError("SCANNED_DOCUMENT")
        warnings.append({"code": "IMAGE_TEXT_NOT_EXTRACTED", "message": "图片中的文字未提取，请核对图片、签名及印章。", "pages": []})
    budget.check()
    return text, None, tables, warnings
