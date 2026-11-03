# V4 后端重构审阅修复

附件精简（2026-11-01，开发者要求）：重复截图、中间对比图及旧机器验收附件已移出待提交目录，保存在本机忽略归档 `.runtime/evidence-tidy-20261101.zip`；下文历史实测结论保留，附件数不代表当前保留数。


2026-10-31，按开发者“客观核实，属实修复”的要求完成。保留既有未提交工作，不执行 Git 写操作。

## 逐项结论与处理

| 审阅点 | 核实与最终处理 |
| --- | --- |
| Kimi：非评分条件循环信任 | 成立。服务从可信轮次和确认文本独立重建唯一 round_N 条件，不再从待审结果选择合法键。任意键、夹带额外键、缺项、错轮及修改历史项均拒绝；needs_review，不改正式状态，也不写请求缓存。图内 Critic 同步检查。正常 Critic 业务失败仍按原契约缓存。 |
| DeepSeek 1：重启后的 epoch 与409 | 成立。SESSION_INVALID 后重读真实 meta；旧记录/快照/epoch 不迁移，旧未知结果保持隔离。全新练习首次提交前读取当前实例；invalid 旧记录允许另开。REQUEST_CONFLICT 清除被拒编号、保留输入与练习，下一次明确动作使用新编号；INTERACTION_VERSION 引导重检协议，不废弃练习。 |
| DeepSeek 2：上下文全pin误报图失败 | 成立。OperationBusy/OperationExpired 单独向路由传播。100份上下文全部pin时实际返回503 SERVICE_BUSY、Retry-After，不追加graph失败Trace或生成200伪失败。 |
| DeepSeek 3：abort占64名额 | 原实现刻意把失败编号计入身份预算，Spec曾明确，并非线程容量未释放；但不利于超期后的连续恢复。本轮调整为在途/已发布64名额与失败防重入集合分离。abort退出释放在途名额；旧编号继续拒绝重入，失败身份随上下文结束释放、独立最多6400个，全局回执仍有上限。64次超期后新编号可成功生成。 |
| DeepSeek 4：累计1万身份 | 有意设计，原Spec已明确进程生命周期身份上限。本轮保持行为，README明确它不是并发上限，等待TTL不会恢复新建能力；需保存清单后重启。没有为了释放容量而静默复活旧会话。 |
| DeepSeek 5：前端规则写死 | 原设计明确要求联合发布，当前首轮已同时升级两端，并非当时后端独自升级。本轮进一步消除维护负担：meta提供engine、字符映射、替换符等完整数据；前端编译并消费版本/数字表/忽略字符/空格/映射/两套模式。在兼容fold-codepoint-v1引擎内接受规则版本更新，不再绑定固定版本字符串；不同引擎明确提示升级两端。 |

兼容安排回归保留了制表符、合法提交和缓存深拷贝验证；将其旧的任意handover键迁移为本轮唯一round_1键，没有删除该用例或放宽断言。Spec 02/04/05已同步修订。

主要改动：negotiation_service.py、negotiation_graph.py、review.py、proposal.py、review_context.py、privacy.py、schemas/interaction.py、frontend-web/index.html。新增tests/test_backend_v4_review_fixes.py、scripts/check_v4_review_fixes.cjs；离线服务增加仅测试使用的实例重置入口，不进入生产应用。

## 最终实测

| 验证 | 结果 |
| --- | --- |
| 全量离线pytest | **819 passed，0 failed/skipped，25.98秒**；一条既有LangChain弃用提示 |
| Day8 | **13组通过**；无谈判入口时合同分析仍可使用 |
| Day10 | **48组通过**，比上一阶段新增7组；外部请求0 |
| 视觉/空间 | **4组通过，15张截图**，已查看联系表 |

Python新增8项，覆盖5种伪造安排、100上下文全pin的503出口、64次abort与防重入、升级规则下实际浏览器函数/Python内核等价性。浏览器新增7组：真实替换服务实例与epoch；REQUEST_CONFLICT；INTERACTION_VERSION；首次发送前实例变化；428当前版本预览；兼容规则升级；不兼容引擎阻断并保留输入。

实例重置采用本机离线测试服务实际替换NegotiationService及会话注册表，不等同于杀死并重启整个应用进程。协议与策略变更使用明确的fetch响应替身；真实HTTP、生产前端与固定谈判图照常执行，云模型保持离线替身。未运行真实云模型、压力/内存量测或真人可用性评估。

附件：pytest（附件已移至本机归档）、Day8（附件已移至本机归档）、Day10（附件已移至本机归档）、视觉数据（附件已移至本机归档）、联系表（附件已移至本机归档）。中间失败保留在本机忽略目录：升级策略测试替身的转义曾未修改实际模式；Day8旧epoch替身不符合32位契约，且代码一度混淆“规则加载成功、OpenAPI发现失败”与“规则不兼容”。修正后分别完整重跑通过，未将这些失败计为验收通过。

实际完成命令（仓库根目录；重跑请更换独立目录）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/v4-review-fixes-20261031/acceptance-pytest -o cache_dir=.runtime/v4-review-fixes-20261031/acceptance-cache --tb=short
node scripts/check_day08_frontend.cjs --out .runtime/v4-review-fixes-20261031/acceptance-day8 --runtime-dir .runtime/v4-review-fixes-20261031/acceptance-browser8
node scripts/check_day10_frontend.cjs --out .runtime/v4-review-fixes-20261031/acceptance-day10 --runtime-dir .runtime/v4-review-fixes-20261031/acceptance-browser10
node scripts/check_layout_visual.cjs --out .runtime/v4-review-fixes-20261031/visual --runtime-dir .runtime/v4-review-fixes-20261031/browser-visual
```
