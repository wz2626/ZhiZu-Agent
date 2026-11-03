# V4 后端架构重构验收

附件精简（2026-11-01，开发者要求）：重复截图、中间对比图及旧机器验收附件已移出待提交目录，保存在本机忽略归档 `.runtime/evidence-tidy-20261101.zip`；下文历史实测结论保留，附件数不代表当前保留数。


2026-10-31，按开发者授权执行修订后的 A0 → A → B → C → D1 → E。同步修改 Spec 00/02/04/05；没有 Git 写操作，没有覆盖前一阶段工作或历史验收目录。

## 裁决与最终行为

- 默认严格端点头矩阵：谈判要求版本/实例/轮次三头；草稿、详细审查仅版本头；meta 无头。旧无头协议由 V4_ALLOW_LEGACY_HEADERS=true 显式开启，历史 HTTP 回归也明确运行在该兼容配置；新增测试验证生产默认严格。部分练习头不能自动降级。
- 固定谈判保留同步会话锁。practice_policy.py 集中固定报价、模板及最终档次，原函数名兼容导出。服务复核冻结规则、证据、确认文本、条件、分数和历史；完整公开响应构造、校验、序列化预检通过后才一次发布正式状态与回执。注入响应构造失败时，状态和缓存均不变；缓存重放使用原公开响应。
- get_session 对未知 ID 返回不落存储的空快照，原测试保留。新会话的错误预期轮次不留下空会话。会话有 TTL、容量、操作预算与实例内身份墓碑；过期 ID 不静默复活。内存模式拒绝标准多进程/多 Worker 配置，不增加共享存储。
- 草稿按上下文+请求编号单飞，指纹仅比较内容。短锁内准入/预留，锁外调用模型，完成后原子发布已校验响应与问题账本。同号不再重复调用，同上下文不同操作可以并行。问题账本与响应条目分离；questions/question_items 必须完全对齐，既有2000字预算与归属校验保留。
- 合同上下文保持30分钟有效；已受理操作的回执独立保留至受理后60分钟。恢复先查回执，新操作仍需有效上下文。在途上下文有 pin，不能被容量淘汰。已过恢复窗的编号不会因输入上下文仍在而再次执行。
- D1 只改变云链路 HTTP 调度，保留同步模型 SDK/图；异步 SDK 迁移未纳入本轮。独立执行器4个执行、最多4个排队、排队上限2秒、操作总期限90秒。HTTP 取消不取消后台任务；超过服务端期限不发布，实际线程退出前不释放执行容量。确定 needs_review 继续缓存；HTTP 等待失败或临时繁忙不制造业务失败回执。模型供应商调用异常沿用明确的受控终止出口，不自动再次调用供应商。
- 入站实际读取上限256KiB、JSON 深度32/节点8192，拒绝重复键和非有限数。全局422不回显原文/异常上下文，未知字段名也不反射；未处理异常在API边界收口，防止框架安全响应后继续向服务器日志重抛原始异常。API no-store，CORS 支持 V4 头。公开审查输出限制数量及解释长度，模型输出总长、输入预算、max_tokens 和聊天/向量响应流字节均有限制；出口文本检查不把不透明问题 ID 当作个人号码。
- V4统一安全文本 ***，旧 analyze 保留 typed placeholder 适配。隐私检测副本折叠Unicode十进制数字、指定零宽/格式字符、特殊空格与全角X，并以索引映射回原文码点；增加18位证件分段保护。前端算法、元信息版本和黄金语料同步升级。没有把所有长业务编号改成隐私，也不宣称姓名、地址全面自动识别。
- 保留428完整安全预览，回答增加 question_id。428不受理/缓存编号、不创建会话或Trace。前端针对 OPERATION_EXPIRED 只提示明确重新生成，保留目标/回答和有效上下文；不将其误报为合同上下文过期。

新增主要模块：schemas/interaction.py、core/http_limits.py、services/operation_store.py、services/model_gateway.py、services/practice_policy.py。主要服务改动落在 proposal.py、review_context.py、negotiation_service.py、negotiation_graph.py、review.py、graph.py、embedding.py、vector_store.py。没有引入授权令牌、第二套幂等键、claim_flags、草稿状态版本或跨重启恢复。

## 实际验证

| 检查 | A0 基线 | 最终结果 |
| --- | --- | --- |
| 全量离线 pytest | 781 passed，23.72秒 | **811 passed，0 failed/skipped，21.77秒** |
| Day8 浏览器 | 13组通过 | **13组通过** |
| Day10 浏览器 | 40组通过 | **41组通过** |
| 视觉/空间 | 4组通过 | **4组通过，15张截图** |

pytest 仍只有一条既有 LangChainPendingDeprecationWarning。浏览器外部请求为0；审查、参考稿使用明确离线替身，谈判使用真实固定图及本机HTTP。已查看最终视觉联系表。附 pytest输出（附件已移至本机归档）、Day8（附件已移至本机归档）、Day10（附件已移至本机归档）、视觉结果（附件已移至本机归档）、联系表（附件已移至本机归档）。

新增30项 Python 回归包含：端点头矩阵、流式请求限制、重复键/非有限数/深度、错误字段名与未处理异常日志隐私、八线程同号/不同号基线、完整响应失败零提交、伪造图拒绝、会话容量与过期身份、锁外并行、上下文 pin/TTL 后恢复、超期结果禁止发布、公开问题对齐、HTTP取消与真实工作容量、响应流上限/关闭及结构化ID消歧。新增浏览器检查明确注入 OPERATION_EXPIRED，然后用原有效上下文和新编号生成，验证已有输入保留。

中间失败均保留于本机忽略目录，不冒充最终通过：首次 A0 临时目录父路径缺失；一次错误测试文件路径未收集；新测试参数默认ID过长；占位符、max_tokens及回执TTL的断言按授权契约迁移；保留合法未计分安排的提交检查曾过严；严格矩阵测试最初未显式关闭环境云配置导致 TestClient 退出错误，补齐离线配置后全量重跑通过。原断言没有通过删除或放宽来规避，协议变化对应的精确期望已迁移。

## 命令与边界

以下命令在仓库根目录实际完成；再次运行请更换独立输出目录。

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/v4-backend-20261031/acceptance-pytest -o cache_dir=.runtime/v4-backend-20261031/acceptance-cache --tb=short
node scripts/check_day08_frontend.cjs --out .runtime/v4-backend-20261031/release-day8 --runtime-dir .runtime/v4-backend-20261031/release-browser8
node scripts/check_day10_frontend.cjs --out .runtime/v4-backend-20261031/acceptance2-day10 --runtime-dir .runtime/v4-backend-20261031/acceptance2-browser10
node scripts/check_layout_visual.cjs --out .runtime/v4-backend-20261031/release-visual --runtime-dir .runtime/v4-backend-20261031/release-browser-visual
```

未运行真实云端集成、压力/内存量测或真人可用性测试，不用离线结果代替法律语义评估。同步线程不能强制杀死，供应商也未提供跨崩溃 exactly-once 保证；本轮限制的是受理容量、发布资格与本进程正式提交。跨 Worker 事务存储、分析请求操作编号、全量姓名/地址识别及语义 claim 判定未扩入本轮。体验新版前保存现有清单，重启后端并刷新页面，以同步新隐私策略与协议。
