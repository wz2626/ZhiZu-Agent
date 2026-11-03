"""Bounded local extraction policy. No document contents in diagnostics."""

from dataclasses import dataclass, field
from importlib.metadata import version
from time import monotonic

PARSE_PATH = "/api/contracts/parse"
POLICY_VERSION = "doc-extract-v2"
FILE_BYTES = 10 * 1024 * 1024
BODY_BYTES = 11 * 1024 * 1024
UPLOAD_SECONDS = 60
PARSE_SECONDS = 20
MAX_PAGES = 50
MAX_TEXT = 20000
MAX_RAW_TEXT = 100000

MESSAGES = {
    "INVALID_UPLOAD": "请上传一个 Word（.docx）或 PDF 文件，不要附加其他字段。",
    "FILE_TOO_LARGE": "文件超过 10 MiB，请压缩文件或保留需要核查的内容后重试。",
    "REQUEST_TOO_LARGE": "上传请求超过大小限制，请选择不超过 10 MiB 的文件。",
    "UNSUPPORTED_FILE_TYPE": "仅支持 .docx 和 .pdf 文件，请转换格式后重试。",
    "FILE_TYPE_MISMATCH": "文件内容与扩展名不一致，请另存为正确格式后重试。",
    "EMPTY_FILE": "文件为空，请重新选择。",
    "ENCRYPTED_DOCUMENT": "文档已加密，请在本机解除加密后重新上传。",
    "CORRUPTED_DOCUMENT": "文件损坏或结构无效，请用原软件重新保存后上传。",
    "UNSAFE_DOCUMENT": "文档结构未通过安全检查，请另存为普通 DOCX 或文字型 PDF。",
    "DOCUMENT_LIMIT_EXCEEDED": "文档超过页数或结构容量限制（PDF 最多 50 页），请调整后重试。",
    "SCANNED_DOCUMENT": "文件疑似扫描件，当前无法读取图片中的正文。请在本机识别文字、核对后粘贴，或上传可复制文字的文件。",
    "INCOMPLETE_EXTRACTION": "文档含扫描页或无法可靠读取的正文结构，未填入残缺文字。请转换为可复制文字的文件后重试。",
    "UNREADABLE_TEXT": "文档文字存在严重乱码或字体映射异常，请另存为 Word 或可复制文字的 PDF。",
    "NO_EXTRACTABLE_TEXT": "没有找到可读取的合同正文，请检查文件或手动粘贴文字。",
    "TEXT_TOO_LONG": "提取正文超过 20000 字，未截断或覆盖当前内容。请整理文件后重试。",
    "PARSER_BUSY": "文件解析繁忙，请稍后手动重试；当前正文仍然保留。",
    "PARSE_TIMEOUT": "文件解析超过处理期限，请简化文件或手动粘贴文字后重试。",
    "UPLOAD_TIMEOUT": "文件上传超时，请检查连接后手动重试。",
    "PARSE_FAILED": "本次未能提取文字，请重新保存文件或手动粘贴正文。",
    "INTERACTION_VERSION": "交互协议已更新，请刷新页面。",
}


class DocumentError(Exception):
    def __init__(self, code, *, status=422, pages=None):
        super().__init__(code)
        self.code, self.status, self.pages = code, status, pages or []


def extractor_info(format_name):
    package = {"pdf": "pdfplumber", "docx": "python-docx"}.get(format_name)
    return ({"name": package, "version": version(package), "policy_version": POLICY_VERSION}
            if package else None)


def error_body(error, request_id, extractor=None):
    message = MESSAGES.get(error.code, MESSAGES["PARSE_FAILED"])
    if error.pages:
        message = "第 " + "、".join(map(str, error.pages)) + " 页：" + message
    return {"detail": {"code": error.code, "message": message,
                       "retryable": error.code in {"PARSER_BUSY", "PARSE_TIMEOUT", "UPLOAD_TIMEOUT", "PARSE_FAILED"},
                       "pages": error.pages, "request_id": request_id,
                       "extractor": extractor, "policy_version": POLICY_VERSION}}


@dataclass
class Budget:
    deadline: float = field(default_factory=lambda: monotonic() + PARSE_SECONDS)
    raw_chars: int = 0
    cells: int = 0

    def check(self, text="", cells=0):
        if monotonic() >= self.deadline:
            raise DocumentError("PARSE_TIMEOUT", status=504)
        self.raw_chars += len(text)
        self.cells += cells
        if self.raw_chars > MAX_RAW_TEXT or self.cells > 20000:
            raise DocumentError("DOCUMENT_LIMIT_EXCEEDED")
