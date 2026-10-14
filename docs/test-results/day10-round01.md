# Day 10 回合 1：v0.1 全链路与三场景实测

日期：2026-10-14（北京时间）。基线 `4abd13db87ad83c1b7e9e6062dd6cd2ace26cb0c`（Day 9）。本轮代码待开发者提交；未暂存、提交或执行其他 Git 写操作。

最终全量 **465 passed，0 failed，0 errors，0 skipped，1 warning in 17.62s**；原381项逻辑不变，新增84项。无头浏览器 **18组通过，0失败、0跳过**；三场景分别重新走完输入、脱敏预览、排雷高亮、3轮谈判（50/75/100）、真实回放与清单导出。云端调用和Token消耗0。

## 契约与实现

按修订计划核对，Day 10 补齐三场景闭环与阻塞修复的安排正确。用户明确授权新增 [Spec 04](../specs/spec-04-negotiation-api-and-scenarios.md)，先落地 HTTP、三场景提取/计分、真实 Trace、缓存标识与失败边界，再实施。未改审查业务、法条数据、既有测试逻辑或外部进度文件。

- 新增唯一 `POST /api/negotiation/turn`，精确声明 `session_id/user_input/request_id/scenario`，前端从真实 OpenAPI 自动发现；严格输入422、冲突409均无原始input回显。
- 三场景分别使用押金返还额、房东维修费用比例、提前退租违约金。规则由服务配置，Critic 检查明确确认、回复一致性、边界与可信引用；相同状态重算同分。
- HTTP 固定离线演练策略与保留的 Day 7 Python 默认保守行为分开配置。用户金额、法条或自称确认不能写入正式条件。
- 入口和服务二次遮蔽手机及15/18位身份证；拒绝未脱敏回复，缓存失败前丢弃草稿。前端继续预览/确认并映射规范场景及中文条件。
- 每个真实节点以单调时钟测量，序号连续、状态白名单、有限非负耗时、attempt≤3；Critic含受控摘要。异常保留已执行记录，不虚构提交节点或未执行节点。
- 单会话锁与完整快照替换，最多5轮/2次重写；失败不提交，成功与失败响应均幂等缓存。响应丢失后重试标 `replayed=true`，第6次不执行图、返回空Trace。

## Python 验证

环境：Windows，仓库 `.venv` Python 3.12.13、pytest 8.4.2。所有测试默认禁止外部 DNS、socket connect/connect_ex；原有模型与向量替身继续使用。测试网络拦截器本身的用例仅对保留测试地址尝试，被调用前阻断，不发送云端请求。

```powershell
# 早期相关回归
.\.venv\Scripts\python.exe -m pytest -q tests/test_negotiation.py tests/test_scoring.py --basetemp=.runtime/pytest_day10_negotiation
# 109 passed, 1 warning in 1.18s

# 扩展与加固后的最终相关回归
.\.venv\Scripts\python.exe -u -m pytest -q tests/test_negotiation.py tests/test_scoring.py tests/test_negotiation_api.py --basetemp=.runtime/pytest_day10_api_final
# 193 passed, 1 warning in 4.01s

# 最终全量
.\.venv\Scripts\python.exe -u -m pytest -q --basetemp=.runtime/pytest_day10_full --junitxml=docs/test-results/day10/pytest.xml
# 465 passed, 1 warning in 17.62s
```

输出见 [最终全量 stdout](day10/pytest-stdout.txt)、[JUnit脱敏副本](day10/pytest-redacted.xml)、[最终相关回归](day10/pytest-affected-final.txt)；中间176项相关测试输出保留为 [早期扩展验证](day10/pytest-affected.txt)，不充当最终数。

前端最终v0.1页眉与场景高亮核对后，追加受影响首页/静态回归 **23 passed，1 warning in 2.63s**，见 [输出](day10/pytest-web-final.txt)。新增PII参数测试采用语义化用例ID；既有测试仍有12处参数名含合成号码，为保留测试逻辑不改，另生成明确标注的JUnit脱敏副本，仅遮蔽这些参数名称，不改数量/结果/耗时。原始XML移至本轮临时目录并在收尾清理；stdout原件保留。

首次最终全量为465项/17.84秒；归档扫描发现新增参数的JUnit用例名含合成号码，改为语义化ID后重新全量运行，最新为465项/17.62秒。未修改既有测试逻辑；本报告链接的stdout原件与JUnit脱敏副本来自后一次运行。

新增84项覆盖三场景5轮、降向目标、同状态同分、严格输入/额外字段/坏JSON、手机与有效或畸形身份证遮蔽、未脱敏候选与缓存、条件/否定/转述/重复/跨场景模板、越界金额、引用可追溯/重复/未检索、最多重写2次、失败不提交、异常前真实Trace、并发会话隔离和同请求只提交一次、OpenAPI唯一发现、网络拦截。

唯一warning为既有 LangGraph `JsonPlusSerializer` 导入的 `LangChainPendingDeprecationWarning`，未隐藏。最初受限环境4次 pytest 尝试阻塞于 `socket._fallback_socketpair → accept`；通过 faulthandler 实际定位后中断，不计通过。随后受控允许本机回环，所有完成的测试结果如上。

## 无头浏览器

```powershell
node --check scripts/check_day10_frontend.cjs
node scripts/check_day10_frontend.cjs
```

Node v24.14.0、无头 Edge 155.0.4283.45，冷缓存隔离配置，所有非同源页面请求拒绝。脚本启动本地 FastAPI，审查替身通过真实审查服务/图；谈判调用真实路由/服务/图和固定离线策略。测试专用 `scripts/day10_offline_app.py` 不由生产应用导入，显式替换凭据并拦截外部DNS/socket/HTTP。1.25秒等待延迟与越界报价、响应丢失、坏Trace、剪贴板拒绝均为明确故障注入。

[18组逐项结果](day10/browser-results.json)、[stdout](day10/browser-stdout.txt)、[真实公开 HTTP 响应/Trace](day10/actual-http-traces.json)。响应归档没有请求体、未脱敏标识、消息历史或未通过草稿。Day 9 的11组补验是这18组的子集，不另加到通过数。

| 组 | 验证 |
| --- | --- |
| 1～5 | 本地资源、真实OpenAPI；输入预览遮蔽；等待计时不造节点；审查图/脱敏快照/精确高亮；谈判消息再脱敏并撤销确认 |
| 6～8 | 等待互斥、防双击；押金1000/50与1500/75；真实节点、反馈、耗时及进度动画一致 |
| 9～10 | 越界报价最多3次生成，正式状态不变；提交后丢响应同编号重试只提交一次并标缓存回放 |
| 11～13 | 清单与正式状态一致、人工项脱敏；剪贴板拒绝的复制降级；历史回放标识 |
| 14 | 维修重新输入→预览→排雷→维修条款高亮→50/75/100→Trace→清单 |
| 15 | 提前退租重新输入→预览→排雷→退租条款高亮→50/75/100→Trace→清单 |
| 16～18 | 坏Trace拒绝不补造；390px无溢出；页面/服务外网调用0、运行时异常0、请求敏感标识0 |

截图：[输入与高亮](day10/input-review-highlight.png)、[押金闭环](day10/deposit-closed-loop.png)、[维修闭环](day10/maintenance-closed-loop.png)、[提前退租闭环](day10/early_termination-closed-loop.png)、[手机布局](day10/mobile-replay.png)。清单：[押金](day10/deposit-checklist.md)、[维修](day10/maintenance-checklist.md)、[提前退租](day10/early_termination-checklist.md)。已目视检查桌面与回放布局。

首次浏览器脚本在DOM未挂载时访问空元素失败，见 [attempt01](day10/browser-attempt01.txt)；第二次在此前审查Trace仍播放时比较节点数量失败，见 [attempt02](day10/browser-attempt02.txt)。均修正脚本等待条件，未修改产品迁就断言。后续18组通过；最终完善每场景独立输入与对应高亮后再次复验，以当前stdout和JSON为准。

归档复核另发现脚本的坏Trace注入与响应归档共用对象引用，可能改动最后一份归档数据。已在注入前深拷贝真实服务器响应、增加全附件序号断言并重跑；当前实际响应附件均保留服务器原始连续Trace，浏览器看到的破坏数据仅用于明确故障注入。

## 归档与剩余边界

Day 9 补档明确标2026-10-14补验；历史聊天与当日输出未取得，不重建。Day 10 Prompt 摘要和索引同步更新，完整聊天导出仍待开发者提供。根README更新v0.1状态、465项实测、接口与三场景操作；Spec与测试证据新增README索引。

本轮临时浏览器配置、pytest临时目录在归档后按绝对路径限制清理，保留已有向量库与其他轮次目录；最终运行 `git --no-optional-locks status`。没有修改 `.env`、LICENSE或任何 `.git` 内容。

收尾检查：本轮51个新增/修改文件见 [完整改动清单](day10/changed-files.md)；本轮Markdown本地链接均有效，证据字符串脱敏扫描通过，JUnit脱敏副本仍为381/465项且失败/错误/跳过均0；15份实际HTTP响应Trace序号均连续。`git --no-optional-locks diff --check` 退出0，仅提示现有LF/CRLF策略。

离线成功不代表真实聊天/向量质量通过；当前提取是严格确认模板与确定性Critic，未完成通用自然语言或法律实质支持的语义验收。Day 11固定20例、Day 12对比/干净环境计时仍待执行，本次不填写未测指标。
