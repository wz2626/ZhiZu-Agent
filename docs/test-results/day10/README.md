# Day 10 v0.1 附件

主报告：[Day10全链路](../day10-round01.md)。全量465 passed、0 failed、0 skipped，1条既有warning；浏览器18组通过。

| 附件 | 内容 |
| --- | --- |
| [changed-files.md](changed-files.md) | 本轮51个新增/修改文件的完整只读Git清单 |
| [pytest-stdout.txt](pytest-stdout.txt)、[pytest-redacted.xml](pytest-redacted.xml) | 最终全量stdout原件与JUnit脱敏副本（仅遮蔽12处既有合成号码参数名，数量/结果/耗时不变；临时原件收尾清理） |
| [pytest-affected-final.txt](pytest-affected-final.txt) | 最终相关回归193项 |
| [pytest-affected.txt](pytest-affected.txt) | 早期扩展回归176项，仅保留过程 |
| [pytest-web-final.txt](pytest-web-final.txt) | 页眉版本最终调整后首页/静态回归23项 |
| [browser-stdout.txt](browser-stdout.txt)、[browser-results.json](browser-results.json) | 最终无头Edge18组逐项输出 |
| [actual-http-traces.json](actual-http-traces.json) | 真实本机公开响应及Trace；无请求体/候选/消息历史 |
| [browser-attempt01.txt](browser-attempt01.txt)、[browser-attempt02.txt](browser-attempt02.txt) | 两次验证脚本等待条件错误，非产品历史事故 |
| [input-review-highlight.png](input-review-highlight.png) | 脱敏快照与押金原句联动 |
| [deposit-closed-loop.png](deposit-closed-loop.png)、[deposit-checklist.md](deposit-checklist.md) | 押金正式结果与导出 |
| [maintenance-closed-loop.png](maintenance-closed-loop.png)、[maintenance-checklist.md](maintenance-checklist.md) | 维修对应条款、正式结果与导出 |
| [early_termination-closed-loop.png](early_termination-closed-loop.png)、[early_termination-checklist.md](early_termination-checklist.md) | 提前退租对应条款、正式结果与导出 |
| [mobile-replay.png](mobile-replay.png) | 手机布局与坏Trace拒绝注入 |

审查聊天/检索是显式测试替身，经真实服务和图运行；谈判使用真实HTTP/图与固定离线策略。实际节点实测计时与预设演练内容分开标明。服务与页面外网调用0，云端Token消耗0。Day9补验11组为18组子集。
