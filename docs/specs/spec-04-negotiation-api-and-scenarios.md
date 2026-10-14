# Spec 04：v0.1 谈判 HTTP、三场景与执行回放

状态：2026-10-14，Day 10 经开发者明确授权新增。继承 Spec 00/03；本规格扩展 Day 7 的仅押金模板与保守默认服务，不改变既有算分公式和旧审查接口。

## HTTP 与场景

唯一提交入口 `POST /api/negotiation/turn`，JSON 必填严格字符串 `session_id`、`user_input`、`request_id`；标识为 1～64 个 ASCII 字母、数字、下划线或横杠，禁止把手机号/身份证号用作标识。消息为 1～2000 字且非纯空白。`scenario` 默认 `deposit`，支持 `maintenance`（兼容 `repair`）和 `early_termination`（兼容 `termination`），响应使用规范名。禁止额外字段；客户端不能设置分数、规则、候选或可信引用。非法请求 HTTP 422，仅返回固定文案，不回显 input；同请求编号不同消息或同会话更换场景 HTTP 409。

入口和服务在执行图、缓存或写入历史之前，按浏览器同口径正则再次遮蔽 11 位手机（含国家码/分隔符）、15/18 位身份证（不依赖有效生日或校验码），替换为 `***`。模型/响应器返回未脱敏信息时 Critic 拒绝。自由文本姓名/住址仍需人工预览处理。

HTTP 默认使用**固定策略的离线模拟房东**，不调用云端，不从用户金额、法条或声称的房东答复复制条件；按成功轮次选择下表的预设报价。它是可复现演练，不宣称通用自然语言理解或真实房东接受概率。Python 服务默认保留 Day 7 的“暂未确认”行为，可显式注入响应器。未来真实模型接入须另行验证。

| 场景 | 唯一计分项 / 允许区间 | 起点 → 目标，权重 | 第1/2/3～5轮预设值 | 严格完整确认模板 |
| --- | --- | --- | --- | --- |
| deposit | `deposit_refund` / 0～2000元 | 0 → 2000，1 | 1000 / 1500 / 2000 | `【模拟房东】我确认返还押金1000元。` |
| maintenance | `repair_cost_share` / 0～100% | 0 → 100，1 | 50 / 75 / 100 | `【模拟房东】我确认承担维修费用50%。` |
| early_termination | `termination_fee` / 0～2000元 | 2000 → 0，1 | 1000 / 500 / 0 | `【模拟房东】我确认提前退租违约金为1000元。` |

数字可带小数，可附 Spec 03 的 `依据LAW-xxx。` 尾句，但必须属于服务提供的已核验证据集合。跨场景模板、否定、条件句、转述、冲突/重复金额均不提取为确认条件。HTTP 默认不引用法条、可信证据集合为空；审查引用不得由浏览器直接升级为谈判可信集合。维修比例和违约金目标均为演练参数，不是法律责任判定。按完整确认状态重算，例中三场景前3轮均为50/75/100；同状态同分，目标等于起点及权重规则沿用 Spec 03。

## 响应、事务与幂等

响应只公开 `session_id/request_id/scenario/status/round_count/confirmed_terms/confirmed_evidence_ids/trial_score/score_explanation/coach_advice/landlord_response/retry_count/errors/trace_label/trace/unresolved_requests/missing_facts/replayed`，不公开未通过草稿、候选分数或用户消息历史。业务失败 HTTP 200 `needs_review`；图异常同样安全退出，保留此前正式条件、轮次、分数和已执行 Trace。

Critic 通过才原子替换单会话正式快照。最多5轮、最多2次重写（3次生成）。图失败绝不提交。相同会话和请求编号、相同脱敏消息返回缓存，`replayed=true`，不执行节点、不再次提交；成功和质检失败响应均缓存。换编号才能重新尝试已缓存失败。第6轮返回当前条件、`completed`、本次请求编号、空 Trace，不复用第5轮 Trace。默认内存单进程，重启清空，不提供长期历史。

## Trace

每个实际执行节点用单调 `perf_counter` 测量；请求局部收集器保留异常前记录。`sequence` 从1连续，`node` 为 `tenant_coach/landlord/rule_score/critic/retry/completed/graph`；`attempt` 1～3，直接结束或编排异常允许0；`status` 为 `completed/failed/retry/needs_review`；`duration_ms` 有限且非负；`feedback` 仅固定受控摘要，Critic 成功和失败均有反馈；`evidence_ids` 仅含可信法条 ID。不包含输入、消息、草稿、未知异常、密钥或隐藏思维。

本轮保留既有图的 Critic 节点内部生成通过后的完整快照；服务锁内替换正式状态。不虚构额外 commit 节点。未执行的节点不补齐；异常节点只记录实际异常；历史缓存 Trace 用 `replayed` 明示“缓存响应回放”，不称本次新执行。前端保持 OpenAPI 唯一发现、同请求重试、失败保留上一状态、场景切换新会话和完整响应后回放。

## 验证与归档

原有381项测试逻辑不变，新增三场景、引用、PII、HTTP/OpenAPI、有界重写、并发幂等与实测 Trace 测试。全量 `.venv` pytest 离线运行。无头浏览器连接本地 FastAPI、真实谈判图和固定策略；审查使用显式测试聊天/检索替身经真实审查图运行，外网被阻断。Day 9 归档为2026-10-14补验，不重建缺失的历史聊天或测试证据；云端语义效果、Day 11固定20例和Day 12干净环境计时仍单独验收。
