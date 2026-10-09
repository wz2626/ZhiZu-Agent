# Day 4 回合 1：Critic 审查图过程摘要

日期：2026-10-09（北京时间）。基线 `fe688c3`，本轮待提交。本文为实际工作摘要，**待补原始记录**；测试中的错误输出均为故障注入，不是云端模型实际返回。

## 用户目标与约束

在 Day 3 的 203 项通过基础上引入 LangGraph，定义 `ReviewState`、起草和 Critic 节点、条件边及编译的 `review_graph`；将核心服务切换为 `review_graph.invoke()`，保留检索前置步骤及 API 格式。安装依赖，适配测试，归档过程，清理临时目录并只读检查 Git。

所有 Python、pip、pytest 使用 `.\.venv\Scripts\python.exe`。不执行 Git 写操作；遵守 spec-00 的脱敏定位、可追溯引用和最多三次生成契约。

## 事前分析与处理

任务分解合理，但图终态与已有响应状态存在接口口径差异。编码前说明：图失败保留 `needs_review` 与安全失败原因，由服务转为原有 `mock` 响应；不为适配修改 Spec 或 Schema。

仓库依赖表已包含 LangGraph，环境版本为 0.6.11。执行指定安装命令后显示已满足；为本轮使用的 Runtime context API，将现有依赖项更新为 `langgraph>=0.6.11,<0.7.0`，不重复追加、不跨系列升级。

编码前也说明无引用 HIGH 的重试行为变化：和其他 Critic 失败统一最多重写两次，始终不能携带无依据 HIGH 作为正式结果。对应四项原有测试由一次直接 Mock 调整为三次后 Mock，另增修正引用后成功测试。

## 实际实现

1. `graph.py` 定义合同文本、证据、当前原始 JSON 草稿、校验错误、重试次数、最终结果及状态；额外保存消息与是否待重写。服务以每次请求独立的 Runtime context 提供 ChatOpenAI 或测试客户端，不把客户端或凭证放入状态，不配置持久化 checkpoint。
2. `drafting_node` 复用原系统 Prompt，调用客户端 `invoke`；重写消息包含具体安全错误。保留 temperature=0.1、timeout=20、SDK max_retries=0 的客户端配置和既有资源释放逻辑。
3. `critic_node` 接管既有 JSON 校验、完整围栏清洗、非有限常量和重复键拒绝、Pydantic Schema 校验、条款编号唯一、脱敏原句连续子串定位、敏感数字检查、召回引用交集及保序去重。无可用引用的 HIGH 必须失败。
4. 失败仅在 `retry_count < 2` 时递增并重写；校验通过才填充 `final_results`。第三次校验失败或聊天调用异常走降级节点，最终 `needs_review` 保留安全原因、清空未通过草稿和正式结果。服务据此生成原有 Mock 演示响应。
5. 保留 `search_evidence`、权威正文和正分数过滤作为图执行前置步骤；模型调用仍可通过 `langchain_openai.ChatOpenAI.invoke` 拦截。新增 graph.invoke 入口验证及实际 graph.stream 节点路径验证。

图编排采用官方 [StateGraph API](https://reference.langchain.com/python/langgraph/graph/state/StateGraph) 的编译与条件边机制；实际行为以本地安装的 0.6.11 和本轮离线测试为准。

## 实际验证与修正

审查模块 **113 passed, 1 warning in 4.07s**；全量 **216 passed, 1 warning in 13.92s**，新增 13 项，均退出码 0，无失败或跳过。

首个受限 pytest 在首个 TestClient 用例无输出阻塞，中断后相同命令在受控提升权限下通过，与历史 Windows 沙箱本地 socketpair 问题表现一致；未取得底层调用栈，不将一致表现写成已确认根因。未发生代码测试断言失败。

首次 pip 出现沙箱系统临时目录清理警告；将进程 TEMP/TMP 设为仓库 `.runtime/pip_tmp` 后重跑，退出码 0。清理时首次脚本的 `Split-Path -LiteralPath ... -Parent` 参数组合不兼容，已中断并改为 .NET 路径父目录解析；核验绝对路径及重解析点后完成本轮三个仓库临时目录清理。

完整命令、测试覆盖、warning 和工作区结果见[本轮测试报告](../../test-results/day04-round01.md)。Git 只读核验基线、diff 与 status，本轮不预填提交哈希。

## 实现边界

Critic 为确定性结构、定位、引用和隐私校验；反思体现为具体错误反馈驱动下一次起草。引用在召回集合中不等于解释已获得法律语义支持，独立语义 Critic、真实云端效果及前端回放未在本轮实现或验证。未伪造节点 trace、隐藏思维或完整原始对话。
