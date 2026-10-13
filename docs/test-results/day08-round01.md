# Day 8 回合 1：三栏看板、前置脱敏与离线资源实测

日期：2026-10-13（北京时间）。代码基线 `c574f7ca2a0f10f09246d6fa5edeb2501f667c91`（Day 7），本轮关联代码 Commit **待提交**。本报告依据实际命令输出与合成数据检查，不代表完整原始聊天归档或法律语义质量评估。

## 交付与范围

- `frontend-web/index.html` 为无构建工具的 Vue 3 单文件三栏工作台：脱敏原文、风险与证据卡片、协商准备区。右栏提供角色/场景切换和本地草稿，谈判 HTTP 接口仍待接入；没有虚构房东回复、轮次或分数。
- 浏览器先正则遮蔽中国手机号与15/18位身份证号为 `***`，展示可编辑预览；用户确认后才能提交。编辑会撤回确认，提交复查发现新号码时先遮蔽并要求重新确认。
- 请求与左栏使用同一份确认后的脱敏快照。`original_clause` 精确子串匹配、分段文本插值高亮；重复原句可切换，渲染后调用 `scrollIntoView`，未匹配时明确提示。
- 使用 `/api/review/analyze-detailed`；`needs_review`、HTTP错误或坏JSON均不会被解释为无风险。
- Vue `3.5.13`、TailwindCSS browser `4.1.13` 下载至 [vendor](../../frontend-web/vendor/README.md)，保留许可证、来源、大小及SHA-256。HTML使用本地相对路径；后端新增只服务该目录的 `/vendor` 路由，使用绝对项目路径，不受启动目录影响。

初轮按用户要求使用CDN，本轮按收尾要求本地化。Kimi审计绿灯为用户转述，尚无原始报告；本次未重新执行Kimi审计，也不将一个注入用例上升为零XSS保证。

## 环境与证据口径

Windows；Python `3.12.13`（仓库 `.venv`）；Node `v24.14.0`；无头 Edge `155.0.4283.45`。使用CDP与Node内置WebSocket，无额外npm依赖。

浏览器加载当前HTML和vendor文件，使用本机合成HTTP响应，未改写页面资源路径。新建浏览器配置目录、禁用缓存，拦截并拒绝所有非本机页面请求，以验证冷启动不依赖CDN。错误响应、无匹配条款、HTML事件属性均为**故障注入**，不是实际云端事故或真实法律结论。

**本轮浏览器18项分组检查通过；Python为23项pytest通过，两者独立统计。** 前轮的 `18 passed, 1 warning in 2.02s` 来自 `tests/test_health.py`；当时浏览器只有关键路径汇总输出，不能把该pytest输出当成18项浏览器证据。本轮已将浏览器断言分成可复跑、逐项输出的18组。

## 实际命令与结果

在仓库根目录执行；Windows本机socket/浏览器检查经受控提升运行，测试不调用真实云端凭据。

```powershell
node scripts/check_day08_frontend.cjs
# 18 passed, 0 failed, 0 skipped; external requests: 0; real cloud calls: 0.

.\.venv\Scripts\python.exe -m pytest -q tests/test_health.py tests/test_frontend_static.py --basetemp=.runtime/pytest_day08_final --junitxml=.runtime/day08-pytest/pytest.xml
# 23 passed, 1 warning in 2.82s

node --check scripts/check_day08_frontend.cjs
git --no-optional-locks diff --check
# 退出码0；Git仅提示现有LF/CRLF策略，无空白错误。
```

两组测试原始输出通过 `Tee-Object` 保存：[浏览器stdout](day08/browser-stdout.txt)、[结构化结果](day08/browser-results.json)、[pytest stdout](day08/pytest-stdout.txt)。测试退出码均为0，没有失败、跳过或测试错误。唯一pytest警告为既有LangGraph `JsonPlusSerializer` 的 `LangChainPendingDeprecationWarning`，未隐藏。

新增静态路由测试5项：HTML只引用两个本地固定版本脚本；两个脚本在其他工作目录启动时仍返回正确JavaScript MIME和原始字节；缺失文件及越过vendor的路径返回404。既有健康、配置保密、首页、CORS等18项继续通过。

## 无头浏览器18项结果

每行对应持久化脚本的一组实际断言；多个断言可属于同一组，不冒称18个独立pytest用例。

| ID | 检查 | 结果 |
| --- | --- | --- |
| 01 | 冷缓存本地Vue/Tailwind加载、模板挂载；外网页面请求被禁止 | 通过 |
| 02 | 桌面1440px有三个面板和三列网格 | 通过 |
| 03 | 打开脱敏预览尚无分析请求 | 通过 |
| 04 | 11位手机号及+86、横杠格式被遮蔽 | 通过 |
| 05 | 15位、18位数字及X结尾身份证号被遮蔽 | 通过 |
| 06 | 未确认预览时提交禁用 | 通过 |
| 07 | 编辑预览立即撤销确认 | 通过 |
| 08 | 新增号码在提交复查时遮蔽，不发请求，要求重新确认 | 通过 |
| 09 | 请求体逐字等于确认的脱敏预览，无合成敏感标识原值 | 通过 |
| 10 | 双击提交仅产生一次分析请求 | 通过 |
| 11 | 精确高亮两处重复原句，可切换当前位置 | 通过 |
| 12 | 调用smooth `scrollIntoView`，左栏实际滚动 | 通过 |
| 13 | 原句未匹配时显示提示，不生成猜测高亮 | 通过 |
| 14 | 风险卡片同步右栏对应协商建议 | 通过 |
| 15 | 合成HTML/事件属性保持纯文本，未插入图片且事件未执行 | 通过 |
| 16 | 390px手机单列布局，无横向溢出 | 通过 |
| 17 | needs_review、HTTP422、坏JSON均显示失败，无旧结果或原始input回显 | 通过 |
| 18 | 重试返回预览，必须重新确认 | 通过 |

浏览器运行异常0；页面尝试访问外网资源0；真实云端聊天/向量调用0。合成号码仅用于测试夹具，结果归档不保存合同请求体或真实个人信息。

## 截图与观察

截图均来自本轮运行，使用合成合同和模拟分析结果：

- [输入态](day08/day08-input-desktop.png)：桌面三栏、隐私说明与分析入口。
- [脱敏预览](day08/day08-preview-desktop.png)：号码遮蔽、编辑后确认撤回。
- [跨栏高亮](day08/day08-highlight-desktop.png)：原句黄色高亮、左栏滚动、中栏选择与右栏建议联动。
- [手机布局](day08/day08-mobile.png)：单列布局；注入HTML以文本高亮，没有执行。

## 收尾与未验证范围

输出和截图归档后，仅清理本轮创建的 `.runtime/day08-*` 文件/浏览器配置，以及明确列出的Day8 pytest临时目录。删除前检查绝对路径均在仓库 `.runtime` 内且没有重解析链接。保留云端向量库、`.env`、其他轮次资料和根许可证。可复跑脚本 `scripts/check_day08_frontend.cjs`、`tests/test_frontend_static.py` 随代码保留。

真实云端分析、谈判HTTP接入、Day9回放/导出及三场景端到端联调本轮未验证。离线保证限于前端资源与交互，后端云端功能仍需外网。没有执行全量Python回归或全面安全测试。

过程摘要和待补原始记录见[链3索引](../prompt-history/chain-03-web-board/README.md)。本轮未暂存或提交；最终以 `git --no-optional-locks status` 汇报工作区。
