"""Synthetic local documents: HTTP, preservation, mixed scans, and worker ownership."""

import asyncio
import zlib
from io import BytesIO
from threading import Event
from zipfile import ZipFile, ZIP_STORED

import anyio
import httpx
import pytest
from docx import Document
from fastapi.testclient import TestClient
from starlette.datastructures import FormData, UploadFile
from PIL import Image, ImageDraw

from backend.app.main import app
from backend.app.core.document_limits import BODY_BYTES, FILE_BYTES, Budget, DocumentError
from backend.app.core.privacy import privacy_policy, redact_pii
from backend.app.services.contract_parser import parse_contract
from backend.app.services.contract_text import clean_text, finish_text
from backend.app.services.parse_jobs import ParseRuntime

HEADERS = {"X-Interaction-Version": "4"}


def word(text="房屋租赁合同，押金2500元，维修费用由房东承担。", table=False):
    doc, stream = Document(), BytesIO()
    doc.add_paragraph(text)
    if table:
        t = doc.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "项目", "金额"
        t.cell(1, 0).text, t.cell(1, 1).text = "押金", "2500元"
        doc.add_paragraph("合同尾部：退租后应返还押金。")
    doc.save(stream)
    return stream.getvalue()


def padded_word(target_size=FILE_BYTES):
    raw = word()
    def build(padding):
        result = BytesIO()
        with ZipFile(BytesIO(raw)) as source, ZipFile(result, "w", ZIP_STORED) as archive:
            for info in source.infolist():
                archive.writestr(info.filename, source.read(info))
            archive.writestr("word/media/test-padding.bin", b"x" * padding)
        return result.getvalue()
    baseline = len(build(0))
    return build(target_size - baseline)


def pdf(pages, *, table=False):
    """Minimal generated PDF with CJK font mapping; no runtime generator dependency."""
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [4 0 R] >>",
               b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> >>"]
    ids = []
    for text in pages:
        page_id, content_id = len(objects) + 1, len(objects) + 2
        ids.append(page_id)
        resources = b"/Font << /F1 3 0 R >>"
        if text is None:
            image_id = len(objects) + 3
            resources += f" /XObject << /Im1 {image_id} 0 R >>".encode()
            content = b"q 595 0 0 842 0 0 cm /Im1 Do Q"
        else:
            content = b""
            for i, line in enumerate(text.split("\n")):
                content += f"BT /F1 12 Tf 50 {760 - i * 20} Td <{line.encode('utf-16-be').hex()}> Tj ET\n".encode()
            if table:
                content += b"50 650 m 350 650 l 50 680 m 350 680 l 50 710 m 350 710 l 50 650 m 50 710 l 200 650 m 200 710 l 350 650 m 350 710 l S\n"
                for x, y, value in [(60, 690, "项目"), (210, 690, "金额"), (60, 660, "押金"), (210, 660, "2500元")]:
                    content += f"BT /F1 12 Tf {x} {y} Td <{value.encode('utf-16-be').hex()}> Tj ET\n".encode()
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << ".encode() + resources + f" >> /Contents {content_id} 0 R >>".encode())
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        if text is None:
            objects.append(b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 3 >>\nstream\n\xff\xff\xff\nendstream")
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(str(i) + ' 0 R' for i in ids)}] /Count {len(ids)} >>".encode()
    result, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for i, value in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{i} 0 obj\n".encode() + value + b"\nendobj\n")
    offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for value in offsets[1:]:
        result.extend(f"{value:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF".encode())
    return bytes(result)


def image_pdf(kind="logo", *, body=True, encoding="flate", text_y=760, display_size=500):
    """Real text plus a 500x500 displayed raster; no OCR/model test double."""
    bitmap = Image.new("RGB", (400, 400), "white")
    draw = ImageDraw.Draw(bitmap)
    if kind == "scan":
        for y in range(30, 350, 25):
            draw.text((30, y), "Supplementary agreement: deposit and penalties", fill="black")
    else:
        draw.ellipse((90, 90, 310, 310), fill=(30, 110, 100))
    pixels = bitmap.tobytes()
    if encoding == "jpeg":
        image_file = BytesIO()
        bitmap.save(image_file, format="JPEG")
        image_data, filter_name = image_file.getvalue(), b" /Filter /DCTDecode"
    elif encoding == "flate":
        image_data, filter_name = zlib.compress(pixels), b" /Filter /FlateDecode"
    else:
        image_data, filter_name = pixels, b" /Filter /UnsupportedAuditFilter"
    bitmap.close()
    content = f"q {display_size} 0 0 {display_size} 50 0 cm /Im1 Do Q\n".encode()
    lines = [("房屋租赁合同，押金按约返还，维修由房东负责。", 50, text_y - i * 16) for i in range(10)] if body else [("合同补充协议请查看下方图片", 50, 815)]
    if body == "short":
        lines = [("房屋租赁合同，押金按约返还。", 50, text_y)]
    for text, x, y in lines:
        content += f"BT /F1 12 Tf {x} {y} Td <{text.encode('utf-16-be').hex()}> Tj ET\n".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [5 0 R] /Count 1 >>",
               b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [4 0 R] >>",
               b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> /XObject << /Im1 7 0 R >> >> /Contents 6 0 R >>",
               f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
               b"<< /Type /XObject /Subtype /Image /Width 400 /Height 400 /ColorSpace /DeviceRGB /BitsPerComponent 8" + filter_name + f" /Length {len(image_data)} >>\nstream\n".encode() + image_data + b"\nendstream"]
    result, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, value in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{i} 0 obj\n".encode() + value + b"\nendobj\n")
    offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for value in offsets:
        result.extend(f"{value:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF".encode())
    return bytes(result)


def upload(data, name="合同.docx"):
    with TestClient(app) as client:
        return client.post("/api/contracts/parse", files={"file": (name, data)}, headers=HEADERS)


def test_word_api_preserves_order_and_table_and_only_returns_text():
    response = upload(word(table=True))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["text"].index("房屋租赁合同") < data["text"].index("| 押金 | 2500元 |") < data["text"].index("合同尾部")
    assert data["char_count"] == len(data["text"])
    assert data["document"]["page_count"] is None and data["document"]["table_count"] == 1
    assert data["extractor"]["version"] == "1.2.0" and len(data["request_id"]) == 32
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("format_name", ["docx", "pdf"])
def test_news_document_can_be_extracted_but_not_accepted_as_a_rental_contract(monkeypatch, format_name):
    from backend.app.services import review as review_module

    def forbidden(*args, **kwargs):
        pytest.fail("news input must stop before model initialization, retrieval or context creation")

    monkeypatch.setattr(review_module.ContractReviewService, "_initialize_chat_if_needed", forbidden)
    monkeypatch.setattr(review_module, "LawVectorStoreService", forbidden)
    monkeypatch.setattr(review_module.review_graph, "invoke", forbidden)
    monkeypatch.setattr(review_module.review_context_store, "create", forbidden)
    text = "各位观众晚上好，欢迎收看今天的《新闻联播》。\n今天的主要内容：各地积极应对降温天气。"
    raw = word(text) if format_name == "docx" else pdf([text])
    with TestClient(app) as client:
        extracted = client.post("/api/contracts/parse", headers=HEADERS,
                                files={"file": ("新闻稿." + format_name, raw)})
        assert extracted.status_code == 200, extracted.text
        assert "欢迎收看" in extracted.json()["text"]
        response = client.post("/api/review/analyze-detailed", headers=HEADERS,
                               json={"contract_text": extracted.json()["text"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "needs_review" and result["failure_code"] == "OUT_OF_SCOPE"
    assert result["results"] == [] and result["review_context_id"] is None
    assert result["evidence_by_id"] == {} and result["retry_count"] == 0
    assert [event["node"] for event in result["trace"]] == ["input_guard"]


def test_actual_10mib_file_accepted_not_confused_with_spool_threshold():
    raw = padded_word()
    assert len(raw) == FILE_BYTES
    response = upload(raw)
    assert response.status_code == 200, response.text
    assert "押金2500元" in response.json()["text"]


@pytest.mark.parametrize("count", [10, 4999, 5000, 5001, 20000, 20001])
def test_no_silent_truncation(count):
    # Vary content to keep the test outside the independent compression-ratio guard.
    text = "".join(chr(0x4e00 + i % 8000) for i in range(count))
    response = upload(word(text))
    if count > 20000:
        assert response.status_code == 422 and response.json()["detail"]["code"] == "TEXT_TOO_LONG"
        assert "text" not in response.json()
    else:
        assert response.status_code == 200, response.text
        assert response.json()["text"] == text


def test_pdf_chinese_and_bbox_table_deduplication():
    response = upload(pdf(["房屋租赁合同\n合同尾部：退租返还押金。"], table=True), "合同.PDF")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["document"]["table_count"] == 1
    assert data["text"].count("2500元") == 1 and "| 押金 | 2500元 |" in data["text"]


@pytest.mark.parametrize("encoding", ["flate", "jpeg"])
def test_readable_body_and_large_logo_is_not_a_scanned_page(encoding):
    response = upload(image_pdf(encoding=encoding), "logo.pdf")
    assert response.status_code == 200, response.text
    assert response.json()["text"].count("押金按约返还") == 10
    assert any(w["code"] == "IMAGE_TEXT_NOT_EXTRACTED" for w in response.json()["warnings"])


def test_short_readable_body_and_large_graphic_is_not_automatically_a_scan():
    response = upload(image_pdf(body="short"), "logo-short.pdf")
    assert response.status_code == 200, response.text


def test_edge_text_does_not_hide_a_smaller_scanned_body():
    response = upload(image_pdf("scan", body=False, display_size=300), "partial-page-scan.pdf")
    assert response.status_code == 422 and response.json()["detail"]["code"] == "SCANNED_DOCUMENT"


@pytest.mark.parametrize("body,encoding,expected", [(False, "flate", "SCANNED_DOCUMENT"), (True, "flate", "INCOMPLETE_EXTRACTION"), (True, "jpeg", "INCOMPLETE_EXTRACTION"), (True, "unknown", "INCOMPLETE_EXTRACTION")])
def test_large_scan_or_uninspectable_image_never_returns_partial_body(body, encoding, expected):
    response = upload(image_pdf("scan", body=body, encoding=encoding), "image.pdf")
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == expected
    assert response.json()["detail"]["pages"] == [1]
    assert "text" not in response.json()


def test_readable_ocr_layer_over_document_image_is_accepted():
    response = upload(image_pdf("scan", text_y=450), "ocr.pdf")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("artifact", ["\u200b", "\ufeff", "\u2060", "\u00ad"])
def test_extraction_artifact_cleanup_is_explicit_and_idempotent(artifact):
    text = artifact + "合同" + artifact + "正文，金额２５００元。"
    cleaned = clean_text(text)
    assert cleaned == "合同正文，金额２５００元。"
    assert clean_text(cleaned) == cleaned


def test_meaningful_format_characters_are_preserved():
    text = "نام\u200cخانوادگی，👩\u200d💻，合同\n押金\t2500元。"
    assert clean_text(text) == text


def test_raster_inspection_rejects_oversize_metadata_without_decoding():
    from backend.app.services.pdf_images import image_text_signal
    class NeverDecode:
        def get_rawdata(self):
            pytest.fail("oversized metadata must not decode")
    assert image_text_signal({"srcsize": (10000, 10000), "stream": NeverDecode()}, Budget()) is None


@pytest.mark.parametrize("attribute", ["SMask", "Mask", "Decode"])
def test_unhandled_image_compositing_cannot_be_mistaken_for_a_decoration(attribute):
    from backend.app.services.pdf_images import image_text_signal
    class Unhandled:
        attrs = {attribute: [1, 0]}
        def get_rawdata(self):
            pytest.fail("cannot classify masked/inverted image by its raw pixels")
    assert image_text_signal({"srcsize": (100, 100), "stream": Unhandled()}, Budget()) is None


@pytest.mark.parametrize("pages,code,positions", [([None], "SCANNED_DOCUMENT", [1]),
                                                  (["房屋租赁合同：押金条款。", None], "INCOMPLETE_EXTRACTION", [2])])
def test_scanned_pages_never_return_partial_text(pages, code, positions):
    response = upload(pdf(pages), "scan.pdf")
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code and detail["pages"] == positions
    assert "text" not in response.json() and "押金条款" not in response.text


def test_page_limit_and_corruption():
    assert upload(pdf(["合同"] * 51), "pages.pdf").json()["detail"]["code"] == "DOCUMENT_LIMIT_EXCEEDED"
    assert upload(b"%PDF-1.4\nbroken", "bad.pdf").json()["detail"]["code"] == "CORRUPTED_DOCUMENT"


@pytest.mark.parametrize("data,name,status,code", [(b"", "a.docx", 422, "EMPTY_FILE"),
    (b"text", "a.doc", 415, "UNSUPPORTED_FILE_TYPE"), (word(), "a.pdf", 415, "FILE_TYPE_MISMATCH"),
    (b"x" * (FILE_BYTES + 1), "a.pdf", 413, "FILE_TOO_LARGE"),
    (b"x" * (BODY_BYTES + 1), "a.pdf", 413, "REQUEST_TOO_LARGE")],
    ids=["empty", "unsupported", "mismatch", "file_limit", "body_limit"])
def test_controlled_errors(data, name, status, code):
    response = upload(data, name)
    assert response.status_code == status
    detail = response.json()["detail"]
    assert detail["code"] == code and detail["request_id"] and "extractor" in detail
    assert name not in response.text


def test_multipart_fields_duplicates_and_busy():
    from backend.app.api import contracts
    with TestClient(app) as client:
        for kwargs in [{"files": [("file", ("a.docx", word())), ("file", ("b.docx", word()))]},
                       {"files": {"file": ("a.docx", word())}, "data": {"extra": "DO_NOT_ECHO"}}]:
            response = client.post("/api/contracts/parse", headers=HEADERS, **kwargs)
            assert response.status_code == 400 and response.json()["detail"]["code"] == "INVALID_UPLOAD"
            assert "DO_NOT_ECHO" not in response.text
        leases = [contracts.parse_runtime.admit(), contracts.parse_runtime.admit()]
        try:
            response = client.post("/api/contracts/parse", headers=HEADERS, files={"file": ("a.docx", word())})
            assert response.status_code == 503 and response.json()["detail"]["code"] == "PARSER_BUSY"
            assert response.headers["connection"] == "close"
        finally:
            for lease in leases:
                lease.release()


def test_zip_unsafe_and_tracked_changes():
    raw, result = word(), BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(result, "w") as archive:
        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename == "word/document.xml":
                content = content.replace(b"<w:body>", b"<w:body><w:ins/>")
            archive.writestr(entry, content)
    assert upload(result.getvalue()).json()["detail"]["code"] == "INCOMPLETE_EXTRACTION"
    with ZipFile(result := BytesIO(), "w") as archive:
        archive.writestr("../bad", "x")
    assert upload(result.getvalue()).json()["detail"]["code"] == "UNSAFE_DOCUMENT"


def test_word_numbering_merged_cells_and_headers():
    doc, stream = Document(), BytesIO()
    doc.add_paragraph("押金应在期满后返还。", style="List Number")
    doc.add_paragraph("维修费用由房东承担。", style="List Number")
    doc.sections[0].header.paragraphs[0].text = "请核对页眉补充约定"
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "合并金额标题"
    table.cell(1, 0).text = "押金"
    table.cell(1, 1).text = "2500元"
    doc.save(stream)
    response = upload(stream.getvalue())
    assert response.status_code == 200, response.text
    data = response.json()
    assert "1. 押金" in data["text"] and "2. 维修" in data["text"]
    assert data["text"].count("合并金额标题") == 1
    assert any(w["code"] == "HEADER_FOOTER_REVIEW" for w in data["warnings"])


def test_encrypted_office_and_pdf_forms_are_not_claimed_readable():
    assert upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1").json()["detail"]["code"] == "ENCRYPTED_DOCUMENT"
    raw = pdf(["房屋租赁合同：交互表单值不在正文中。"])
    raw = raw.replace(b"/Type /Catalog", b"/Type /Catalog /AcroForm << /Fields [] >>", 1)
    response = upload(raw, "form.pdf")
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INCOMPLETE_EXTRACTION"


def test_zip_expansion_and_xml_entity_guard():
    raw, result = word(), BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(result, "w") as archive:
        for info in source.infolist():
            content = source.read(info)
            if info.filename == "word/document.xml":
                content = content.replace(b"?>", b'?><!DOCTYPE document [<!ENTITY test "private">]>', 1)
            archive.writestr(info, content)
    assert upload(result.getvalue()).json()["detail"]["code"] == "UNSAFE_DOCUMENT"
    with ZipFile(result := BytesIO(), "w") as archive:
        for i in range(2001):
            archive.writestr(str(i), b"")
    assert upload(result.getvalue()).json()["detail"]["code"] == "DOCUMENT_LIMIT_EXCEEDED"


@pytest.mark.parametrize("text", ["138\r\n0000\r\n0000", "１３８　００００　００００", "138 \n0000 0000", "110101\n19900101\n000X", "+86 138-0000-0000"])
def test_grouped_privacy(text):
    assert redact_pii(text) == "***"


@pytest.mark.parametrize("text", ["押金2500元，租金2500元", "2026年11月3日", "| 138 | 2500 | 2500 |", "138000000000", "13800000000 0", "2500 元 2500 元", "1 3 8 0 0 0 0 0 0 0 0", "138\n\n0000\n0000", " " * 5000], ids=["amounts", "date", "table", "12digits", "separated12", "currency", "digitwise", "blankline", "whitespace5000"])
def test_privacy_negative_cases(text):
    assert redact_pii(text) == text
    assert max(len(privacy_policy()[key]) for key in ("phone_pattern", "id_pattern", "separator_pattern")) <= 1024


async def reached(predicate):
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(.002)
    raise AssertionError("worker did not reach expected phase")


@pytest.mark.parametrize("cancel", ["native_waiter", "anyio_waiter", "native_job"])
def test_running_job_owns_file_and_slot_after_cancellation(cancel):
    async def scenario():
        runtime, entered, release = ParseRuntime(1), Event(), Event()
        stream = BytesIO(b"test")
        form = FormData({"file": UploadFile(stream)})
        def work():
            entered.set()
            assert release.wait(3)
            assert not stream.closed
            return "done"
        job = runtime.start(form, runtime.admit(), work)
        await reached(entered.is_set)
        try:
            if cancel == "native_job":
                job.task.cancel()
                await asyncio.gather(job.task, return_exceptions=True)
            elif cancel == "native_waiter":
                async def wait():
                    return await asyncio.shield(job.task)
                waiter = asyncio.create_task(wait())
                await asyncio.sleep(0)
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            else:
                async with anyio.create_task_group() as group:
                    async def wait_scope():
                        await asyncio.shield(job.task)
                    group.start_soon(wait_scope)
                    await asyncio.sleep(0)
                    group.cancel_scope.cancel()
            assert runtime.admit() is None and not stream.closed
        finally:
            release.set()
            await reached(lambda: job.cleaned)
            await asyncio.gather(job.task, return_exceptions=True)
        assert stream.closed
        lease = runtime.admit()
        assert lease is not None
        lease.release()
    asyncio.run(scenario())


def test_cancel_before_worker_starts_releases_exactly_once():
    async def scenario():
        runtime, stream = ParseRuntime(1), BytesIO(b"test")
        job = runtime.start(FormData({"file": UploadFile(stream)}), runtime.admit(), lambda: pytest.fail("must not execute"))
        job.task.cancel()
        await asyncio.gather(job.task, return_exceptions=True)
        await asyncio.sleep(0)
        assert stream.closed
        job.task_done(job.task)
        lease = runtime.admit()
        assert lease is not None and runtime.admit() is None
        lease.release()
    asyncio.run(scenario())


def test_cancel_while_waiting_for_shared_thread_capacity():
    async def scenario():
        from starlette.concurrency import run_in_threadpool
        limiter = anyio.to_thread.current_default_thread_limiter()
        old_tokens = limiter.total_tokens
        limiter.total_tokens = 1
        occupied, release = Event(), Event()
        def blocker():
            occupied.set()
            assert release.wait(3)
        blocker_task = asyncio.create_task(run_in_threadpool(blocker))
        await reached(occupied.is_set)
        runtime, stream = ParseRuntime(1), BytesIO(b"test")
        job = runtime.start(FormData({"file": UploadFile(stream)}), runtime.admit(), lambda: pytest.fail("queued work cancelled"))
        try:
            await asyncio.sleep(.02)
            assert not job.started
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            await reached(lambda: job.cleaned)
            assert stream.closed
            lease = runtime.admit()
            assert lease is not None
            lease.release()
        finally:
            release.set()
            await blocker_task
            limiter.total_tokens = old_tokens
    asyncio.run(scenario())


def test_budget_and_cleaning_do_not_truncate_or_rewrite_values():
    with pytest.raises(DocumentError, match="PARSE_TIMEOUT"):
        Budget(deadline=0).check()
    assert finish_text("合同\r\n\r\n\r\n金额２５００元，比例50%。") == "合同\n\n金额２５００元，比例50%。"


@pytest.mark.parametrize("failure", ["truncated", "disconnect", "oversize"])
def test_partial_multipart_spools_close_on_receive_failure(monkeypatch, failure):
    import starlette.formparsers as parsers
    original, spools = parsers.SpooledTemporaryFile, []
    class Tracked(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closes = 0
            spools.append(self)
        def close(self):
            self.closes += 1
            return super().close()
    monkeypatch.setattr(parsers, "SpooledTemporaryFile", Tracked)
    async def scenario():
        from starlette.requests import ClientDisconnect
        async def body():
            yield b'--test\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4\n'
            if failure == "disconnect":
                raise ClientDisconnect()
            if failure == "oversize":
                for _ in range(12):
                    yield b"x" * 1024 * 1024
            # Deliberately no terminating boundary.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            response = await client.post("/api/contracts/parse", headers={**HEADERS, "Content-Type": "multipart/form-data; boundary=test"}, content=body())
        assert response.status_code == (413 if failure == "oversize" else 400)
        assert spools and all(s.closed and s.closes == 1 for s in spools)
        from backend.app.api.contracts import parse_runtime
        leases = [parse_runtime.admit(), parse_runtime.admit()]
        assert all(leases)
        for lease in leases:
            lease.release()
    asyncio.run(scenario())


def test_submit_failure_leaves_cleanup_with_route(monkeypatch):
    from backend.app.api import contracts
    def fail(*args, **kwargs):
        raise RuntimeError("do not echo")
    monkeypatch.setattr(contracts.parse_runtime, "start", fail)
    response = upload(word())
    assert response.status_code == 500 and "do not echo" not in response.text
    lease = contracts.parse_runtime.admit()
    assert lease is not None
    lease.release()


@pytest.mark.parametrize("failure", ["registration", "create", "callback", "callback_after_attach"])
def test_handoff_failure_cannot_leave_executable_work_or_double_cleanup(monkeypatch, failure):
    from backend.app.services import parse_jobs
    async def scenario():
        runtime, calls, created = ParseRuntime(1), [], []
        class Counted(BytesIO):
            closes = 0
            def close(self):
                self.closes += 1
                super().close()
        class BrokenSet(set):
            def add(self, job):
                super().add(job)  # Also cover registration that partially succeeds.
                raise RuntimeError("registration failed")
        class BrokenTask(asyncio.Task):
            def add_done_callback(self, fn, *, context=None):
                if failure == "callback_after_attach":
                    super().add_done_callback(fn, context=context)
                raise RuntimeError("callback failed")
        stream = Counted(b"contract")
        form, lease = FormData({"file": UploadFile(stream)}), runtime.admit()
        if failure == "registration":
            runtime.jobs = BrokenSet()
        original = asyncio.create_task
        def make_task(coroutine):
            if failure == "create":
                raise RuntimeError("create failed")
            task = BrokenTask(coroutine) if failure.startswith("callback") else original(coroutine)
            created.append(task)
            return task
        with monkeypatch.context() as patch:
            patch.setattr(parse_jobs.asyncio, "create_task", make_task)
            with pytest.raises(RuntimeError):
                runtime.start(form, lease, lambda: calls.append("must not execute"))
            # Same pre-transfer finally path as the HTTP route.
            parse_jobs.close_form(form)
            lease.release()
        if created:
            # These tasks are already cancelled; wait without registering more
            # callbacks on the deliberately broken Task subclass.
            await asyncio.sleep(0)
            assert all(task.done() and task.cancelled() for task in created)
        assert not calls and stream.closes == 1 and not runtime.jobs
        recovered = runtime.admit()
        assert recovered is not None and runtime.admit() is None
        recovered.release()
    asyncio.run(scenario())


def test_eager_task_factory_cannot_run_work_before_handoff():
    async def scenario():
        runtime, observed, stream = ParseRuntime(1), [], BytesIO(b"contract")
        loop = asyncio.get_running_loop()
        old = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            job = runtime.start(FormData({"file": UploadFile(stream)}), runtime.admit(), lambda: observed.append(stream.closed))
            assert not job.started and not observed and not stream.closed
            await job.task
            assert observed == [False] and stream.closed
        finally:
            loop.set_task_factory(old)
    asyncio.run(scenario())


def test_version_and_upload_encoding_errors_have_diagnostics(monkeypatch):
    monkeypatch.delenv("V4_ALLOW_LEGACY_HEADERS", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/contracts/parse", files={"file": ("a.docx", word())})
        assert response.status_code == 409 and response.json()["detail"]["request_id"]
        response = client.post("/api/contracts/parse", headers={**HEADERS, "Content-Encoding": "gzip"}, files={"file": ("a.docx", word())})
        assert response.status_code == 400 and response.json()["detail"]["extractor"] is None
