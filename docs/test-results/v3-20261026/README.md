# V3 全栈实施与验收报告

> 2026-10-30 第一次整体优化收口：本报告为历史阶段记录，不代表当前界面。重复截图、测试输出及中间验收附件已移至本机忽略目录 `.runtime/optimization1-cleanup-20261030/docs/test-results/v3-20261026/`；迁移清单和 SHA-256 位于该归档根目录 `manifest.json`。下文附件数量与路径保留为当时记录，标注已转归档的文件不再随仓库提交；当前验收见 [表单反馈与视觉修复](../ux-feedback-20261030/README.md)。

完成日期：2026-10-26（Asia/Shanghai）。本次依据开发者确认的 Codex/Kimi 合并方案实施，包含规格文档同步。代码未提交，未执行 Git 写操作；用户已有修改及旧 Day9/Day10 附件保持。

## 最终验证结果

| 验证 | 最终结果 | 附件 |
| --- | --- | --- |
| 全量离线 Pytest | **728 passed，0 failed，0 skipped**；1条既有依赖警告，23.18秒 | 完整输出（历史附件 `pytest.txt`，已转本机归档） |
| Day 8 浏览器 | **25 passed，0 failed，0 skipped**，原24组＋1组法条正文核对 | 结果（历史附件 `day08-results.json`，已转本机归档） |
| Day 10 浏览器 | **43 passed，0 failed，0 skipped**，原32组＋11组V3 | 结果（历史附件 `day10-results.json`，已转本机归档）、[真实公开响应](public-http-responses.json) |
| 独立视觉／空间 | **10组通过**，生成29个场景截图；已查看联系表与关键原尺寸截图 | 结果及尺寸（历史附件 `visual-results.json`，已转本机归档）、联系表（历史附件 `contact-sheet.png`，已转本机归档） |
| 真实聊天草稿检查 | 合成维修上下文，`deepseek-flash`，**一次生成成功，零重写，11.794秒** | [结构化结果与真实Trace](live-proposal-smoke.json) |

Python 3.12.13、pytest8.4.2、Node v24.15.0、Edge156.0.4314.42，Windows。本次新增76项Python测试：条件变化34、草稿35、法条回填7。离线浏览器与本地测试服务均观测到0外部/云调用、0浏览器运行异常；真实聊天检查单独列示，不能混称全部验证零云调用。

警告为既有 `LangChainPendingDeprecationWarning`。一次全量尝试因Windows以GBK解码子进程UTF-8输出而失败（727通过、1项CLI测试失败）；统一 `PYTHONUTF8=1` 后原断言完整通过，未为此改写测试或业务代码。

## 实际交付行为

- 精确原句青色发光框、交互时短时虚线引线；减少动态效果时静止。保留重复、跨段、重叠原句和12px避让。
- 详细审查返回 `evidence_by_id`，正文、条号、来源和核验日期可展开核查；旧模型六字段与旧审查接口兼容。
- `turn_effect` 在会话锁内比较正式前后快照，随请求缓存；首轮不把null当0，降向目标正确判方向，目标后维持不暗示房东强硬。
- 红青条表达已计分目标进度和剩余差距，变化徽标与逐项before/after来自后端。
- 草稿绑定30分钟/100份短时审查上下文，单上下文64个独立请求；引用、长度、JSON和隐私经有界校验，同编号重放不重复生成。
- 草稿预览位于主输入区上方，只有人工点击才填入。已有文本须确认替换，填入后撤销发送隐私确认；目标、条款、会话和输入修改隔离迟到响应。
- Pipeline使用真实事件、耗时、状态与受控反馈，区分当前、历史、缓存及草稿任务；完整响应前仅显示等待计时。

## 验收中实际修正的问题

1. 草稿429是审查上下文请求上限，已改为提示重新审查并清除不可用的重试请求。
2. 前端变化校验补足变化集合完整性与整轮类型一致性，拒绝“金额上涨却称维持”的矛盾响应；同编号重试可恢复正式缓存结果。
3. 稠密短合同展开详情后高度过大，收紧段落和卡片间距；不足400字或每条对应文本不足100字时采用行内批注，一般长文继续SVG页边轨道。
4. 首轮发送按钮最初落在900px视口之外，调整演练区间距后保留首屏可达硬断言；未隐藏错误、标签或隐私说明来凑高度。
5. 草稿从窄侧栏移入宽幅预览，避免长消息挤成细长卡片和两侧失衡。
6. 后端校验区分合同条号与法律引用，拒绝深嵌套/超长JSON，配置和生成异常使用受控失败。独立审阅发现的问题已补入回归。

某次视觉隐私检查把 `body.textContent` 中内联脚本的合成号码常量也当作界面输出；已改为检查渲染应用区域，继续验证坏草稿不进入UI。一次新增CDP故障注入等待超时后，经定向复核及最终完整重跑通过；只把最终完成运行列为通过。

## 核心规则与空间覆盖

Day10保留三场景五轮、防双击、失败不提交、同编号重试、会话隔离、隐私检查、手动复制回退、键盘操作及真实Trace。新增覆盖：法条正文与官方源、唯一提交入口、改善/降向/维持、矛盾变化拒绝与缓存恢复、草稿隐私/显式替换、丢响应幂等、目标/输入/条款/会话四类迟到隔离、三次失败终止及429。

空间检查包含1440×900首屏发送、1920×1080、1280×720、390×844、560/700/800/900矮窗与125%/150%/200% CSS布局放大。空间变化保持会话、草稿、隐私和正式状态；单实例输入框保留，隐藏区域零占位且不可聚焦，Trace不覆盖控件。放大为CSS reflow代理，不冒充浏览器仅文字放大。

原验收调用与保护项核对（历史附件 `core-preservation.json`，已转本机归档）确认原有检查调用均存在，既有Python测试、算分公式、原审查/协商图、requirements与Day9/Day10历史证据未改。新增测试并非通过减少旧断言来对齐数量。

## 代表截图

本报告保留7张PNG（含联系表）；其余最终截图及全部试跑材料保留在被忽略的 `.runtime/v3-20261026/`，不作为待提交证据批量加入。JSON明确标注每个场景是否归档，未保留的单图不视为缺失的正式附件。

| 场景 | 截图 |
| --- | --- |
| 输入首屏 | 输入（历史附件 `01-input-first-screen.png`，已转本机归档） |
| 短合同选中 | 批注（历史附件 `08-short-contract-selected.png`，已转本机归档） |
| 法条全文就地展示 | 正文与来源（历史附件 `24-v3-law-evidence-expanded.png`，已转本机归档） |
| 宽幅草稿预览 | 草稿（历史附件 `26-v3-proposal-preview.png`，已转本机归档） |
| 条件改善与双色条 | 本轮结果（历史附件 `27-v3-confirmed-improvement.png`，已转本机归档） |
| 手机草稿与输入 | 手机（历史附件 `29-v3-proposal-mobile.png`，已转本机归档） |
| 全场景总览 | 29场景联系表（历史附件 `contact-sheet.png`，已转本机归档） |

已按联系表检查全部场景，并查看输入、长合同中段、首轮、200%放大、法条展开、草稿预览、改善和手机等原尺寸图。此记录限于这些窗口与状态，不宣称任意合同、屏幕和用户审美下完美。

## 修改文件清单

以下列出本次源代码、测试和核心文档范围；工作区里更早的改动不冒充本次新增。

| 分组 | 文件 |
| --- | --- |
| 前端 | `frontend-web/index.html` |
| 协商后端 | `backend/app/schemas/negotiation.py`、`services/negotiation_effect.py`（新）、`services/negotiation_service.py`、`api/negotiation.py` |
| 审查与草稿后端 | `backend/app/schemas/review.py`、`schemas/proposal.py`（新）、`services/review.py`、`services/review_context.py`（新）、`services/proposal.py`（新）、`api/review.py`、`main.py` |
| 新增Python测试 | `tests/test_negotiation_effect.py`、`tests/test_review_evidence.py`、`tests/test_proposal.py` |
| 浏览器验收 | `scripts/check_day08_frontend.cjs`、`check_day10_frontend.cjs`、`check_layout_visual.cjs`、`day10_offline_app.py` |
| 文档 | 根README、技术亮点、规格索引、Spec00/02/03/04、新Spec05、实测结果索引及本报告 |

## 命令与验证范围

全量使用一次性目录，实际输出记录为：

```text
PYTHONUTF8=1
python: .\.venv\Scripts\python.exe -m pytest
--basetemp=C:\Users\wz200\AppData\Local\Temp\zhizu-v3-utf8-4159b4b55a9a461282ba40438086bca8\pytest
-o cache_dir=C:\Users\wz200\AppData\Local\Temp\zhizu-v3-utf8-4159b4b55a9a461282ba40438086bca8\cache
-o faulthandler_timeout=40
```

浏览器最终运行目录：

```text
node scripts/check_day08_frontend.cjs --out .runtime/v3-20261026/day08-final --runtime-dir .runtime/v3-20261026/day08-runtime-final
node scripts/check_day10_frontend.cjs --out .runtime/v3-20261026/day10-final --runtime-dir .runtime/v3-20261026/day10-runtime-final
node scripts/check_layout_visual.cjs --out .runtime/v3-20261026/visual-final --runtime-dir .runtime/v3-20261026/visual-runtime-final
```

上述目录非空后脚本拒绝覆盖，复验必须换新目录。Windows受限沙箱内的TestClient/本地回环和命令登记可能受限，最终运行使用允许本机回环的执行环境，离线测试的外网拦截仍保持。

真实聊天只验证新草稿服务：上下文为明确合成的已审查fixture，实际模型输出通过结构/引用/隐私校验；引用LAW-712/713，金额和日期未捏造。并未重新测量上游审查语义、总体法律准确率或现实房东接受概率。模型提供8项待补问题、消息较长，用户仍应审核、编辑后再发送。没有用这一例推导总体效果指标。
