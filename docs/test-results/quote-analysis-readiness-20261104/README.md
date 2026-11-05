# 微信破招可用性复核与补丁（2026-11-04）

结论：复审提出的9条合法归因/否定均在修改前复现为UnsafeReplyError，不能依据未覆盖这些句式的LGTM直接放行。补丁后已通过正反例与全量回归，可以作为个人沟通辅助开始试用。模型仍有受控格式/引用失败，不承诺每次生成成功；当前证据不足以宣称可免审核商用或法律结论准确。

## 1. 本轮修改

| 文件 | 变更与边界 |
| --- | --- |
| `backend/app/services/quote_output_guard.py` | 归因扩展房东/对方/他/她与昨天/前天/刚刚等时间词，仍需原话逐字匹配；有界否定支持不敢/不承诺/不会等，不采用任意“不”字窗口；保留转折、新租客意图和双重否定拦截 |
| 同上 | best_for独立展示兜底：第一人称威胁、辱骂替换为档位中性提示，保留正文及来源，不因此整卡502；普通场景描述不变，PII/纯文本规则仍执行 |
| 同上 | 明确中文/阿拉伯数字条号归一化，如第一条/第1条；单位式中文支持1～9999，不猜“一百一”等歧义，不扩展已选来源白名单 |
| `backend/app/services/quote_analysis.py` | 发布卡片前应用提示语降级，状态/正文/来源校验不放宽 |
| `backend/app/services/quote_prompt.py` | 只对改变支持判断的关键事实追问，不因缺少完美证据一概unclear；补三档对象形状与引用子集示例，不改状态绑定 |
| `tests/test_quote_analysis.py` | 新增48项用例，总计189项；覆盖9条复现、其他归因/否定、反向威胁、双重否定、提示语降级、条号等价和未选来源拒绝 |
| `scripts/evaluate_quote_analysis.py` | 失败诊断增加结构化reply_source_ids，不改变API或内部调用次数 |

前端、旧评分/演练模块、其他后端API均无本轮新增改动。单次无状态、最多一次模型调用、无自动重试、来源后端回填保持不变。工作区已有修改保留，未执行Git写操作。

## 2. 离线与浏览器验证

最终代码执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/quote-readiness-final-full -o cache_dir=.runtime/quote-readiness-final-cache
node scripts/check_quote_panel.cjs --out .runtime/quote-readiness-browser --runtime-dir .runtime/quote-readiness-browser-runtime
node scripts/check_contract_import.cjs --out .runtime/quote-readiness-import --runtime-dir .runtime/quote-readiness-import-runtime
```

- **1122 passed，0失败/错误/跳过**，23.80秒；包含189项破招测试，保留1条已有LangChain弃用警告。
- **17组新面板检查通过**：[browser-results.json](browser-results.json)。HTTP明确使用替身，覆盖复制、遮蔽、IME、迟到响应、状态拒绝、范围外清卡及四档布局。
- **17组真实本地合同导入检查通过**：[import-results.json](import-results.json)。使用真实Uvicorn/Word/PDF解析，无模型调用。
- 首次受限沙箱的pytest在本地通信测试处挂起，未算通过，已停止该轮进程；允许本地通信的执行环境配合项目内临时目录完成上述回归。没有将tmp_path错误算成断言通过。
- 旧演练浏览器检查未运行，不算通过；其后端测试仍包含在全量pytest中。
- `pip check`、两个当前浏览器脚本的Node语法检查、本轮Markdown本地链接检查及`git diff --check`通过；Git另提示部分已有文件的LF/CRLF转换，不是测试失败。

## 3. 真实模型验证：保留失败

未获得复审者的20条真实微信原始数据。本轮使用脚本内20条明确标记的合成脱敏案例，调用当前已配置模型，不能称为真人试用或复跑对方数据。

首轮命令：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_quote_analysis.py --out .runtime/quote-readiness-live.json --count 20
```

[live-batch.json](live-batch.json)：**9 success、7 needs_context、2 out_of_scope、2 MODEL_OUTPUT_INVALID**。即18例有效，2例被拒绝；有效卡片均满足状态/立场/追问绑定，无本轮已观测的威胁归因误杀。中位4.695秒、p95 7.320秒，仅为本次小样本观察。

两次失败分别是回复引用集合不合规、三档回复错误地输出为字符串。服务端均拒绝，未放宽校验或补造来源。补充结构示例后，对这两个案例各复测一次：[live-retest.json](live-retest.json)，入室场景成功、押金返还日期场景仍被引用校验拒绝。随后为定位引用问题新增结构化ID诊断，再单独调用该押金案例一次：[live-source-probe.json](live-source-probe.json)，该次成功，因而未取得失败时的完整回复ID诊断；不能宣称根治了模型引用错误。

本轮共**23次独立云请求，每次恰好1次模型调用，自动重试0次**。不继续反复重试凑全绿。20个不同案例最终各有一个有效输出，经最终校验器及后端来源原文映射重新验证，但这是首批＋复测＋诊断的累计结果，**不是单批20/20**。统计及逐例结果见[summary.json](summary.json)。失败档案仅保留受控类别/结构诊断，不归档被拒绝的回复原文。

新批次追问减少，但样本小、生成有随机性，不能仅凭success占比提高认定质量改善。仍需核对引用与实际争议的关系；条号/来源真实性校验不能证明法律适用正确。

## 4. 使用判断

重启后端、刷新页面后可开始个人辅助试用：粘贴脱敏合同与房东原话，检查拆解和引用，再选择一种回复复制。needs_context仍有三档澄清回复；出现受控失败保留旧卡，检查其“旧输入”提示，再决定是否补充或手动重试，后者可能再次计费。

尚未验证真人长期使用、真实纠纷效果、公网运营及完整法律适用准确性。法条库仍限租赁章节703～734，姓名/详细住址仍需自行处理，正则仅覆盖已定义的语言模式。可以用于准备沟通，不把当前结果当成自动判责或保证谈判结果。

历史记录：[上轮CR补丁](../quote-analysis-cr-patch-20261104/README.md)。本轮结论覆盖其中“中文/阿拉伯数字未互通”的旧边界，不改写历史失败。
