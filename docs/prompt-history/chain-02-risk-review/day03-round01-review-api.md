# Day 3 回合 1：契光排雷服务与 API 构建过程

日期：2026-10-07（北京时间）。本文为本次可见任务、代码和实际工具输出的过程摘要，**不是完整原始对话导出**。工具为 Codex，模型名称未确认；本轮 Commit 待提交。

## 用户目标、约束与基线

用户要求先分析安排是否合理，再完成六组工作：风险 Schema；法条检索串联聊天模型并提供 Mock 降级；`POST /api/review/analyze`；两份脱敏租房演练参考；API/服务测试和全量回归；本专项索引、过程摘要、根 README 与测试报告。完成后清理本轮测试临时目录，执行带 `--no-optional-locks` 的 Git 状态检查。

红线为仅使用 `.\.venv\Scripts\python.exe`、pytest 固定 `--basetemp=.runtime/pytest_tmp`、不改 `requirements.txt`、不做 Git 写操作、No-Markdown 结构化 JSON 输出、无真实聊天 Key 时必须直接安全 Mock。测试均为离线模拟。

编码前读取项目 `AGENTS.md`、[总 Spec](../../specs/spec-00-architecture.md)、[知识库 Spec](../../specs/spec-01-rag-kb.md)及现有配置、服务、路由和测试。只读核实本地 HEAD 为 `45931c6`（用户所述 Commit #5），初始 `git --no-optional-locks status --short` 为空；安装环境已有 `ChatOpenAI`，未安装或升级依赖。Spec 基线为该 HEAD 下的现有文件，未修改规格。

## 提前提出的契约差异与实现口径

- 任务按 Schema → 服务 → API → 测试/归档推进合理；同时指出需由服务校验原句和引用，而不能只靠 Prompt。
- 总 Spec 的完整图失败出口为 `needs_review`，本轮用户明确要求核心服务响应 `success/mock`。本轮按该显式请求实现，最终校验失败为 `mock`，完整 LangGraph Critic 图及其状态出口仍待后续开发。
- 总 Spec 按脱敏文本定位，本轮要求原文精确子串。服务在检索、聊天和定位前二次脱敏，返回脱敏文本精确子串；已脱敏的请求与无敏感信息请求同时满足请求原文的子串要求。未将原始敏感数字映射回响应。
- 32 条租赁法条没有押金返还的直接依据。Prompt 明确范围边界，Mock 不伪造法律引用，正常文本也会得到固定 HIGH 演示项，因此不能当作实质审查结果。

以上按本次实际 commentary 记录；未收到额外确认或独立审查原件，不补造确认对话。

## 实际服务链路

1. `schemas/review.py` 定义 HIGH、MEDIUM、LOW、NONE，输入长度 10～5000、整数 top_k 1～8，以及条款结果和 `success/mock` 响应。风险项要求解释/建议，NONE 可为空；证据 ID 限于 LAW-703～LAW-734；总风险数按非 NONE 项核对。
2. `services/review.py` 使用现有 `has_real_key` 和 `config.py` 配置。没有真实聊天 Key 时跳过客户端、Chroma 和向量检索，直接从当前脱敏文本取演示片段，固定 HIGH + NONE、总数 1、空引用。即使向量 Key 存在也不访问云端。
3. 真实模式持有 `ChatOpenAI`，向量库按需以 `create_if_missing=False` 打开，并核查就绪状态；检索传递 top_k。过滤非数值/bool/非有限/零/负/超界分数、未知 ID、正文不匹配及重复候选；保留小正分。正文再次与固定权威 JSON 核对，场景文件不参与检索。
4. 使用独立系统消息和 JSON 编码的合同/法条数据消息。实际系统 Prompt 明确严苛法务角色、只按给定原文与 ID、忽略数据内的指令、仅 JSON 数组、禁止 Markdown、原句连续精确复制、风险枚举、依据不足及押金边界。未使用 JSON object 模式冒充数组输出。
5. `json.loads` 和 Pydantic 校验完整数组，再核验唯一条款 ID、脱敏原句定位、引用属于本次证据、输出中不出现未脱敏手机号/身份证号。仅校验失败时递增 retry_count，最多两次重写/三次生成，不回传原始坏输出或异常详情。SDK 自动重试设为 0，聊天超时 20 秒。
6. 缺库、未就绪、空证据、检索失败、聊天初始化/调用失败、最终校验失败均降级 `mock`；日志只保留异常类型。请求结束关闭服务自有资源，注入对象由调用方管理；资源关闭失败也不覆盖正常响应。
7. 路由接收 Schema 并调用核心方法，在 `main.py` 使用 `/api/review` 前缀注册。两份合成脱敏文本与演练用途说明写入 `backend/data/scenarios/sample_contracts.json`，没有法条索引或固定工程测试集的身份。

适配参数还核对了本地已安装类签名和 [LangChain 官方 ChatOpenAI 参考](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI)。未据此宣称实际 SiliconFlow 连接验证成功。

## 实际测试过程与结果

- 首次针对性测试在第一个 TestClient fixture 阻塞，无结果，手动终止，退出码 1。随后同一测试加 `-o faulthandler_timeout=20` 诊断；20 秒栈显示 asyncio 创建本地 socketpair 时停在 `_fallback_socketpair` 的 `accept`，尚未执行审查逻辑，再次终止，退出码 1。不能把两次未完成运行计为通过。
- 受控提升权限运行同一离线测试后，**71 passed in 4.28s**。未修改测试来规避 TestClient，也未改现有底座逻辑或切换 Python。
- 补充资源关闭异常容错及其测试后，针对性复测 **72 passed in 3.31s**。
- 指定命令全量实际结果 **175 passed in 15.09s**，退出码 0，包含原有 103 项和新增 72 项，无失败、跳过或警告。细节及清理记录见[本轮实测报告](../../test-results/day03-round01.md)。

坏 JSON、代码块、伪造原句/引用、敏感输出、坏分数与上游/资源关闭异常均为**故障注入**，没有把人工问题写成真实云服务事故。真实本地 Chroma + 模拟聊天的完整 API 链路已验证；真实云服务连接、模型法律语义判断与完整图仍未验证。

## 归档边界

本次新增指定 `chain-02-risk-review` 目录，并在归档入口说明与既有 `chain-02-graph-critic` 的关系，不替换原目录。待补完整原始聊天及模型信息；本摘要和测试输出不能替代原始多轮记录。所有 Git 操作均只读，没有创建 Commit。
