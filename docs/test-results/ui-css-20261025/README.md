# V2 卷宗限宽、药丸操作舱与 Trace 避让

> 2026-10-30 第一次整体优化收口：本报告为历史阶段记录，不代表当前界面。重复截图、测试输出及中间验收附件已移至本机忽略目录 `.runtime/optimization1-cleanup-20261030/docs/test-results/ui-css-20261025/`；迁移清单和 SHA-256 位于该归档根目录 `manifest.json`。下文附件数量与路径保留为当时记录，标注已转归档的文件不再随仓库提交；当前验收见 [表单反馈与视觉修复](../ux-feedback-20261030/README.md)。

> 2026-10-25 追加附件精简：本文保留历史验收结论和最终结果摘要；旧版截图、重复试跑及过程附件已清理。文中附件状态属于当时记录，当前保留范围以本提示为准。最新界面与验收见[最终任务分屏报告](../ui-task-layout-20261025/README.md)。


日期：2026-10-25。产品代码仅修改 `frontend-web/index.html` 的 `<style>`。通过修改前后的 SHA-256 比较，确认 style 之外的 HTML/JS，以及 Day 8、Day 10 两份现有测试文件均未改变，见 范围核对（附件已精简）。

## 样式结果

- 卷宗相位的外框最大宽度为 64rem（1024px），内容层最大宽度为 56rem（896px），二者居中。工作区本身不收窄，因此既有 wide/flow 判断、对弈桌比例和 SVG 测量继续生效。
- 只有带主操作的 `.contract-foot.has-contract-action` 使用药丸外观：最大宽度 52rem（832px）、居中、999px 圆角、细边框、半透明背景与阴影。手机改为 20px 圆角并允许换行；既有 flow 下的 `position:static` 保留。
- `.shell` 底部预留至少 160px，并叠加安全区。展开 Trace 时，纯 CSS 根据详情区最大高度增加留白；同时增加页面滚动定位的底部避让距离。未修改任何状态机、输入框实例、事件或测试逻辑。

## 最终验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 原有 Day 8 脚本 | 23 通过，0 失败，0 跳过 | 结果（历史附件 `day08-attempt01/browser-results.json`，已转本机归档） |
| 原有 Day 10 脚本 | 30 通过，0 失败，0 跳过 | 结果（历史附件 `day10-attempt02/day10/browser-results.json`，已转本机归档） |
| `tests/test_frontend_static.py` | 5 通过，1 条既有依赖警告 | 本轮终端实测，2.99 秒 |
| 独立视觉测量 | 宽度、居中、SVG 锚点和底部可用区域检查通过 | 尺寸与命中数据（附件已精简） |

本轮只改 CSS，未重跑全量后端 Pytest，未将 2026-10-22 的 652 项历史通过结果计作本轮实测。两份浏览器脚本和独立视觉测量的外网请求及运行时异常均为 0。测试运行目录与证据目录均独立创建，历史记录未覆盖。

Day 10 首次与其他检查并行启动时，在布局诊断尚未初始化时提前读取，停在 `assert.ok(measurements.diagnostic)`；保留了该轮目录。页面 JS 和测试脚本均未改，单独重跑后全部 30 项通过。

## 空间实测

| 场景 | 实测 |
| --- | --- |
| 1920×1080、1440×1080 卷宗 | 外框 1024px，内容 896px，操作舱 832px，三个中心均与工作区中心重合；仍为 wide |
| 390×844 卷宗 | 外框 362px，内容 360px，操作舱 320px，操作舱为 static，无横向溢出 |
| 1920×1080 对弈桌，滚动到底 | 输入框底边 738.88px、发送按钮底边 838.88px，Trace 顶边 1016px |
| 1920×1080 展开 Trace，滚动到底 | 底部留白 620px，输入框和发送按钮均完整位于 Trace 上方 |
| 1440×560 矮窗口 | 输入框和发送按钮均完整可见，发送按钮可命中 |
| 390×844 对弈桌，滚动到底 | 输入框底边 448.14px、发送按钮底边 564.52px，Trace 顶边 763.61px |
| 390×844 展开 Trace，滚动到底 | 底部留白 497.6px，输入框和发送按钮均完整可见且不被覆盖 |
| 200% CSS 布局放大代理 | 输入框和发送按钮均完整位于 Trace 上方，按钮命中正确 |

留白保证最下方控件可以完整滚动到控制台上方；固定浮层在其他滚动位置仍会覆盖其自身所在的视口区域。200% 放大使用 `document.body.style.zoom='2'`，不冒称浏览器仅文字放大。

代表截图：1920px 卷宗与药丸（附件已精简）、脱敏预览（附件已精简）、收拢后的 SVG 批注（附件已精简）、手机底部操作（附件已精简）、展开 Trace 的手机避让（附件已精简）。

## 运行命令

```powershell
node scripts/check_day08_frontend.cjs --out docs/test-results/ui-css-20261025/day08-attempt01 --runtime-dir .runtime/ui-css-20261025/day08-attempt01
node scripts/check_day10_frontend.cjs --out docs/test-results/ui-css-20261025/day10-attempt02 --runtime-dir .runtime/ui-css-20261025/day10-attempt02
.\.venv\Scripts\python.exe -m pytest -q tests/test_frontend_static.py --basetemp <本轮新临时父目录>/base -o cache_dir=<本轮新临时父目录>/cache
```

重跑时使用新的证据和运行目录；pytest 的临时父目录须先创建，不指向任何证据目录。
