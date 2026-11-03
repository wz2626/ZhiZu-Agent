"""Per-page text/table extraction with fail-closed mixed-scan detection."""

from collections import Counter
import logging
import re

import pdfplumber
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser

from backend.app.core.document_limits import DocumentError, MAX_PAGES
from backend.app.services.contract_text import table_text
from backend.app.services.pdf_images import image_text_signal

# pdfminer debug diagnostics can contain decoded streams/metadata. Only our
# controlled error codes are public/loggable in this privacy-sensitive service.
logging.getLogger("pdfminer").setLevel(logging.CRITICAL + 1)


def preflight_pdf(stream, budget):
    doc = PDFDocument(PDFParser(stream))
    if doc.encryption:
        raise DocumentError("ENCRYPTED_DOCUMENT")
    if doc.catalog.get("AcroForm"):
        raise DocumentError("INCOMPLETE_EXTRACTION")
    count = 0
    for _page in PDFPage.create_pages(doc):
        budget.check()
        count += 1
        if count > MAX_PAGES:
            raise DocumentError("DOCUMENT_LIMIT_EXCEEDED")
    stream.seek(0)
    if not count:
        raise DocumentError("NO_EXTRACTABLE_TEXT")
    return count


def image_coverage(images, width, height):
    # Union area, so overlapping images cannot inflate coverage.
    boxes = [(max(0, im["x0"]), max(0, im["top"]), min(width, im["x1"]), min(height, im["bottom"])) for im in images]
    xs = sorted({x for b in boxes for x in (b[0], b[2])})
    area = 0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((b[1], b[3]) for b in boxes if b[0] < right and b[2] > left and b[3] > b[1])
        end = -1
        for top, bottom in spans:
            area += (right - left) * max(0, bottom - max(top, end))
            end = max(end, bottom)
    return area / max(1, width * height)


def parse_pdf(stream, budget):
    count = preflight_pdf(stream, budget)
    pages, unreadable, scans, incomplete, image_pages, tables = [], [], [], [], [], 0
    with pdfplumber.open(stream, unicode_norm="NFC") as doc:
        for page in doc.pages:
            budget.check()
            number = page.page_number
            try:
                chars, images = page.chars, page.images
                if sum(len(v) for v in page.objects.values()) > 100000 or len(images) > 1000:
                    raise DocumentError("DOCUMENT_LIMIT_EXCEEDED")
                coverage = image_coverage(images, page.width, page.height)
                body_chars = [c for c in chars if page.height * .08 <= c["top"] <= page.height * .92 and c["text"].strip()]
                # A near-full page image is not safe just because it has a footer or a few labels.
                if images and (coverage >= .35 or (len(body_chars) < 80 and coverage >= .15)):
                    if len(body_chars) < 80:
                        # Sparse but readable text next to demonstrably graphic
                        # images is not itself a scan. Edge-only/no body text
                        # remains rejected even for a blank/uniform image.
                        graphics_only = bool(body_chars) and all(
                            not any(im["x0"] <= (c["x0"] + c["x1"]) / 2 <= im["x1"] and
                                    im["top"] <= (c["top"] + c["bottom"]) / 2 <= im["bottom"] for c in body_chars)
                            and image_text_signal(im, budget) is False for im in images)
                        if not graphics_only:
                            scans.append(number)
                    else:
                        for im in images:
                            if im["width"] * im["height"] < page.width * page.height * .35:
                                continue
                            inside = sum(im["x0"] <= (c["x0"] + c["x1"]) / 2 <= im["x1"] and
                                         im["top"] <= (c["top"] + c["bottom"]) / 2 <= im["bottom"] for c in body_chars)
                            if inside >= 80:
                                continue  # Readable OCR/text layer over the image.
                            outside_count = len(body_chars) - inside
                            signal = image_text_signal(im, budget)
                            if outside_count < 80 or signal is not False:
                                incomplete.append(number)
                                break
                if images:
                    image_pages.append(number)
                if not chars and not images and len(page.curves) > 20:
                    unreadable.append(number)
                deduped = page.dedupe_chars(tolerance=1)
                found = deduped.find_tables()
                boxes, blocks = [], []
                for table in found:
                    budget.check()
                    rows = table.extract()
                    if not rows or not any(any(cell for cell in row) for row in rows):
                        raise DocumentError("INCOMPLETE_EXTRACTION", pages=[number])
                    budget.check(cells=sum(len(row) for row in rows))
                    value = table_text(rows)
                    budget.check(value)
                    blocks.append((table.bbox[1], table.bbox[0], value, "table"))
                    boxes.append(table.bbox)
                    tables += 1
                def outside(char):
                    x, y = (char["x0"] + char["x1"]) / 2, (char["top"] + char["bottom"]) / 2
                    return not any(a <= x <= c and b <= y <= d for a, b, c, d in boxes)
                lines = deduped.filter(outside).extract_text_lines(layout=False, strip=True, return_chars=True)
                split_lines = 0
                for line in lines:
                    positions = sorted((c for c in line.get("chars", []) if c["text"].strip()), key=lambda c: c["x0"])
                    if any(positions[i + 1]["x0"] - positions[i]["x1"] > page.width * .18
                           for i in range(2, max(2, len(positions) - 3))):
                        split_lines += 1
                if split_lines >= 3:
                    raise DocumentError("INCOMPLETE_EXTRACTION", pages=[number])
                # Preserve lines and explicit table blocks; never collapse all whitespace.
                for line in lines:
                    value = line["text"]
                    budget.check(value)
                    blocks.append((line["top"], line["x0"], value, "text"))
                pages.append((number, page.height, sorted(blocks, key=lambda b: (b[0], b[1]))))
            finally:
                page.close()
            budget.check()
    if incomplete:
        raise DocumentError("INCOMPLETE_EXTRACTION", pages=sorted(set(scans + incomplete)))
    if scans:
        raise DocumentError("SCANNED_DOCUMENT" if len(scans) == count else "INCOMPLETE_EXTRACTION", pages=scans)
    if unreadable:
        raise DocumentError("UNREADABLE_TEXT", pages=unreadable)
    edge_counts = Counter()
    for _, height, blocks in pages:
        for value in {b[2] for b in blocks if b[3] == "text" and (b[0] < height * .08 or b[0] > height * .92)}:
            edge_counts[value] += 1
    output, removed = [], False
    page_number = re.compile(r"^(?:第\s*\d{1,3}\s*页(?:\s*共\s*\d{1,3}\s*页)?|\d{1,3}\s*(?:页|/\s*\d{1,3}|of\s+\d{1,3}))$", re.I)
    for _, height, blocks in pages:
        kept = []
        for top, _, text, kind in blocks:
            edge = top < height * .08 or top > height * .92
            title = edge_counts[text] >= max(3, count * .7) and text.strip().upper() in {"房屋租赁合同", "租赁合同", "租房合同", "LEASE AGREEMENT"}
            if kind == "text" and edge and (page_number.fullmatch(text.strip()) or title):
                removed = True
                continue
            kept.append(text)
        output.append("\n".join(kept))
    warnings = []
    if image_pages:
        warnings.append({"code": "IMAGE_TEXT_NOT_EXTRACTED", "message": "图片中的文字未提取，请核对图片、签名及印章。", "pages": image_pages})
    if removed:
        warnings.append({"code": "PAGE_DECORATION_REMOVED", "message": "已移除高置信页码或重复页标题，请对照原文件核对。", "pages": []})
    return "\n\n".join(output), count, tables, warnings
