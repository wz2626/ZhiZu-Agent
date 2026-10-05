# Day 1 回合 2：本地验证记录

验证日期：2026 年 10 月 5 日（北京时间）。本记录描述实际运行结果，不替代原始 Prompt 对话；三条核心 Prompt 链仍待补原始记录。

## 环境与范围

当前默认解释器为 Python 3.8，Python 启动器没有发现 3.12。因此使用 uv 在仓库内准备隔离的 Python 3.12.13 与 `.venv`，缓存和运行时存于已忽略的 `.runtime/`；没有全局安装 Python 或修改 Git 配置。

本回合只安装底座相关的六项直接依赖，版本为 FastAPI 0.142.2、uvicorn 0.54.0、Pydantic 2.13.5、python-dotenv 1.2.4、httpx 0.28.1、pytest 8.4.2，均在既定范围内。尚未安装或验证 RAG 相关依赖，未进行真实云 API 调用及完整 10 分钟复现计时。

## pytest

实际复测命令（仓库根目录，PowerShell）：

```powershell
New-Item -ItemType Directory -Path .pytest_cache -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest tests/test_health.py -q --basetemp=.pytest_cache/tmp --junitxml=docs/test-results/day01-round02-pytest.xml
```

- 首次执行没有预先创建 `.pytest_cache`，使用 `tmp_path` 的测试准备阶段报错：10 passed、1 error。保留[首次 JUnit](day01-round02-pytest-first.xml)。这是实际发生的命令问题，并非故障注入。
- 修正 README 测试命令并创建父目录后，复测得到 **11 passed、0 failed、0 error、0 skipped，耗时 0.54 秒**。保留[复测 JUnit](day01-round02-pytest.xml)。
- 两次运行均有 1 条 Starlette 关于 TestClient 使用 httpx 的弃用警告；没有隐藏该警告或为此变更既定依赖范围。
- 测试覆盖缺密钥、模板/部分/空白/完整密钥配置，JSON 和配置 repr 不泄露密钥，读取配置，其他工作目录下返回首页，Swagger/OpenAPI 以及本地 CORS 白名单。

## 实际启动与 HTTP 检查

使用 `.\.venv\Scripts\python.exe scripts/start.py` 启动 uvicorn，实际监听 `127.0.0.1:8000`。通过本地 HTTP 请求验证：

| 路由 | 结果 |
| --- | --- |
| `/api/health` | HTTP 200；`status=ok`、`project=ZhiZu-Agent`、`version=0.1.0`、`env_configured=false` |
| `/` | HTTP 200，中文 HTML 占位页 |
| `/docs` | HTTP 200，Swagger HTML |

缺密钥不阻止服务启动。`env_configured` 只检查配置完整性，不代表 API 密钥通过云端验证。验收服务随后停止，按 README 命令可重新启动。

## 页面检查

内联 JavaScript 经 Node 语法检查通过。普通沙箱下 Edge 渲染失败；随后使用仓库内隔离配置目录完成实际浏览器检查，未采用真实浏览器个人资料。

- [桌面截图：1440 × 1000](day01-round02-desktop.png)。浏览器 DOM 显示“正常运行”“尚未配置完整”，说明 `/api/health` 请求及状态展示实际执行。
- [窄屏截图：520 × 1450](day01-round02-narrow.png)。状态卡与三个场景按单列排列，检查范围内无内容重叠。

## 文件与权限核对

外层跳板 4 行，仓库 AGENTS.md 35 行；所要求的文件均存在，五个 `__init__.py` 均为空。LICENSE 的 SHA-256 与修改前一致。只执行 Git 白名单中的读取命令，没有执行 Git 写操作。
