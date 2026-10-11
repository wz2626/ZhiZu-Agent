# 智租博弈（ZhiZu-Agent）

面向青年租房押金扣留、维修责任和提前退租问题的 AI 辅助演练项目。目标流程是合同风险审查、模拟协商、导出协商清单。目前已具备 FastAPI 运行底座、《民法典》租赁合同 32 条法条知识库、只读状态与检索接口、“契光排雷”合同审查核心服务和 API，以及 LangGraph 起草与 Critic 有界重写图。Day 5 已完成首次真实云端小规模联调，并提供详细失败出口与实际节点 Trace；完整语义质检、前端回放、谈判图及业务网页仍待后续验证或实现。

Day 5 已确认先做首次真实模型小规模验证，再完善失败出口和 trace；新窗口从 [Day 5 交接说明](docs/day05-handoff.md) 开始。配置继续通过本地 `.env`，网页填写 API Key 的入口暂不纳入任务。

2026-10-11：DeepSeek `deepseek-flash` + 硅基流动 `BAAI/bge-m3` 已完成真实 32 条入库、重复入库、五类检索和两份合成合同审查，见 [Day 5 回合 1 实测](docs/test-results/day05-round01.md)。后半段经用户正式授权新增 `/api/review/analyze-detailed` 与 Trace 契约，旧接口保留兼容行为；离线故障验证见 [Day 5 回合 2 实测](docs/test-results/day05-round02.md)。转租授权和正常合同疑似误报进入[已知问题](docs/known-issues.md)，后续集中复核与调优。

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
| `backend/app/graph/` | 执行图预留目录；当前审查图实现在 `backend/app/services/graph.py` |
| `backend/app/schemas/` | 输入、输出与状态 Schema |
| `backend/app/services/` | 检索、模型适配与业务服务 |
| `backend/data/laws/` | 权威租赁法条数据 |
| `backend/data/scenarios/` | 三类演练场景与 20 个话术构造参考案例，不作为法律依据 |
| `frontend-web/` | 当前为 HTML/JavaScript 健康检查页；单文件 Vue 3 业务网页待实现 |
| `scripts/` | 入库、启动和辅助脚本 |
| `tests/` | 自动化测试；后续固定 20 例工程测试集与演练参考案例分开管理 |
| `docs/specs/` | 模块规格；[总规格](docs/specs/spec-00-architecture.md) |
| `docs/prompt-history/` | 三条真实 AI 协作过程链 |
| `docs/test-results/` | 实际测试输出与结果 |

## Windows PowerShell：启动、入库与测试

以下命令在仓库根目录运行，使用已配置的 `.venv`。安装依赖使用 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`，其中包含本机 SOCKS 代理所需的 httpx 扩展。法条数据只来自 `backend/data/laws/civil_code_lease_703_734.json`，演练案例不作为法律依据。

`.env.example` 使用已经验证过的双平台组合，两把 Key 必须来自各自的平台。DeepSeek Flash 用于聊天分析，BGE-M3 用于生成1024维向量，不能将聊天模型名填进向量配置：

```dotenv
CHAT_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-flash
CHAT_API_KEY=your_deepseek_api_key_here
CHAT_TIMEOUT_SECONDS=60

EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_KEY=your_siliconflow_api_key_here
CHROMA_PATH=./.runtime/chroma_cloud
```

保留已有 `.env`，只在本地替换两处占位密钥；不上传或提交它。60秒是此组合验证使用的聊天网络超时，代码缺省仍为20秒。已有进程环境变量优先于 `.env`，修改后重启服务。健康检查 `env_configured=true` 只表示配置完整，不证明 Key 可用或已成功审查。

```powershell
# 仅在没有 .env 时复制模板，保留自己的已有配置
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# 填好两把 Key 后显式使用 cloud，避免 auto 在缺 Key 时静默回退
.\.venv\Scripts\python.exe scripts/init_kb.py --mode cloud --verify-queries

# 启动；在浏览器访问 http://127.0.0.1:8000，按 Ctrl+C 停止
.\.venv\Scripts\python.exe scripts/start.py
```

入库和 API 必须读取同一 `CHROMA_PATH`；上述模板使用独立云端目录 `.runtime/chroma_cloud`，代码未配置时默认 `./backend/chroma_db`。离线开发可另行运行 `.\.venv\Scripts\python.exe scripts/init_kb.py --mode mock --persist-dir .runtime/chroma_mock --verify-queries`；如需让 API 使用离线库，启动前配置其路径并清空向量密钥，不混用两种向量。`auto` 模式缺有效向量密钥会回退 Mock，真实验证请显式指定 `cloud`。旧集合若缺少维度元数据，重新运行入库脚本即可在校验现有 1024 维向量后补录。

启动后可访问同源首页 `http://127.0.0.1:8000/`、健康接口 `/api/health`、知识库状态 `/api/kb/status` 和 Swagger `/docs`。知识库检索接口为 `POST /api/kb/search`，请求示例：`{"query":"房屋漏水由谁维修？","top_k":4}`。返回脱敏后的 `query`、`top_k`、`results`（法条证据）、`direct_basis_sufficient` 与 `boundary_notice`；缺库、损坏库或检索校验异常返回 503 `KB_NOT_READY`，云端向量调用失败返回 503 `UPSTREAM_EMBEDDING_ERROR`。缺库或空目录请求不创建存储目录；零向量查询返回空证据，零分候选被过滤。押金问题仅展示相关条文，并明确提示本章没有押金返还的直接依据。

### 契光排雷：合同审查 API

`POST /api/review/analyze` 接收必填字符串 `contract_text`（长度 10～5000，纯空白拒绝）和整数 `top_k`（默认 4，范围 1～8）。缺字段、越界长度和非法 `top_k` 返回 422。示例：

```json
{
  "contract_text": "租客每月按约支付租金。租客未经房东同意擅自转租房屋。",
  "top_k": 4
}
```

返回 `status`（`success` 或 `mock`）、`results` 和 `total_risks`。每条结果包含 `clause_id`、`original_clause`、`risk_level`（`HIGH` / `MEDIUM` / `LOW` / `NONE`）、`explanation`、`evidence_ids` 和 `negotiation_tip`；`total_risks` 由 Python 统计 HIGH、MEDIUM、LOW 项，NONE 不计入。`evidence_ids` 仅允许 `LAW-703`～`LAW-734`，成功结果的引用还必须属于本次检索提供的法条。

后端在检索和聊天之前复查并遮蔽手机号、身份证号；`original_clause` 按[总规格](docs/specs/spec-00-architecture.md)校验为**后端脱敏文本的精确子串**。输入已脱敏或不含上述敏感信息时，它也必须是请求原文的精确子串；调用方应使用同一脱敏文本定位和高亮，不按未脱敏文本偏移定位。姓名和住址等自由文本仍需人工脱敏。

真实模式使用 `config.py` 的 `CHAT_BASE_URL`、`CHAT_MODEL`、`CHAT_API_KEY` 配置 `ChatOpenAI`，检索使用当前 `CHROMA_PATH` 和向量配置；须先按匹配的向量模式完成 32 条法条入库。审查请求不自动入库，缺库不创建存储目录。Prompt 要求严格依据提供的原始法条和 ID，仅输出 JSON 数组，禁止 Markdown 代码块；服务再次校验结构、原句、引用、敏感数字和唯一条款 ID。校验失败最多重写 2 次、总生成最多 3 次；关闭 SDK 自动重试。`CHAT_TIMEOUT_SECONDS` 控制聊天网络超时，默认 20 秒，允许 1～120 秒；本轮 DeepSeek 默认思考模式以 60 秒配置验证，正常样例聊天耗时约 26 秒。每次服务独立持有和关闭同步 HTTP 客户端，避免复用已关闭的连接。空证据、未就绪/异常知识库、聊天初始化/调用失败或最终校验失败均回退 `mock`。

缺少真实 `CHAT_API_KEY`（包括模板占位值）时直接 HTTP 200 返回固定演示：1 个 HIGH、1 个 NONE，`total_risks=1`，原句从当前脱敏文本截取，`evidence_ids=[]`。此路径不初始化聊天客户端或向量库、不调用任何云 API，即使仅配置了真实向量密钥也一样。**Mock 不是真实风险判断**，正常合同也会出现演示 HIGH；解释明确注明演示和依据不足，不伪造法条引用。涉及押金返还的实质判断仍需补充本章以外的依据。

Day 4 已将起草、Critic 校验和有界重写接入 LangGraph，最多总生成 3 次；图内失败终态为 `needs_review`，保留受控原因并清空未通过的草稿和结果。旧 `/analyze` 将失败适配为 Mock，不返回内部原因或 Trace。Critic 当前检查结构、引用追溯、原句定位和隐私，不代表法律语义依据充分性已验证。两份脱敏合成演练文本位于 `backend/data/scenarios/sample_contracts.json`，不进入法条库，也不替代后续固定工程测试集。

### 详细审查与实际执行记录

`POST /api/review/analyze-detailed` 接收与旧接口相同的输入，返回 `status=success/needs_review`、`results`、`total_risks`、`failure_code`、`reason`、`errors`、`retry_count`、`trace_label` 和 `trace`。成功时结果通过质检、错误字段为空；失败时结果为 `[]`、风险数为0，明确说明缺配置、缺库、无证据、聊天超时或校验失败等原因，不生成 Mock 演示。失败的风险数0表示没有有效结果，不表示合同安全。业务失败仍为 HTTP 200，非法输入仍为422。

Trace 标为“本次执行回放”，包含本次真实执行的节点、生成次数、状态、实测毫秒、法条 ID 和受控反馈。校验失败最多重写两次；最终仍失败保留历次反馈，异常前已完成的记录也保留。准备失败不补造起草或 Critic 节点。历史图节点名 `mock` 在 Trace 中表示失败终止为 `needs_review`，不会让详细版返回演示风险。Trace 不含合同、消息、草稿、原始异常或隐藏思维；当前没有前端回放或实时流式输出。完整字段见 [Spec 02](docs/specs/spec-02-risk-review.md)，离线故障样例见 [回合 2 实测](docs/test-results/day05-round02.md)。

在仓库目录的另一个 PowerShell 窗口运行全量测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
```

`pytest.ini` 将缓存目录设为 `.runtime/pytest_cache`，避开旧的 `.pytest_cache` ACL 问题。`env_configured` 表示配置项已齐全且密钥不是模板占位值，不会联网验证密钥。`.env` 从仓库根目录加载，已有进程环境变量优先；健康 JSON 不返回密钥。单元测试使用合成配置，不调用云 API。首页从相同源请求 `/api/health`，CORS 仅允许本地 `127.0.0.1:8000` 与 `localhost:8000`。

Day 1 在 Python 3.12.13 下验证健康底座，11 项 pytest 通过；[验证记录](docs/test-results/day01-round02.md)保留首次命令问题、复测结果和页面截图。该次仅安装底座相关依赖，未验证全量 RAG 依赖及完整业务复现。

Day 2 回合 2 全量测试为 43 passed，见[向量维度与知识库 API 实测](docs/test-results/day02-round02.md)。2026-10-07 的 Day 3 前置底座加固后，全量测试为 **103 passed in 11.35s**，退出码 0，无失败、跳过或警告；新增覆盖严格向量数值校验、非有限距离、零向量/零分过滤、扩展脱敏、密钥判定、损坏库降级、错误码区分与单客户端检索，见[加固实测报告](docs/test-results/day02-round03-hardening.md)。

Day 3 回合 1 全量结果为 **175 passed in 15.09s**，见[回合 1 报告](docs/test-results/day03-round01.md)；回合 2 增至 **203 passed in 13.31s**，审查模块 **100 passed in 5.59s**，见[回合 2 报告](docs/test-results/day03-round02.md)。均为离线测试，真实聊天调用被拦截。

Day 4 已提交为 `2c007bd`，当时全量 **216 passed, 1 warning in 13.92s**，见[Day 4 实测报告](docs/test-results/day04-round01.md)。Day 5 回合 1 当时全量为 **226 passed, 1 warning in 17.37s**，无失败或跳过；警告为 LangGraph 导入的 `LangChainPendingDeprecationWarning`。该回合真实云调用另行记录，两份审查均返回 `success`，原句、引用范围和计数检查通过，但存在正常样例提示风险及转租授权语义待复核，尚未完成全面内容质量或独立语义 Critic 验证。

Day 5 回合 2 最新全量为 **267 passed, 1 warning in 16.71s**，退出码0，无失败或跳过；新增41项详细接口与 Trace 离线测试。原有云端拦截机制保持不变，本轮没有真实云调用。详细版失败原因与节点记录通过离线故障注入验证，原始测试输出、兼容核对与实际 Trace 样例见 [回合 2 报告](docs/test-results/day05-round02.md)。

常见问题：提示缺少模块时，确认使用仓库的 `.venv`；端口 8000 被占用时，先停止占用该端口的本地服务。占位密钥显示“尚未配置完整”属于正常状态，不影响健康接口。切换 mock 与云端向量或更换模型时应使用不同集合或目录；错误维度的云端向量会在写入前被拒绝。

## 10 分钟极速复现指南（后续补全）

目标从克隆开始计时，包含依赖安装、配置、法条入库、启动和三场景复现；当前未完成全流程计时。法条入库、启动和测试命令见上文；后续补充三场景操作、AI 功能排错和实测耗时。固定 20 例工程测试集为 10 风险、4 正常、3 范围外、3 异常输入，与 20 个演练参考案例严格区分。

## 规格与过程证据

协作按 [AGENTS.md](AGENTS.md) 执行，后续实现以 [总规格](docs/specs/spec-00-architecture.md) 为基准。三条 Prompt 主题链分别记录法条检索与审查、图与 Critic、网页看板的真实 AI 交互和修复过程；本轮按用户指定增加 [Chain-02 风险审查专项记录](docs/prompt-history/chain-02-risk-review/README.md)，保留既有链目录。归档时读取[归档总说明](docs/prompt-history/README.md)。当前索引及过程摘要仍待补完整原始记录，不表示完整对话证据已生成。
