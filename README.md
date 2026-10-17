# 智租博弈（ZhiZu-Agent）

面向青年租房押金扣留、维修责任与提前退租问题的 AI 辅助演练项目。v0.1 已接通“输入 → 脱敏预览 → 契光排雷 → 三场景模拟协商 → 真实执行回放 → 协商清单复制导出”。

Day 11 固定20例真实 API 自动评估已完成：**20/20 通过**（10 风险、4 正常、3 范围外、3 异常输入），见 [Day 11 报告](docs/test-results/day11-eval-report.md)。14例有效租约实际调用聊天与向量服务；3例范围外、2例长异常在输入护栏拒绝，1例过短输入在字段校验拒绝，这6例均无已观测云请求、Token 为0。该结果只代表报告公开的 API 规则通过，不等于法律准确率或完整安全认证。

谈判 HTTP 默认是明确标注的**固定策略离线演练**：报价按成功轮次推进，不从租客诉求复制条件；合同审查正常运行使用配置的云端聊天/向量服务。Day 10 无头 Edge 的18组闭环验证使用真实本地 API 与图、明确标注的审查替身，见 [浏览器实测](docs/test-results/day10-round01.md)。本页提供从克隆开始的完整复现步骤；全新机器安装与10分钟计时复现仍待独立执行，不能据此宣称已完成净室实测。

## 已有能力与边界

- 浏览器遮蔽手机号、15/18位身份证号，用户编辑并确认预览；后端再次脱敏。定位、高亮使用确认后的脱敏文本。姓名、详细住址由用户人工删改。
- 本地知识库固定《民法典》租赁合同第703～734条共32条，保留正文、来源和核对日期；演练参考案例与权威法条分开。
- 两个审查入口均在检索和云调用前执行确定性输入护栏；详细接口返回真实节点 Trace 和明确失败出口，旧接口保留 `success/mock` 兼容格式，拦截时回退明确标注的 Mock 演示结果。
- 三场景候选提取、Critic、纯 Python 算分；最多5轮，最多2次重写，失败不提交，同状态同分，重复请求不重复提交。
- Trace 只记录实际执行节点及实测耗时、受控反馈；完整响应后回放。缓存与历史回放单独标注，不展示隐藏思维。
- 清单只导出通过质检的正式条件，分列未解决诉求和待补事实；自动复制被拒时提供手动复制文本。
- 会话使用单进程内存和独立锁，重启清空。暂无账号、长期历史、OCR或复杂文书。

## 目录与契约

| 路径 | 用途 |
| --- | --- |
| `backend/app/api/` | 健康、知识库、合同审查、唯一谈判提交接口 |
| `backend/app/schemas/` | 请求、正式状态、公开响应与 Trace |
| `backend/app/services/` | RAG、双图、Critic、规则算分、会话服务 |
| `backend/app/core/` | 配置与严格 PII 脱敏 |
| `backend/data/laws/` | 32条权威法条 |
| `backend/data/scenarios/` | 合成演练文本；不作为法条依据 |
| `frontend-web/index.html` | 无构建工具 Vue 3 三栏工作台 |
| `frontend-web/vendor/` | 固定版本 Vue/Tailwind 与许可证 |
| `scripts/` | 启动、入库、离线浏览器验收 |
| `tests/` | 离线回归（含全局外网拦截） |
| `docs/specs/` | [规格索引](docs/specs/README.md) |
| `docs/test-results/` | [实测索引](docs/test-results/README.md) |
| `docs/prompt-history/` | [过程证据与待补原始记录](docs/prompt-history/README.md) |

以 [Spec 00](docs/specs/spec-00-architecture.md)、[Spec 02](docs/specs/spec-02-risk-review.md)、[Spec 03](docs/specs/spec-03-negotiation-scoring.md) 和 [Spec 04](docs/specs/spec-04-negotiation-api-and-scenarios.md) 为契约。Day 12 根据安全审查将既有护栏扩展到旧入口，同时保留旧响应格式；原 Spec 的 Day 11 护栏范围描述属于当时的接口范围。协作边界见 [AGENTS.md](AGENTS.md)，答辩对比见 [核心技术亮点](docs/technical-highlights.md)。

## 从零复现：Windows PowerShell

准备 Git、Python **3.12**（含 Windows `py` 启动器）和浏览器；安装依赖、首次入库及真实合同审查需要网络。完整审查需分别准备 DeepSeek 聊天 Key 与硅基流动向量 Key，并保证两家服务可用及额度足够。前端资源已随仓库提供，运行工作台无需 Node、npm、Docker 或独立 ChromaDB 服务。

### 1. 克隆与安装环境

在打算存放项目的目录打开 PowerShell，逐段执行；每步成功后再继续：

```powershell
git clone https://github.com/wz2626/ZhiZu-Agent.git
Set-Location ZhiZu-Agent
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe --version
```

两次版本检查应显示 `Python 3.12.x`。后续都直接调用虚拟环境解释器，无需激活脚本或修改 PowerShell 执行策略。若 `py -3.12` 提示未安装，先安装 Python 3.12并重新打开终端；若已经安装但未登记到启动器，可用其真实路径执行 `& 'C:\实际安装目录\python.exe' -m venv .venv`，不要把示例路径原样运行。仓库未锁定所有间接依赖，真实评估采用的具体包版本见 Day 11 报告。

### 2. 配置 `.env`

```powershell
# 仅在没有 .env 时复制，不覆盖已有凭据
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
notepad .env
```

在打开的文件中填写下列配置并保存。项目已验证的组合为 DeepSeek 官方 `deepseek-flash` 聊天与硅基流动 `BAAI/bge-m3` **1024维**向量；两个 Key 来自不同平台，不能互换。`your_...` 占位值不能用于运行：

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

`.env`、真实 Key 和本地 Chroma 数据不提交。已有进程环境变量优先于 `.env`；若修改后仍读到旧值，检查启动终端的同名环境变量并重启后端。聊天超时范围为1～120秒，模板使用60秒；它是单次网络超时，包含重写的完整请求可能更久。

### 3. 初始化本地 ChromaDB 知识库

保持当前目录为仓库根目录，执行：

```powershell
.\.venv\Scripts\python.exe scripts/init_kb.py --mode cloud --verify-queries
```

此命令通过云端向量 API 将固定32条《民法典》租赁法条写入本地 `./.runtime/chroma_cloud`，随后执行5条检索核验，会产生向量 API 用量。首行 JSON 应显示 `loaded_articles=32`、`inserted_count=32`、`total_count=32`；重复入库应为 `inserted_count=0`、`updated_count=32`、总数仍为32。后续行应列出核验问题及召回条号/来源。先确保命令成功，再启动后端。

入库和 API 必须从同一仓库根目录运行，并使用相同的 `CHROMA_PATH`、向量模型、维度和模式。更换模型/维度或在 mock/cloud 间切换时使用独立目录并重新入库，不要覆盖混用原库。ChromaDB 是进程内的本地持久化库，不需要另开数据库端口。

### 4. 启动 FastAPI 与同源前端

```powershell
.\.venv\Scripts\python.exe scripts/start.py
```

看到 `Uvicorn running on http://127.0.0.1:8000` 后保留此窗口运行。用浏览器打开 [工作台](http://127.0.0.1:8000/)；[Swagger](http://127.0.0.1:8000/docs) 可查看接口。首页和 `/vendor` 静态资源由同一个 FastAPI 服务提供，请通过上述地址进入。

可另开一个 PowerShell 窗口做启动检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/kb/status
Start-Process 'http://127.0.0.1:8000/'
```

健康应为 `status=ok`、`env_configured=true`；知识库应为 `indexed_count=32`、`is_ready=true`、`embedding_mode=cloud`。健康只核对配置是否齐全，知识库状态只核对本地集合，不验证云端 Key、余额或可达性；实际审查成功才证明该次云端链路可用。按 `Ctrl+C` 停止后端，改 `.env` 后重启。

### 5. 体验三场景闭环

1. 在首页点击“试用合成合同”，或粘贴自己的租约。点击“分析合同 · 先预览脱敏”，核对手机号/身份证遮蔽，并人工删改姓名、详细住址等信息；勾选确认后点击“确认并提交分析”。
2. 等待真实审查完整返回，查看风险等级、解释、法条；点风险卡片可在左侧定位原句，下方“本次执行回放”展示实际节点。若显示“本次审查未完成”，按失败原因修复后重试，不能把空结果当成无风险。
3. 在右侧选择“押金扣留”，输入下表消息并勾选消息隐私确认，点击“发送给模拟房东”。连续发送3条新消息观察50→75→100分；每次都需重新确认消息隐私。切换角色标签查看已通过质检的回应，并在“已确认条件”核对正式状态。
4. 点击“导出协商清单”，复制 Markdown；若浏览器拒绝剪贴板，使用页面提供的文本框手动复制。清单分列已确认条件、未解决诉求和待补事实。
5. 切换“维修责任”“提前退租”，分别重复发送与导出；切换场景会开始新会话并清空本页上一场景清单，先保存需要的内容。也可重新编辑该场景合同，再执行审查→演练→导出。

| 场景 | 可直接输入的首轮消息 | 第1/2/3轮确认条件 | 第1/2/3轮进展分 |
| --- | --- | --- | --- |
| 押金扣留 | 请核对扣减凭证，并明确可以返还的押金金额。 | 返还1000 / 1500 / 2000元 | 50 / 75 / 100 |
| 维修责任 | 请确认由谁承担维修费用，以及承担的比例。 | 房东承担50 / 75 / 100% | 50 / 75 / 100 |
| 提前退租 | 请结合交接安排，明确可协商的提前退租违约金。 | 违约金1000 / 500 / 0元 | 50 / 75 / 100 |

后续消息可用“请进一步明确可接受的条件”“请确认最终协商条件”。固定策略按成功轮次推进，报价与消息措辞无关；第4/5轮保持第3轮条件和分数，单会话最多5轮。以上是演练参数，不是法律判定、真实房东接受概率或大模型谈判能力测评。合同审查使用云服务，谈判演练本身不调用云端。

### 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| `git` / `py` 不存在，或找不到 Python 3.12 | 安装 Git 与 Python 3.12（含启动器）后重开 PowerShell，先通过版本检查再创建虚拟环境。 |
| `No module named ...` / 依赖安装失败 | 在仓库根目录用 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`；确认未误用系统 Python，并检查安装输出与网络。 |
| 入库报无有效密钥、401/403或超时 | 检查两家平台分别对应的配置、权限、额度和网络；占位 Key 无效。仅入库使用向量 Key，审查还需要聊天 Key。 |
| 知识库 `is_ready=false`、`KB_NOT_READY` 或模型/维度不一致 | 确认运行目录、`CHROMA_PATH`、向量模型/模式一致，在独立目录按第3步重新入库；不要把 mock 库用于 cloud 检索。 |
| `env_configured=false` / `CHAT_NOT_CONFIGURED` | 保存 `.env` 的真实配置，检查终端环境变量是否覆盖后重启；健康检查不测试真实凭据。 |
| 端口8000占用 | 关闭自己此前启动的服务，再运行 `scripts/start.py`；已有服务可先用健康接口核对项目。 |
| 审查 `needs_review` | 查看受控原因与实际 Trace：护栏拒绝需换成有效租赁条款；云端/质检失败按提示重试。HTTP 200不等于审查成功。 |
| 首页空白或功能未发现 | 确认通过 `http://127.0.0.1:8000/` 打开、启用 JavaScript、`frontend-web/vendor/` 完整且 `/openapi.json` 可访问。 |

无 Key 时也可启动网页、使用固定策略谈判、验证确定性护栏和离线测试；**不能完成真实合同审查闭环**。如只验证本地入库，可运行以下命令创建隔离 mock 库；该命令不改变 API 当前配置，也不让详细审查自动返回离线成功：

```powershell
.\.venv\Scripts\python.exe scripts/init_kb.py --mode mock --persist-dir .runtime/chroma_mock --verify-queries
```

## HTTP 接口

| 方法与路径 | 输入与行为 |
| --- | --- |
| GET `/api/health` | 健康和配置完整性；不验证云端 |
| GET `/api/kb/status` | 本地知识库只读状态 |
| POST `/api/kb/search` | `query`、`top_k`；返回可追溯证据与依据边界 |
| POST `/api/review/analyze-detailed` | `contract_text` 10～5000字、`top_k` 默认4/范围1～8；真实 `success/needs_review`、Trace |
| POST `/api/review/analyze` | 同输入、同前置护栏；旧版 `success/mock`，无 Trace；拒绝时直接返回 Mock 演示结果，不是真实风险判断 |
| POST `/api/negotiation/turn` | 唯一谈判提交接口，自动由网页读取 `/openapi.json` 发现 |

谈判请求：

```json
{
  "session_id": "demo-deposit",
  "user_input": "请核对扣减凭证并明确返还金额。",
  "request_id": "turn-1",
  "scenario": "deposit"
}
```

前三个字段必填严格字符串，标识1～64个 ASCII 字母、数字、下划线或横杠且不能含敏感号码；消息1～2000字、非纯空白。额外状态/规则/引用字段拒绝。场景默认为 `deposit`，另支持 `maintenance`（兼容 `repair`）和 `early_termination`（兼容 `termination`）。

正式分数名为 `trial_score`（不是候选分数）。公开响应包含确认条件、轮次、`success/completed/needs_review`、Critic 反馈、实际 Trace、未解决诉求及待补事实。非法输入422且不回显 input；同会话换场景或同编号换消息409；业务失败200且正式状态不变。重试相同编号/脱敏消息返回缓存并标记 `replayed=true`，不再次提交；已缓存失败需新编号才能重新执行。第6次请求不执行图，返回5轮当前条件和空 Trace。

| 场景 | 预设第1/2/3轮确认值 | 第1/2/3轮模拟协商进展分 |
| --- | --- | --- |
| 押金 | 返还1000 / 1500 / 2000元，目标2000元 | 50 / 75 / 100 |
| 维修 | 房东承担50 / 75 / 100%，目标100% | 50 / 75 / 100 |
| 提前退租 | 违约金1000 / 500 / 0元，起点2000元、目标0元 | 50 / 75 / 100 |

第4/5轮保持第3轮条件和分数。以上是演练参数，不是法律判定。模型/替身只提取和解释，最终分数由规则按完整确认状态重算；`target == start` 排除该项，无适用项为不可评分。默认谈判不引用法条，可信证据集合为空；不能用客户端提交的法条冒充本次已核验引用。

详细接口护栏拒绝时返回 `needs_review`、空结果、`OUT_OF_SCOPE` 或 `INVALID_CONTRACT_TEXT`，Trace 只有实际执行的 `input_guard`。旧接口护栏拒绝时保留 `mock` 兼容形状及原有演示条目与计数，文案明确标注 Mock、非真实法律审查结论；没有拒绝码或 Trace，新调用方应使用详细接口。两者都在聊天客户端初始化、检索与云调用前停止。护栏只拦截高置信范围外或无有效合同内容的输入，模糊文本及含真实租约内容的混合文本仍进入后续审查，不是所有恶意输入的通用分类器。

## 离线复验与证据范围

在仓库根目录执行单元/接口回归；此套件全局阻断外部网络，外部服务使用测试替身，不消耗云端 Token：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
```

可选浏览器验收需要 Node（已记录实测版本v24.14.0）及默认路径安装的 Edge，日常运行工作台不需要。以下脚本自行启动/停止仅本机测试服务、隐藏无头 Edge，外网被阻断；审查替身经过真实审查图，谈判经过真实图和固定策略。脚本会写入并更新 `docs/test-results/day09/`、`day10/` 的证据，临时浏览器配置写入 `.runtime/day10-browser/`；保留历史证据前请在独立复现副本执行：

```powershell
node scripts/check_day10_frontend.cjs
```

Day 12（2026-10-17）本轮全量离线回归：**652 passed、0 failed、0 skipped，1条既有依赖 warning，21.04秒**，较 Day 11 的631项增加21项；审查相关定向回归234 passed。新增覆盖旧入口的下游禁止调用、双端点脱敏/422及真实租约、模糊/混合文本放行。全量命令使用独立临时目录 `--basetemp=.runtime/pytest_day12_full`；真实云评估与离线回归是不同证据，不相加计算通过率。

本轮另在现有虚拟环境、清空双 API Key 的隔离 mock 库上实跑入库与 `scripts/start.py`：32条入库、5条检索、重复入库总数仍为32；首页、vendor、Swagger、OpenAPI、健康与库状态可访问；三场景真实本地 HTTP 各3轮均为50→75→100分，两个审查入口均按各自兼容格式拒绝范围外文本，核验后已停止服务。这不是全新环境安装、真实云端审查或本轮浏览器界面验收。

Windows 受限沙箱若卡在 asyncio `socketpair/accept`，需允许本机回环后复验，不能将中断写为通过。本轮首次沙箱执行也卡在该位置，中止后在允许本机回环、测试仍禁止外网的环境重跑，得到上述完成结果。

已记录的依赖警告为 LangGraph 导入的 `LangChainPendingDeprecationWarning`。真实云端报告见 [Day 5 联调](docs/test-results/day05-round01.md)、[Day 11 固定20例](docs/test-results/day11-eval-report.md)；故障/Trace 验证见 [详细失败出口](docs/test-results/day05-round02.md)。合同解释是否被法条实质支持、完整误报/漏报及 [已知语义问题](docs/known-issues.md) 仍需人工逐例复核；Day 11 的规则通过不能自动关闭这些问题。Day 12 效果对比和从全新克隆开始的10分钟计时尚无实测结论，本轮文档核对不冒充这些验证。
