# 智租博弈（ZhiZu-Agent）

面向青年租房押金扣留、维修责任和提前退租问题的 AI 辅助演练项目。目标流程是合同风险审查、模拟协商、导出协商清单。目前已具备 FastAPI 运行底座、《民法典》租赁合同 32 条法条知识库及只读状态、检索接口；合同审查图和谈判图仍在后续开发中。

## 核心特性（规划）

- **前置脱敏**：浏览器遮蔽手机号和身份证号，提供可编辑预览；后端调用云 API 前复查。
- **契光排雷**：基于《民法典》租赁合同第 703～734 条审查条款，联动脱敏原文并显示依据和协商建议。
- **沉浸道场**：租客辅导、模拟房东回应和最多 5 轮谈判。
- **Critic 有界回环**：失败最多重写 2 次，仍不合格返回 `needs_review`。
- **混合算分**：模型识别与解释，程序按已确认条件确定性算分。
- **真实 trace 回放**：返回完整 JSON 后回放实际执行节点，并导出协商清单。

## 目录

| 路径 | 用途 |
| --- | --- |
| `backend/app/api/` | FastAPI 接口 |
| `backend/app/core/` | 配置与公共能力 |
| `backend/app/graph/` | 风险审查图与谈判图 |
| `backend/app/schemas/` | 输入、输出与状态 Schema |
| `backend/app/services/` | 检索、模型适配与业务服务 |
| `backend/data/laws/` | 权威租赁法条数据 |
| `backend/data/scenarios/` | 三类演练场景与 20 个话术构造参考案例，不作为法律依据 |
| `frontend-web/` | 单文件 Vue 3 网页 |
| `scripts/` | 入库、启动和辅助脚本 |
| `tests/` | 自动化测试；后续固定 20 例工程测试集与演练参考案例分开管理 |
| `docs/specs/` | 模块规格；[总规格](docs/specs/spec-00-architecture.md) |
| `docs/prompt-history/` | 三条真实 AI 协作过程链 |
| `docs/test-results/` | 实际测试输出与结果 |

## Windows PowerShell：启动、入库与测试

以下命令在仓库根目录运行，使用已配置的 `.venv`。未填写聊天或向量 API 密钥时，法条入库的 `auto` 模式会使用确定性 mock 向量；真实云端向量需在本地 `.env` 配置有效密钥。法条数据只来自 `backend/data/laws/civil_code_lease_703_734.json`，演练案例不作为法律依据。

```powershell
# 仅在没有 .env 时复制模板，保留自己的已有配置
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# 使用当前配置的 CHROMA_PATH 入库；可加 --verify-queries 打印五类查询的 Top-3
.\.venv\Scripts\python.exe scripts/init_kb.py --verify-queries

# 离线验证建议使用独立目录，避免与云端向量混用
.\.venv\Scripts\python.exe scripts/init_kb.py --mode mock --persist-dir .runtime/chroma_mock --verify-queries

# 启动；在浏览器访问 http://127.0.0.1:8000，按 Ctrl+C 停止
.\.venv\Scripts\python.exe scripts/start.py
```

默认入库命令使用 `CHROMA_PATH`（未设置时为 `./backend/chroma_db`）；API 也读取此路径。离线独立目录用于测试，如需让 API 查看它，在启动服务前将 `CHROMA_PATH` 指向该目录。旧集合若缺少维度元数据，重新运行入库脚本即可在校验现有 1024 维向量后补录。

启动后可访问同源首页 `http://127.0.0.1:8000/`、健康接口 `/api/health`、知识库状态 `/api/kb/status` 和 Swagger `/docs`。知识库检索接口为 `POST /api/kb/search`，请求示例：`{"query":"房屋漏水由谁维修？","top_k":4}`。返回脱敏后的 `query`、`top_k`、`results`（法条证据）、`direct_basis_sufficient` 与 `boundary_notice`；未入库时返回 503 并提示运行 `scripts/init_kb.py`。押金问题仅展示相关条文，并明确提示本章没有押金返还的直接依据。

在仓库目录的另一个 PowerShell 窗口运行全量测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
```

`pytest.ini` 将缓存目录设为 `.runtime/pytest_cache`，避开旧的 `.pytest_cache` ACL 问题。`env_configured` 表示配置项已齐全且密钥不是模板占位值，不会联网验证密钥。`.env` 从仓库根目录加载，已有进程环境变量优先；健康 JSON 不返回密钥。单元测试使用合成配置，不调用云 API。首页从相同源请求 `/api/health`，CORS 仅允许本地 `127.0.0.1:8000` 与 `localhost:8000`。

本回合在 Python 3.12.13 下验证健康底座，11 项 pytest 通过；[验证记录](docs/test-results/day01-round02.md)保留首次命令问题、复测结果和页面截图。该次仅安装底座相关依赖，未验证全量 RAG 依赖及完整业务复现。

常见问题：提示缺少模块时，确认使用仓库的 `.venv`；端口 8000 被占用时，先停止占用该端口的本地服务。占位密钥显示“尚未配置完整”属于正常状态，不影响健康接口。切换 mock 与云端向量或更换模型时应使用不同集合或目录；错误维度的云端向量会在写入前被拒绝。

## 10 分钟极速复现指南（后续补全）

目标从克隆开始计时，包含依赖安装、配置、法条入库、启动和三场景复现；当前未完成全流程计时。法条入库、启动和测试命令见上文；后续补充三场景操作、AI 功能排错和实测耗时。固定 20 例工程测试集为 10 风险、4 正常、3 范围外、3 异常输入，与 20 个演练参考案例严格区分。

## 规格与过程证据

协作按 [AGENTS.md](AGENTS.md) 执行，后续实现以 [总规格](docs/specs/spec-00-architecture.md) 为基准。三条 Prompt 链分别记录法条检索与审查、图与 Critic、网页看板的真实 AI 交互和修复过程，归档时读取[归档总说明](docs/prompt-history/README.md)。当前各链仅有待补原始记录的索引，不表示完整对话证据已生成。
