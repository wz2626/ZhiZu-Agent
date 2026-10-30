# 桌面三栏等高调整

> 2026-10-30 第一次整体优化收口：本报告为历史阶段记录，不代表当前界面。重复截图、测试输出及中间验收附件已移至本机忽略目录 `.runtime/optimization1-cleanup-20261030/docs/test-results/ui-equal-height-20261021/`；迁移清单和 SHA-256 位于该归档根目录 `manifest.json`。下文附件数量与路径保留为当时记录，标注已转归档的文件不再随仓库提交；当前验收见 [表单反馈与视觉修复](../ux-feedback-20261030/README.md)。

> 2026-10-25 追加附件精简：本文保留历史验收结论和最终结果摘要；旧版截图、重复试跑及过程附件已清理。文中附件状态属于当时记录，当前保留范围以本提示为准。最新界面与验收见[最终任务分屏报告](../ui-task-layout-20261025/README.md)。


日期：2026-10-21。产品代码仅修改 `frontend-web/index.html`：增加桌面样式与左、中两个面板类名，未修改任何 JavaScript、右栏样式或已有测试脚本/断言。

## 实现

- 仅在宽度至少 1101px 的三栏布局启用；1100px 及以下保留原有布局。
- 左、中栏取消原固定高度，按 Grid 行高拉伸。对这两栏使用 `contain: size`，让右栏继续决定行高，避免左、中长内容反向撑高右栏。
- 左、中正文使用纵向 Flex；合同输入/脱敏预览填充剩余高度，已提交文本保留长文滚动；风险空状态在剩余空间居中，风险卡片保留内容高度。
- 左、中头部及页脚不收缩，页脚贴底。右栏既有 R2.1 固定/自然流机制原样保留。

与本轮起点逐字比较，全部内联 JavaScript 一致；SHA256 为 `31a78a8406ffd426026ede067b33ec6a6eecc15e73101ff2101ce6d218cfd24c`。差异仅为 13 行桌面 CSS 和两个 section 的类名，见 HTML 差异（附件已精简）。原 README、两套浏览器脚本、共用目录保护模块及四份已有命名修改文档的八项文件哈希保持一致，见 修改前哈希（附件已精简）。

## 回归结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 全量 pytest | 收集 652 项，652 passed，0 failed，0 skipped，22.93 秒；1 条既有依赖警告 | 日志（历史附件 `pytest.txt`，已转本机归档） |
| Day 8 原有断言，附加只读几何采样 | 20 passed，0 failed，0 skipped | 结果（历史附件 `browser-day08-attempt01/browser-results.json`，已转本机归档）、日志（附件已精简） |
| Day 10 原脚本直接执行 | 26 passed，0 failed，0 skipped | 结果（历史附件 `browser-day10-unmodified-attempt02/day10/browser-results.json`，已转本机归档）、日志（附件已精简） |
| 修改前 HTML 对照 | 原 Day 10 的 26 组通过 | 对照结果在 `.runtime/ui-equal-height-20261021/browser-day10-baseline-control/`，未写入历史证据目录 |

Day 9 补验 11 组是 Day 10 的子集，不重复相加。外部请求、云调用和浏览器运行异常均为 0。审查使用离线替身；没有运行真实云审查、云入库或云评估。测试需要 Windows 本机回环许可，测试内的外网阻断保持有效。`git diff --check` 通过。

## 几何与视觉检查

临时测量器放在 `.runtime/ui-equal-height-20261021/run-with-layout-probe.cjs`，只在内存中给原截图函数追加读数，不修改原脚本或断言。它记录了 12 份截图前样本，其中 11 份为桌面样本、1 份为窄屏记录；桌面样本的三栏顶边、底边差均为 0px，左、中页脚均贴住各自容器内部底边，输入/预览和中栏空状态检查通过。

| 状态 | 左栏高 | 中栏高 | 右栏高 |
| --- | ---: | ---: | ---: |
| 输入、预览、已分析，右栏固定模式 | 760px | 760px | 760px |
| 复制失败回退文本框显示，右栏自然流 | 1275.45px | 1275.45px | 1275.45px |
| 第五轮完成，右栏保持自然流 | 1034.58px | 1034.58px | 1034.58px |

测量源：Day 8 样本（附件已精简）、Day 10 样本（附件已精简）。这些几何样本不额外计入原有 20/26 组通过数。

将本轮直接回归的 11 个右栏布局样例与阶段 A 最终数据逐项比较，模式全部相同，高度差全部为 0px，包括 760px 固定模式、992.89px 自然流、输入框拉高、200% CSS 缩放代理及 390px 窄屏，见 右栏高度对照（附件已精简）。没有为了等高而缩短右栏。

已查看输入、脱敏预览、长合同定位、复制失败回退、第五轮、矮窗口、窄屏及 200% CSS 布局缩放代理截图。移动端未强制等高；200% 代理不代表原生“仅文字放大”验收。

## 附加流程超时记录

带额外两帧等待的 Day 10 几何采样运行在第五轮后等待重新进入固定模式时超时，因此该次组合运行没有完成全部 26 组，不能记为通过；日志保留（附件已精简）。超时前采集到的几何断言均已通过。

随后用完全未改的原 Day 10 脚本运行新页面，26 组通过；另用修改前 HTML 做对照，也得到 26 组通过。旧版记录与本次记录都显示：复制回退会触发自然流锁定，原截图流程中一次瞬时 viewport 变化使其重新评估。额外两帧等待改变了截图与 resize 的时序。证据支持该超时属于临时组合测量的时序影响，未发现此次 CSS 改变 R2.1 的证据；没有修改 R2.1 或削弱原断言来处理此问题。

## 截图入口

- 桌面输入与居中的空状态（附件已精简）
- 脱敏预览填充（附件已精简）
- 自然流三栏等高，复制回退显示（附件已精简）
- 矮窗口自然流三栏等高（附件已精简）
- 200% CSS 布局缩放代理（附件已精简）
- 390px 移动端（附件已精简）

## 复验方式

从仓库根目录运行现有命令，每次使用新的输出与临时目录，不能复用本报告的非空证据目录。

```powershell
$equalHeightRun = [guid]::NewGuid().ToString('N')
$equalHeightTemp = Join-Path ([System.IO.Path]::GetTempPath()) ('zhizu-equal-height-' + $equalHeightRun)
New-Item -ItemType Directory -Path $equalHeightTemp | Out-Null
.\.venv\Scripts\python.exe -m pytest --basetemp="$equalHeightTemp/base" -o "cache_dir=$equalHeightTemp/cache" -o faulthandler_timeout=40
node scripts/check_day08_frontend.cjs --out "docs/test-results/equal-height-$equalHeightRun/day08" --runtime-dir "$equalHeightTemp/day08"
node scripts/check_day10_frontend.cjs --out "docs/test-results/equal-height-$equalHeightRun/day10" --runtime-dir "$equalHeightTemp/day10"
```

本轮未修改后端、业务状态或测试断言，未覆盖既有证据，未提交 Git。

## 2026-10-25 附件精简

经项目负责人要求，删除 19 张中间尝试或非代表性截图，保留“截图入口”所列 6 张。所有几何采样、右栏高度对照、最终结果、失败日志和 Trace 均保留；几何 JSON 中的截图名称仍表示当时的采样标识，不代表每张历史截图仍作为附件保存。本次未重新执行测试，原验收结论不变。文件从 43 个减为 24 个，删除记录见 清理清单（历史附件 `../evidence-cleanup-20261025.json`，已转本机归档）。
