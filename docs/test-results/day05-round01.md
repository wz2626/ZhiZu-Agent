# Day 5 回合 1：首次真实云端联调与连接修复

日期：2026-10-11（北京时间）。代码基线 `2c007bd`，本轮待提交。开始时已有 README 修改和未跟踪的 `docs/day05-handoff.md`，保留这些内容。

## 本轮范围与结论

用户填写本地凭据后授权检查并开始 Day 5；随后明确选择“先完成真实联调，接口与 Spec 暂不调整”。因此本轮只完成真实云端入库、检索、两份合成合同审查及联调阻塞修复。没有新增接口、修改 Spec 或开发对外 trace。Day 5 尚未全部完成。

真实向量入库、重复入库、五类检索及两份合同的工程链路通过。模型内容仍有待复核项，不能把结构检查通过视为全面语义验收。

## 配置与环境

- 聊天：DeepSeek 官方 `https://api.deepseek.com`，`deepseek-flash`；服务实际返回同名模型。未修改默认思考模式，不存储或展示模型隐藏思维。
- 向量：硅基流动 `https://api.siliconflow.cn/v1`，`BAAI/bge-m3`，1024 维。
- 本地独立索引：`.runtime/chroma_cloud`；原 Mock 库未删除、未混用。
- 凭据只从被 Git 忽略的 `.env` 读取，不输出到终端、报告或日志。只向对应服务商发送认证信息。
- 本地最终配置 `CHAT_TIMEOUT_SECONDS=60`，代码默认仍为 20，可设置范围 1～120。此值是 SDK/HTTP 连接及读写超时配置，不是整个请求的硬性墙钟截止时间。SDK 自动重试为 0，Critic 重写上限保持 2 次。
- 本地原有 SOCKS 代理配置需要 `socksio`，已安装 `socksio==1.0.0`；依赖清单改为 `httpx[socks]>=0.27.0,<1.0.0`。

## 真实执行及自然故障

1. 配置完整性检查通过，未输出 Key。
2. 首次执行 `.\.venv\Scripts\python.exe scripts/init_kb.py --mode cloud --verify-queries`，因缺少 SOCKS 依赖，在发出 HTTP 请求前报 `ImportError`。此时创建了空的独立 Chroma 集合，未写入法条向量。
3. 普通受限环境中 pip 受网络权限阻拦，未安装成功；随后通过自动审核提升权限，运行 `.\.venv\Scripts\python.exe -m pip install 'httpx[socks]' --retries 0` 成功。未改变机器代理设置。
4. 重跑相同入库命令成功：`before_count=0, inserted_count=32, updated_count=0, total_count=32, embedding_mode=cloud`。五类查询均返回法条。该次 PowerShell 输出中文编码显示异常，后续探针明确使用 UTF-8。
5. 临时验证脚本第一次在发出云调用前因 Windows 缺少 `tzdata` 初始化失败；改为明确的 UTC+8 固定偏移后运行，未增加额外依赖。
6. `.\.venv\Scripts\python.exe .runtime/day05/verify_cloud.py` 执行重复入库、FastAPI TestClient 检索及两份合同审查。两份审查首次分别出现 `APITimeoutError`（20.79 秒）与 `APIConnectionError`（约 2 毫秒），均回退 `mock`；图内为 `needs_review`，没有算作真实审查通过。见 [修复前记录](day05/cloud-before-fix.json)。
7. 只读调用官方 `/models`，代理和直连均返回 HTTP 200，配置模型可用。见 [连接检查](day05/chat-connectivity.json)。这证明认证和模型列举可用，不单独作为推理调用成功证据。
8. 本地最小复现发现：第一个服务关闭后，第二个服务的 SDK 复用了同一已关闭 HTTP 客户端，实测 `same_transport=True, second_transport_closed=True`。安装的 langchain-openai 0.3.35 对默认传输客户端使用缓存，而服务按请求关闭 root client，导致后续请求受影响。
9. 修复为每个服务显式创建并持有自己的同步 HTTP 客户端；初始化失败及请求结束均释放，重复关闭保持安全。增加独立客户端、初始化失败清理与超时传递回归测试。
10. 使用 `CHAT_TIMEOUT_SECONDS=60` 运行 `.\.venv\Scripts\python.exe .runtime/day05/verify_cloud.py --reviews-only`，两份合同均真实成功。随后仅在本地 `.env` 追加该超时设置，保留两把 Key 和其他配置。见 [修复后记录](day05/cloud-after-fix.json)。

临时探针位于本机 `.runtime/day05/`，不作为已发布的自动化集成测试脚本。上述请求经过 FastAPI TestClient 进程内路由，向量与聊天使用真实网络服务；本轮没有启动浏览器或独立监听端口。探针仅观察服务/图状态和调用统计，不改模型响应，不替换真实模型或向量。JSON 证据是过滤后的记录，不是原始 HTTP 或模型推理输出。

## 入库与检索结果

重复入库实际耗时约 1.93 秒：`before_count=32, inserted_count=0, updated_count=32, total_count=32`。状态接口 `is_ready=true, embedding_mode=cloud`。检索正文和来源逐项与仓库锁定的权威法条 JSON 回查一致；本轮未重新联网核对法条网站是否更新。

| 问题 | 实际 Top-3 | API 耗时 | 回查 |
| --- | --- | --- | --- |
| 押金返还 | LAW-733 / LAW-719 / LAW-714 | 0.84 秒 | ID、正文、来源一致，接口明确直接依据不足 |
| 房屋维修 | LAW-713 / LAW-712 / LAW-714 | 1.20 秒 | 一致 |
| 未经同意转租 | LAW-716 / LAW-724 / LAW-715 | 0.86 秒 | 一致 |
| 不定期租赁通知 | LAW-730 / LAW-707 / LAW-722 | 0.98 秒 | 一致 |
| 危及安全健康 | LAW-731 / LAW-724 / LAW-729 | 0.96 秒 | 一致 |

## 两份合成合同结果与内容限制

| 样例 | 最终状态 | 风险数 | 聊天耗时 / API 总耗时 | 生成次数 | Token（输入 / 输出 / 合计） |
| --- | --- | --- | --- | --- | --- |
| 正常到期退租 | success | 2 | 25.99 / 28.08 秒 | 1 | 713 / 4899 / 5612 |
| 押金不退与擅自转租 | success | 2 | 19.51 / 20.29 秒 | 1 | 722 / 4120 / 4842 |

两份结果的原句均为输入的精确子串，引用均属于本次检索法条，风险数与非 NONE 项数量相符，`retry_count=0`。Token 数来自 SDK 返回的 usage metadata；输出总数可能含模型内部推理消耗，不代表仅最终 JSON 的长度。超时调用的服务端消耗未获取，也没有取得本轮账单金额。

内容检查：

- 模型没有把押金相关条款直接判成有本章法条支持的 HIGH，明确说明本库没有押金返还的直接依据。
- “正常到期退租”样例得到 MEDIUM（租金支付细节）和 LOW（押金返还时间）两项提示。样例是简短摘录，“按约”可能指向未提供的其他约定；该结果可视为补充信息提示，但不能作为正常合同零误报验收通过。
- 第二份的转租条款原文写有“租客可以未经房东同意擅自转租”。模型直接断言该约定与 LAW-716 冲突、不能排除解除权，未充分讨论合同中的“可以”是否构成事先授权。这是语义待复核点，不将其记录为已证明的法律结论。
- 当前 Critic 仍仅进行结构、原句、引用范围、隐私等确定性检查。上述语义问题没有被当前 Critic 拦截；独立语义 Critic、更多正常例与完整合同上下文的评估仍待后续安排。

## 实际调用统计

- 成功的首次入库脚本：1 次 32 文本向量请求 + 5 次查询向量请求（按脚本调用路径核对；当次没有逐调用计时记录）。
- 修复前探针：8 次向量请求，均 HTTP 200；其中 1 次重复入库、5 次检索 API、2 次审查检索。
- 修复后探针：2 次审查向量请求，均 HTTP 200。
- 合计向量 HTTP 请求 16 次。缺依赖导致的首次入库失败没有发出向量请求。
- 聊天 SDK 调用共 4 次：1 次超时、1 次已关闭客户端错误、2 次成功。已关闭客户端错误没有到达远端；超时是否被服务端完成及计费未获取。不能把 4 次 SDK 调用写成 4 次服务端成功处理。
- `/models` 只读检查 2 次，均 HTTP 200；不计为聊天生成。

## 离线测试与依赖检查

普通受限环境中的两次 pytest（全量、审查模块）长时间无输出，已中断，退出码 1；未获得测试结果，不算通过。随后通过自动审核提升权限执行离线测试；未新增真实故障注入测试，也没有将自然超时/连接失败称为故障注入。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_review.py -q --basetemp=.runtime/pytest_day05_review_elevated
# 115 passed, 1 warning in 5.23s

.\.venv\Scripts\python.exe -m pytest tests/test_review.py tests/test_health.py -q --basetemp=.runtime/pytest_day05_timeout
# 134 passed, 1 warning in 5.70s

.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_day05_full
# 226 passed, 1 warning in 17.37s

.\.venv\Scripts\python.exe -m pip check
# No broken requirements found.
```

以上完成的命令退出码均为 0，无测试失败或跳过。警告仍是 LangGraph 导入时的 `LangChainPendingDeprecationWarning`。新增 10 项回归覆盖连接隔离、初始化失败清理、超时传递、非法/默认超时。

## 后续边界

Day 5 剩余的失败出口、对外 trace、接口兼容方案及审查模块 Spec，遵照用户本轮选择暂未实施。没有修改总 Spec，没有更改 API Schema，没有执行 Git 写操作或提交。Day 10/12 的全链路与效果评估不被本次小规模联调替代。

完整原始聊天记录待用户导出，本报告只是实测摘要和受控证据，不替代原始对话链。后续仍需用户作产品/语义验收及 Git 提交；当前接通流程不需要再手工填写配置或额外操作账户。

参考：[DeepSeek 思考模式官方文档](https://api-docs.deepseek.com/guides/thinking_mode/)（本轮核实默认启用、默认 effort 为 high），[聊天接口官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)。
