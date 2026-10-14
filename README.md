# 智租博弈（ZhiZu-Agent）

面向青年租房押金扣留、维修责任与提前退租问题的 AI 辅助演练项目。v0.1 已接通“输入 → 脱敏预览 → 契光排雷 → 三场景模拟协商 → 真实执行回放 → 协商清单复制导出”。

2026-10-14：全量离线 **465 passed，0 failed，0 skipped，1 条既有依赖 warning，17.62 秒**（原381项 + 新增84项）；无头 Edge **18组通过、0失败、0跳过**，其中11组同时作为 Day 9 功能补验证据。见 [Day 10 实测](docs/test-results/day10-round01.md) 和 [Day 9 补档补验](docs/test-results/day09-round01.md)。原有测试逻辑未改，外部网络有全局拦截，云端调用与 Token 消耗为0。

谈判 HTTP 默认是明确标注的**固定策略离线演练**：报价按成功轮次推进，不从租客诉求复制条件。合同审查正常运行仍使用配置的云端聊天/向量服务；本轮浏览器通过实际本地 API 和图，审查聊天/检索使用明确的测试替身。真实模型语义质量、固定20例评估和10分钟干净环境复现尚未完成。

## 已有能力与边界

- 浏览器遮蔽手机号、15/18位身份证号，用户编辑并确认预览；后端再次脱敏。定位、高亮使用确认后的脱敏文本。姓名、详细住址由用户人工删改。
- 本地知识库固定《民法典》租赁合同第703～734条共32条，保留正文、来源和核对日期；演练参考案例与权威法条分开。
- 详细审查返回真实节点 Trace 和明确失败出口；旧接口保留演示兼容行为。
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
| `tests/` | 465项离线回归（含全局外网拦截） |
| `docs/specs/` | [规格索引](docs/specs/README.md) |
| `docs/test-results/` | [实测索引](docs/test-results/README.md) |
| `docs/prompt-history/` | [过程证据与待补原始记录](docs/prompt-history/README.md) |

以 [Spec 00](docs/specs/spec-00-architecture.md)、[Spec 02](docs/specs/spec-02-risk-review.md)、[Spec 03](docs/specs/spec-03-negotiation-scoring.md) 和本轮授权新增的 [Spec 04](docs/specs/spec-04-negotiation-api-and-scenarios.md) 为契约。协作边界见 [AGENTS.md](AGENTS.md)。

## Windows PowerShell：运行

在仓库根目录，使用 Python 3.12 和仓库 `.venv`：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 仅在没有 .env 时复制，不覆盖已有凭据
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

本地填写 `.env`；真实 Key 不上传或归档。已验证的 Day 5 组合是 DeepSeek `deepseek-flash` 聊天与硅基流动 `BAAI/bge-m3` 1024维向量，各使用对应平台凭据：

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

```powershell
.\.venv\Scripts\python.exe scripts/init_kb.py --mode cloud --verify-queries
.\.venv\Scripts\python.exe scripts/start.py
```

访问同源 [工作台](http://127.0.0.1:8000/) 与 [Swagger](http://127.0.0.1:8000/docs)。已有进程环境变量优先，改配置后重启。入库与 API 必须使用相同 `CHROMA_PATH` 和向量模式；换模型/维度或 mock/cloud 时用不同目录。离线库可通过 `scripts/init_kb.py --mode mock --persist-dir .runtime/chroma_mock --verify-queries` 初始化，但这不让详细审查自动变为离线成功。健康 `env_configured=true` 只说明配置齐全。

## HTTP 接口

| 方法与路径 | 输入与行为 |
| --- | --- |
| GET `/api/health` | 健康和配置完整性；不验证云端 |
| GET `/api/kb/status` | 本地知识库只读状态 |
| POST `/api/kb/search` | `query`、`top_k`；返回可追溯证据与依据边界 |
| POST `/api/review/analyze-detailed` | `contract_text` 10～5000字、`top_k` 默认4/范围1～8；真实 `success/needs_review`、Trace |
| POST `/api/review/analyze` | 同输入；旧版 `success/mock`，无 Trace；mock不是风险判断 |
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

## 三场景操作与离线复验

网页载入合成合同或粘贴文本 → 打开并编辑脱敏预览 → 确认后排雷 → 点对应风险卡片高亮原句 → 选择场景、填写消息并勾选隐私确认 → 发送并查看正式分数/Trace → 导出清单。切换场景开始新会话；失败保留此前条件；网络失败可重试同一消息。复制导出为 Markdown 文本，不是服务器持久化文件。

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
node scripts/check_day10_frontend.cjs
```

浏览器脚本需要 Node（实测v24.14.0）及默认路径安装的 Edge；脚本自行启动/停止仅本机测试服务、隐藏无头 Edge，并使用隔离浏览器配置。它不使用真实凭据，审查替身经过真实审查图，谈判经过真实图和固定策略；外网被阻断。证据写入 `docs/test-results/day09/` 与 `day10/`，仅 `.runtime/day10-browser/` 保存临时浏览器配置。Windows 受限沙箱若卡在 asyncio `socketpair/accept`，需允许本机回环后复验，不能将中断写为通过。

唯一测试警告为 LangGraph 导入的 `LangChainPendingDeprecationWarning`。Day 5 的真实云端小规模验证及已知语义问题另见 [真实联调](docs/test-results/day05-round01.md)、[详细失败出口](docs/test-results/day05-round02.md)、[已知问题](docs/known-issues.md)。Day 11固定20例、Day 12效果对比和从克隆开始的10分钟计时仍待执行；当前没有这些指标的实测结论。
