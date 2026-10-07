# Chain-02：契光排雷核心服务专项

## 范围与归档状态

按用户指定目录归档 Day 3 合同审查迭代：回合 1 的 Schema、RAG + LLM 核心服务、API、演练参考文本，以及回合 2 的真实客户端调用路径、Prompt、严格 JSON 清洗解析、引用过滤和离线拦截测试。既有 `chain-02-graph-critic` 不变，本专项不宣称完整审查图或语义 Critic 已实现。

当前状态：**待补原始记录**。[回合 1 摘要](day03-round01-review-api.md)和[回合 2 摘要](day03-round02-real-llm.md)依据实际可见任务、实现及测试编写，不是原始多轮对话导出；遵循[归档总说明](../README.md)。

## 迭代索引

| 迭代 | 时间（北京时间） | 工具/模型 | 意图与结果 | 原始记录 | 测试证据 | 关联代码 Commit |
| --- | --- | --- | --- | --- | --- | --- |
| I01：Day 3 回合 1 | 2026-10-07 | Codex；模型未确认 | 核心审查链路与安全 Mock；新增 72 项，Day 1/2/3 全量 175 项通过 | 待补原始记录；[过程摘要](day03-round01-review-api.md) | [回合 1 实测](../../test-results/day03-round01.md) | `a774f2b`（Commit #6，本地只读核实；基线 `45931c6`） |
| I02：Day 3 回合 2 | 2026-10-07 | Codex；模型未确认 | temperature=0.1、严格 JSON 与防幻觉引用过滤；新增 28 项实际 ChatOpenAI.invoke 拦截用例；全量 203 项通过 | 待补原始记录；[过程摘要](day03-round02-real-llm.md) | [回合 2 实测](../../test-results/day03-round02.md) | 待提交；基线 `a774f2b`（Commit #6） |

## 关键迭代

I01 的目标、Spec 差异、真实运行阻塞及诊断、针对性复测和全量结果见[过程摘要](day03-round01-review-api.md)及[测试报告](../../test-results/day03-round01.md)。本次未执行任何 Git 写操作，不预填本轮提交哈希。

I02 在真实客户端构造路径上拦截 `langchain_openai.ChatOpenAI.invoke`，不消耗云端 Token；严格保留脱敏原句定位和总生成 3 次上限，未召回引用被剔除，无可用引用的 HIGH 项直接返回演示 Mock。针对性 100 项、全量 203 项通过，见[过程摘要](day03-round02-real-llm.md)与[测试报告](../../test-results/day03-round02.md)。未验证真实 SiliconFlow 连通性和模型语义效果。

## 待补材料

两轮完整原始聊天导出或连续截图/录屏、可核实的模型名称和消息位置；回合 2 提交后由开发者提供或 Agent 只读核实实际哈希。尚未提供独立审查或真实云端集成记录。
