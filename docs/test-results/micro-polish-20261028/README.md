# V3.5 六项微交互增量验收

> 2026-10-30 第一次整体优化收口：本报告为历史阶段记录，不代表当前界面。重复截图、测试输出及中间验收附件已移至本机忽略目录 `.runtime/optimization1-cleanup-20261030/docs/test-results/micro-polish-20261028/`；迁移清单和 SHA-256 位于该归档根目录 `manifest.json`。下文附件数量与路径保留为当时记录，标注已转归档的文件不再随仓库提交；当前验收见 [表单反馈与视觉修复](../ux-feedback-20261030/README.md)。

2026-10-28。本轮完成已授权的 45／25／26／3／24／11 六项视觉细化。生产修改集中在 `frontend-web/index.html`：新增局部 CSS、展示标签和已有状态绑定，未新增请求、业务状态或依赖。

| 项目 | 最终实现 |
| --- | --- |
| 45 数字排版 | 分数、轮次、分差、耗时、金额采用 `tabular-nums`；分数预留 9ch，金额仍可换行，不截断 |
| 25 回应冷暖上沿 | 1px 绝对定位细线，采用 `lastSuccessfulEffect`；改善／首次确认青色、退步暖红、维持／调整中性色；失败保留上一成功回应颜色 |
| 26 五轮筹码槽 | 轮次徽标内五个常驻细槽，按正式 `roundCount` 点亮，保留原文字与外框尺寸；装饰为 `aria-hidden` |
| 3 主按钮按压 | 启用的主按钮在桌面实际按下时下沉 1px、阴影收窄；触屏／减少动态效果保留静态颜色反馈，禁用按钮不位移，焦点环保留 |
| 24 旧条件交割 | 本轮变更行只对“存在旧确认值且改善”的旧值划线；新增确认不虚构历史，正式条件清单保持正常文字 |
| 11 Pipeline 通路 | 在真实事件间的既有 24px 间隔中绘制伪元素轨道；回放期间短时填充，重试继承琥珀色；最后节点及回放结束为完整静态连线 |

`measureSpatialLayout` 与本轮修改前的函数内容逐字一致；未增加观察器或测量回调。原有 Day 10 断言行全部保留，现有 V3.5 倾斜／接纳去重／离场清理逻辑继续运行。新增动效使用现有媒体偏好和可见性门控；请求等待期间不显示 Pipeline 节点或连接，不把回放时间解释成真实运行耗时。

## 通过结果

| 验证 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: |
| 全量离线 Pytest | 762 项 | 0 | 0 |
| Day 8 浏览器验收 | 25 组 | 0 | 0 |
| 完整 Day 10 浏览器验收 | 58 组 | 0 | 0 |
| 视觉／空间验收 | 10 组，29 个截图场景 | 0 | 0 |

Day 10 为原有 52 组加本轮 6 组，仍包括防重复提交、五轮门禁、失败不提交、幂等重放、三场景闭环、脱敏、草稿迟到隔离、单实例 Composer、精确定位和 V3.5 动效竞态。另执行了最新检查源码的定向复验：启动检查加上述 6 组，共 7 组；其中增强的伪元素减少动态效果断言已实际执行。这 7 组不额外累加到完整 Day 10 的 58 组。

Pytest 用时 25.89 秒，1 条既有 `LangChainPendingDeprecationWarning`。浏览器运行时异常 0、外部请求与云调用 0。测试使用本机 Edge CDP、本地 FastAPI 和明确的离线模型／检索替身，验证工程行为，不替代真实模型语义评估。具体浏览器版本、逐项结果、实际几何与动画证据及文件 SHA256 见 acceptance.json（历史附件 `acceptance.json`，已转本机归档）；原始 Pytest 输出见 pytest.txt（历史附件 `pytest.txt`，已转本机归档）。

## 实测与修复

- 真实 CDP 鼠标按下：按钮 y 从 `765.328125` 到 `766.328125`，释放恢复；宽高与工作区矩形均不变。禁用、触屏和减少动态效果下矩形保持原位。
- Pipeline 通过真实回放产生，检查 `getAnimations({subtree:true})` 中运行的 `pipeline-ink` 与伪元素 computed style；减少动态效果下另核对动画为 `none`、变换为静态。伪元素必须纳入动画查询范围，避免误判。
- 第一轮只点亮一槽；失败与响应丢失均不增加；同编号缓存重试只增加一次；第五轮五槽点亮，不能提交第六轮。
- 真实押金改善显示 `1000 → 1500`，只给旧值加删除线。首次确认和维持原条件没有虚假的被替代数值。失败时本轮徽标说明未提交，回应上沿仍对应原成功结果。
- 验收发现 `.score-delta` 的 `font` 简写会重置前面的 `font-variant-numeric`；已将统一数字规则放到相关简写之后，computed style 复验通过。

已查看 29 场景联系表（历史附件 `contact-sheet.png`，已转本机归档） 及桌面首轮、条件改善、失败 Trace、手机与 200% 布局放大原图。1440×900 首轮、第五轮和改善后的发送操作仍在未滚动首屏内；390px 触屏与 200% 放大无横向溢出，操作可达。代表效果见 条件改善界面（历史附件 `confirmed-improvement.png`，已转本机归档）。200% 为 CSS `zoom=2` 布局重排代理，不是仅文字放大。

## 复验命令与范围

命令在项目根目录执行，输出和缓存使用本轮独立目录。重新执行浏览器验收时需要换用空目录后缀。

```powershell
$env:PYTHONUTF8='1'
New-Item -ItemType Directory -Force .runtime/micro-polish-20261028/pytest-run | Out-Null
.\.venv\Scripts\python.exe -m pytest --basetemp=.runtime/micro-polish-20261028/pytest-run/temp -o cache_dir=.runtime/micro-polish-20261028/pytest-run/cache -o faulthandler_timeout=40
node scripts/check_day08_frontend.cjs --out .runtime/micro-polish-20261028/day08-out --runtime-dir .runtime/micro-polish-20261028/day08-browser
node scripts/check_day10_frontend.cjs --out .runtime/micro-polish-20261028/day10-final --runtime-dir .runtime/micro-polish-20261028/day10-final-browser
node scripts/check_layout_visual.cjs --out .runtime/micro-polish-20261028/visual-final --runtime-dir .runtime/micro-polish-20261028/visual-final-browser
```

本轮修改文件：`frontend-web/index.html`、`scripts/check_day10_frontend.cjs`、新增 `scripts/check_micro_polish.cjs`、验收索引及本目录。Day 8／V3.5／视觉脚本原有断言保持原样。业务 Spec、后端与既有历史证据不属于本轮修改；工作区原有修改保留，未执行 Git 写操作。

正式归档仅本目录 5 个文件，其余试跑截图和浏览器文件留在被忽略的 `.runtime/micro-polish-20261028/`，未覆盖历史归档。
