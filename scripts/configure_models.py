"""Interactive local configuration. The browser never handles model keys."""

import argparse
import getpass
from io import StringIO
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from dotenv.parser import parse_stream

from launcher_files import ROOT, RUNTIME, InUse, atomic_write, file_lock

sys.path.insert(0, str(ROOT))
ENV_FILE = ROOT / ".env"
KEYS = {"1": ("聊天", "CHAT_API_KEY"), "2": ("向量", "EMBEDDING_API_KEY")}


def save_key(path, key, value):
    if not value.isascii() or not value.isprintable() or any(c.isspace() for c in value) or "${" in value:
        raise ValueError("密钥应为单行可打印字符，请重新复制。")
    raw = path.read_bytes().decode("utf-8-sig")
    quoted = "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    lines = []
    found = False
    for binding in parse_stream(StringIO(raw)):
        original = binding.original.string
        if binding.key == key:
            # Retain leading blank lines, export prefix, trailing comment and newline.
            pattern = (r"(?s)^(\s*(?:export\s+)?'?" + re.escape(key) +
                       r"'?\s*=\s*?)(?:'(?:(?:\\.)|[^'\\])*'|\"(?:(?:\\.)|[^\"\\])*\"|[^\r\n]*?)"
                       r"([ \t]+\#[^\r\n]*|[ \t]*)(\r?\n)?$")
            match = re.match(pattern, original)
            if not match:
                raise ValueError("配置行格式无法安全更新，请检查 .env 中对应配置。")
            original = match[1] + quoted + match[2] + (match[3] or "")
            found = True
        lines.append(original)
    if not found:
        newline = "\r\n" if "\r\n" in raw else "\n"
        if raw and not raw.endswith(("\r", "\n")):
            lines.append(newline)
        lines.append(key + "=" + quoted + newline)
    atomic_write(path, "".join(lines).encode("utf-8"))


def prepare_cloud():
    from backend.app.core.config import get_settings, kb_path
    from backend.app.services.embedding import get_embeddings
    from backend.app.services.vector_store import LawVectorStoreService

    settings = get_settings()
    if not settings.embedding_configured:
        print("请先配置向量 Key、服务地址和模型。")
        return
    target = kb_path(settings.chroma_path)
    embeddings = get_embeddings("cloud")
    print("当前知识库路径", target)
    status = LawVectorStoreService.inspect_status(target, embeddings=embeddings)
    if status.is_ready:
        print("32 条云法条索引已就绪，本次没有调用向量服务。")
        return
    if status.state != "missing":
        print("已有内容不兼容或无法读取。请检查 CHROMA_PATH 或为新库指定空目录。")
        return
    if input("将联网处理 32 条公开法条，可能产生向量用量。输入 1 确认，回车取消：").strip() != "1":
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    # Serialize even two project copies explicitly pointing to the same target.
    with file_lock(target.parent / ("." + target.name + ".init.lock")):
        if LawVectorStoreService.inspect_status(target, embeddings=embeddings).state != "missing":
            print("目录状态已改变，请重新检查。")
            return
        with tempfile.TemporaryDirectory(dir=target.parent, prefix=".zhizu-build-") as stage:
            built = Path(stage) / "laws"
            subprocess.run([sys.executable, "scripts/init_kb.py", "--mode", "cloud",
                            "--persist-dir", str(built)], cwd=ROOT, check=True)
            if not LawVectorStoreService.inspect_status(built, embeddings=embeddings).is_ready:
                raise ValueError("新索引验证失败，未发布。")
            if target.exists():
                target.rmdir()  # Succeeds only for a still-empty directory.
            built.rename(target)
    print("32 条法条索引准备完成，请在工作台刷新状态。")


def configure(first_start=False):
    # Capture external overrides before importing application modules that load .env.
    external = dict(os.environ)
    from backend.app.core.config import has_real_key

    while True:
        values = {**dotenv_values(ENV_FILE), **external}
        if first_start and all(has_real_key(values.get(key) or "") for _, key in KEYS.values()):
            return
        for title, key in KEYS.values():
            configured = has_real_key(values.get(key) or "")
            source = "（系统环境变量优先）" if key in external else ""
            print(title + " Key：" + ("已配置" if configured else "待配置") + source)
        if first_start:
            print("无 Key 可导入合同，聊天 Key 可用于回复分析。Windows 交付包已附默认法条索引，完整审查请再配置向量 Key。")
            if not sys.stdin.isatty():
                return
            try:
                choice = input("回车直接打开工作台；输入 1 配置模型：").strip()
            except EOFError:
                return
            if choice != "1":
                return
            first_start = False
        print("1  设置或更换聊天 Key")
        print("2  设置或更换向量 Key")
        print()
        print("3  法条库维护（仅在索引缺失或更换向量模型时使用）")
        action = input("请输入选项，或按回车退出：").strip()
        if not action:
            return
        if action == "3":
            # Fresh interpreter loads updated file; do not pass imported dotenv values as overrides.
            subprocess.run([sys.executable, "-X", "utf8", __file__, "--prepare-cloud"],
                           cwd=ROOT, env=external, check=True)
        elif action in KEYS:
            title, key = KEYS[action]
            if key in external:
                print("此项由系统环境变量提供，请在该来源修改后重新打开启动窗口。")
                continue
            if not sys.stdin.isatty():
                print("请在交互终端中输入密钥。")
                continue
            value = getpass.getpass(title + " Key（隐藏输入，回车保留）：").strip()
            if value:
                with file_lock(RUNTIME / "config.lock"):
                    save_key(ENV_FILE, key, value)
                print("已保存。正在运行的服务下次启动时生效。")
        else:
            print("请输入菜单中的编号。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-start", action="store_true")
    parser.add_argument("--prepare-cloud", action="store_true")
    args = parser.parse_args()
    try:
        if args.prepare_cloud:
            prepare_cloud()
        else:
            configure(args.first_start)
    except InUse:
        sys.exit("另一个配置窗口正在准备该目录，请等待后重试。")
    except (OSError, ValueError, EOFError, subprocess.CalledProcessError) as error:
        print("操作未完成，请核对目录权限、配置和上方提示后重试。", type(error).__name__, file=sys.stderr)
        sys.exit(1)

