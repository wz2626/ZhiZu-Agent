# 五个沟通方向与保守推荐

2026-11-01，待开发者提交。仅修改单文件前端与浏览器验收脚本；未修改后端、Spec、固定报价或算分。完整原始对话待开发者导出，本文件为实测摘要。

新增“租金与额外收费”和“其他沟通诉求”；二者仅提供表达准备、参考稿与核对后复制，禁止向固定演练提交，不显示模拟分数、轮次或房东条件。原押金/维修/提前退租演练保持原有HTTP枚举和规则。

原句明确只对应一个方向时，在首次进入沟通时推荐并允许更改；多个方向并存时不强选，未匹配时推荐其他。手动选择后不覆盖；按分析版本与条款隔离，目标和参考稿仍归条款，消息和演练进度归具体方向记录。推荐只用于导航，既不分类法律风险也不添加法律依据，不会自动生成或发送消息。空占位只在收起时显示，不占展开选项的一行。

## 验证

- `pytest -q tests/test_frontend_static.py`：5 passed，1条既有LangChain依赖warning；本轮未重复运行全量后端。
- `node scripts/check_day08_frontend.cjs --out .runtime/directions-20261101/day8-final2-evidence --runtime-dir .runtime/directions-20261101/day8-final2-runtime`：41组通过。[机器结果](day8.json)。
- `node scripts/check_day10_frontend.cjs --out .runtime/directions-20261101/day10-final-evidence --runtime-dir .runtime/directions-20261101/day10-final-runtime`：79组通过，使用真实本地业务图和明确离线云模型替身。[机器结果](day10.json)。
- 新检查覆盖五方向、明确/混合推荐、手选保留、独立消息、目标不覆盖、复制拒绝兜底、IME延后切换、手机固定视口、单Composer及新增方向0次turn请求；原报价、算分、未知结果恢复、Critic与草稿归属断言保留。
- 初轮测试脚本需迁移场景和句柄：押金1000→1500断言显式绑定押金记录；视觉检查重载页面后重新捕获Composer；合成change事件在IME期间改变原生select值，检查应验证应用方向/消息未切换。修正脚本后完整复跑，没有降低报价和恢复断言。

## 真实云端独立复验

真实生产app，无模型Mock；DeepSeek官方deepseek-flash、硅基流动BAAI/bge-m3。独立服务与Edge浏览器，合成合同。分析API约30.26秒；向量批量5视图503.10ms；审查模型28.39秒；费用草稿模型10.47秒，其他诉求草稿模型7.15秒。合计1次真实向量HTTP、3次真实聊天HTTP，均200。

费用条款推荐fees；填写目标后生成费用草稿并明确采用；切other后生成进入房屋通知相关参考稿，返回fees仍保留原消息。固定演练turn请求为0，页面不出现模拟分数/轮次。手机无全局溢出，浏览器Warning/Error为0。[安全调用与浏览器记录](live.json)。本轮未扩展法库，费用具体法律依据不足时仍需补充核对。

仅保留两张真实结果截图：[费用草稿采用](fees-real-draft.png)、[其他诉求手机](other-real-mobile.png)。均已肉眼查看。生成过程和合成回归截图保留在本机忽略目录，不继续扩充待提交附件。
