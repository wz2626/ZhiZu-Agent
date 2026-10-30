# V3.5 角色徽章与空间微交互验收

> 2026-10-30 第一次整体优化收口：本报告为历史阶段记录，不代表当前界面。重复截图、测试输出及中间验收附件已移至本机忽略目录 `.runtime/optimization1-cleanup-20261030/docs/test-results/v35-20261028/`；迁移清单和 SHA-256 位于该归档根目录 `manifest.json`。下文附件数量与路径保留为当时记录，标注已转归档的文件不再随仓库提交；当前验收见 [表单反馈与视觉修复](../ux-feedback-20261030/README.md)。

2026-10-28。实施范围为前端展示和配套浏览器验收；后端 API、状态提交、算分、五轮上限与脱敏契约未在本轮修改。工作区原有 V2/V3 与后端审计改动继续保留。

## 结果

| 验证 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: |
| 全量离线 Pytest | 762 | 0 | 0 |
| Day 8 浏览器验收 | 25 组 | 0 | 0 |
| Day 10 浏览器验收 | 52 组 | 0 | 0 |
| 视觉／空间验收 | 10 组、29 个截图场景 | 0 | 0 |

Day 10 保留原有 43 组业务与安全验收，新增 9 组 V3.5 验收。上述不同类型检查分列，不能相加当作单元测试数量。Pytest 用时 23.00 秒，出现 1 条原有 `LangChainPendingDeprecationWarning`，无测试失败。浏览器未记录运行时异常或外部请求，测试未调用真实云模型。

原始统计与动效实测值见 acceptance.json（历史附件 `acceptance.json`，已转本机归档），Pytest 原始输出见 pytest.txt（历史附件 `pytest.txt`，已转本机归档）。测试采用 Windows 本机 Edge CDP 与本地 FastAPI；模型和检索使用明确标注的离线替身，协商图、提交规则及 HTTP 路径实际执行。它验证工程行为，不替代真实模型语义质量或所有浏览器／辅助技术兼容性评估。

## 实施内容与审阅裁决

- 新增共用 `RolePersona` 内联 SVG 组件，28px 固定槽位，分别表示模拟房东与草稿参谋。角色装饰有 `aria-hidden`，SVG 不可聚焦；未插入新的交互控件。
- 房东展示状态来自等待状态、最后一次成功接纳的条件变化及五轮结束状态。第一次失败保持待命；已有成功结果后的失败保留上次成功姿态。维持原条件不会被解释成拒绝或强硬。草稿参谋只表示准备中／已接纳草稿，不模拟语音或模型隐藏推理。
- 改善／确认采用青色，退步采用暖红，调整／维持采用中性色。一次性光效同样遵循该语义，不用整卡震动或心理表情解释分数。
- 只有房东回应、已确认条件和左侧建议三个明确白名单外壳拥有独立装饰面。鼠标位置按帧写入 CSS 变量，倾角限制为 ±2°；业务正文、按钮、法条、Composer、批注与定位外壳不变形。
- 主舞台原有实际面板转场被 260ms 背景层落位取代。网格只在演练区域内，占位为零，透明度 4.5%；正文和输入框始终为平面。
- 已采纳 Kimi 的两项清理修正：统一取消 rAF、清空指针缓存及变量、使旧回调失效；离开演练时清除旧 `resultArrived` 和角色／草稿提示，避免 `v-show` 返回时重播。
- 接纳去重使用会话与请求编号，草稿另含上下文、条款和 `draft_request_id`。第一次收到合法缓存重放仍可提示；隐藏期间接纳只更新静态事实，重返演练不会补播。背景入场与结果提示分开管理。
- 动效仅在鼠标主指针、fine + hover、未要求减少动态效果且页面可见时工作。触屏、运行期媒体偏好变化、失焦、页面隐藏、退出相位、场景重置、卸载均清理待执行工作；选中文字及键盘聚焦时暂停倾斜。等待装饰只作两次短脉冲。

本轮未增加 WebP、大立绘、弹簧惯性、正文透视、实时语音或后端字段。审阅中“后续增强纳入本轮”的一句与上下文冲突，按已确认范围排除。

## 防止“只出现 class 就算通过”的证据

- CDP 真实鼠标输入后，房东装饰层实测 `rx=0.95deg`、`ry=1.89deg`，computed transform 为非静态 `matrix3d`；前后外壳矩形完全一致。已确认条件和建议装饰面也分别验证实际响应。
- `getAnimations()` 检测到 `arena-settle` 正在运行，背景有变换矩阵，实际业务面板 `transform=none`；等待结束后背景回到静态。
- 同一帧内先 move、再 leave/cancel/blur/visibilitychange/相位退出，经过后续两帧倾角仍为零；真实 Vue 卸载后，保留的已分离装饰节点也没有被旧回调写回。
- 运行期 reduced-motion 与 coarse pointer 变更清除倾角，并阻止后续倾斜／背景入场动画。touch、pen、非主指针、文本选择及键盘焦点也有反向覆盖。
- 真实缓存重放覆盖“首个响应丢失后首次接纳”及“相同请求第二次递送被轮次校验拒绝”，均保留既有幂等规则。失败保持上次姿态、第五轮即结束、草稿失效撤销提示、隐藏响应不补播均通过。

浏览器回归仍保留：双击锁、隐私二次遮蔽与重新确认、原文精确偏移、12px 避让、双向定位、单实例 Composer、迟到草稿隔离、三场景闭环、同请求重试、失败不提交、第六轮禁发、真实 Trace 和复制回退。

## 视觉复核

已检查 29 场景联系表（历史附件 `contact-sheet.png`，已转本机归档），并打开首轮／第五轮、失败、长短合同、草稿预览、390px 触屏及 200% 布局放大原尺寸截图。另检查三块装饰面的实际 hover 截图。没有发现新增遮挡、布局错位或不可达操作；1440×900 首轮和第五轮发送按钮仍在未滚动首屏内。

一处实施中修正：建议卡的装饰面最初会被不透明子卡片遮住，已调整装饰层层级并实际截图检查，仍保持 `pointer-events:none`。移动端视觉脚本现同时启用触屏模拟，确保验证 coarse pointer 规则，而不只是缩小窗口；手机快捷键徽标隐藏。200% 使用 CSS `zoom=2` 触发布局重排，不冒充浏览器仅文字放大。

代表图：草稿与角色静态就绪（历史附件 `arena-proposal.png`，已转本机归档）。其余截图、实际 HTTP Trace 与浏览器临时文件保留在忽略目录 `.runtime/v35-20261028/`。本轮正式归档仅 5 个文件，不覆盖 Day 9／Day 10 或 V3 历史证据。

## 命令与文件

以下命令在项目根目录执行。证据目录必须为空；复验时应更换目录后缀。`--basetemp` 仅指向本轮一次性临时子目录，不能指向证据目录。

```powershell
$env:PYTHONUTF8='1'
New-Item -ItemType Directory -Force .runtime/v35-20261028/pytest-run | Out-Null
.\.venv\Scripts\python.exe -m pytest --basetemp=.runtime/v35-20261028/pytest-run/temp -o cache_dir=.runtime/v35-20261028/pytest-run/cache -o faulthandler_timeout=40
node scripts/check_day08_frontend.cjs --out .runtime/v35-20261028/day08-out --runtime-dir .runtime/v35-20261028/day08-browser
node scripts/check_day10_frontend.cjs --out .runtime/v35-20261028/day10-final --runtime-dir .runtime/v35-20261028/day10-final-browser
node scripts/check_layout_visual.cjs --out .runtime/v35-20261028/visual-final --runtime-dir .runtime/v35-20261028/visual-final-browser
```

本轮修改：

| 文件 | 作用 |
| --- | --- |
| `frontend-web/index.html` | SVG 角色、事实状态、一次性提示、装饰层倾斜、背景落位和统一清理 |
| `scripts/check_day10_frontend.cjs` | 原验收后接入 V3.5 模块，记录实际动效证据 |
| `scripts/check_v35_interactions.cjs` | 新增 9 组动效正反向、竞态与角色接纳验收 |
| `scripts/check_layout_visual.cjs` | 移动窗口同时启用触屏模拟 |
| `docs/test-results/README.md` | 追加本轮报告入口 |
| `docs/test-results/v35-20261028/` | 本报告、精简 JSON、Pytest 输出和两张图 |

未进行 Git 提交。业务 Spec 与后端文件不属于本轮改动。
