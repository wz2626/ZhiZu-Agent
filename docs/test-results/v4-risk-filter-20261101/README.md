# 合同提醒：交互式风险筛选

附件精简（2026-11-01，开发者要求）：重复截图、中间对比图及旧机器验收附件已移出待提交目录，保存在本机忽略归档 `.runtime/evidence-tidy-20261101.zip`；下文历史实测结论保留，附件数不代表当前保留数。


2026-11-01。仅调整前端列表呈现，不改变审查结果、风险计数、原句坐标、协商状态或接口。

- `activeRiskFilter = ref('ALL')`；`filteredResults` 从完整 `results` 派生，风险列表改为渲染派生集合。
- 高／中／低／说明为原生按钮，提供 hover、选中底色、`aria-pressed` 与 `aria-controls`。同等级再次点击或点“待关注”恢复全部，全部包含 NONE 说明项；待关注数仍只计算风险项。
- 计数始终来自完整结果。零数量仍可筛选，展示空状态和复原入口。
- 筛选不改选中条款、原句高亮、解读、输入或轮次；被隐藏的当前条款给出提示。新分析和版本切换复位为 ALL，不继承旧版本筛选。
- 手机保持在风险面板，不因筛选跳转；平板保留可见的筛选结果与上下文提示。

浏览器专项使用 HIGH／MEDIUM／NONE 混合合成数据及 LOW=0，验证分级、切换、复原、零结果、原生 Enter 激活、当前选择保留、手机、无 POST 及新版本复位。[桌面中风险筛选](risk-filter-medium.png)、手机筛选（附件已移至本机归档）、零结果（附件已移至本机归档）。

Day8 共 **37 passed／0 failed／0 skipped**，见 [browser-results.json](browser-results.json)；前端静态 **5 passed**，1 条既有 LangChain 弃用预警。原有定位、IME、草稿、焦点、对比度和 App Shell 检查保留。本轮未运行完整 Day10、后端或真实收费模型调用。

实现：`frontend-web/index.html`；新增 `scripts/check_risk_filter.cjs`，接入 `scripts/check_visual_polish.cjs` 并补版本复位断言。无 Git 写操作。
