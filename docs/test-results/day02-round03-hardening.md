# Day 3 前置底座加固实测（Day 2 回合 3，计划 Commit #5）

日期：2026-10-07（北京时间）。代码基线为 `c44af4a`，关联本次修复的 Commit **待提交**。本轮只处理已核实的 5 组问题及 N1/N4，不开发 Day 3 新业务功能。

## 环境、命令与最终结果

所有 Python 命令均使用仓库 `.venv`；实际 `--version` 为 **Python 3.12.13**，项目 Chroma 版本为 1.5.9。未安装或升级依赖，未修改 `requirements.txt`，未使用全局 Python/pip。测试使用合成配置、mock 与模拟云响应，不调用真实 SiliconFlow API，不访问真实个人信息或密钥；Chroma 数据均位于 pytest 的 `tmp_path`。

全量命令（3 次运行均相同）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
```

最终输出：

```text
........................................................................ [ 69%]
...............................                                          [100%]
103 passed in 11.35s
```

退出码 **0**，无失败、跳过或警告。覆盖 `test_health.py`、`test_kb_ingestion.py`、`test_kb_api.py`；原 Day 2 回合 2 为 43 项，本轮新增 60 个参数化用例，合计 103 项全部通过。

## 针对性覆盖与实际通过行为

| 项目 | 通过测试验证的行为 |
| --- | --- |
| 严格云向量元素 | 有限 int/float 接受；True/False、字符串数字、None、NaN、正负 Infinity 抛出清晰 ValueError，异常不含合成密钥 |
| 非有限距离 | NaN、正负 Infinity 在算分前被拒绝，不产生伪满分；API 映射为 503 KB_NOT_READY |
| 零向量与零分 | 纯标点、Emoji、零宽字符返回 `[]`；服务测试断言不调用 Chroma query；过滤零/负分，0.01 的正分仍保留 |
| 扩展脱敏 | +86/86 前缀、3-4-4 空格/短横线格式、15 位及尾号 X/x 的 18 位身份证成功遮蔽；不校验 MOD11-2，合成 18 位号码仍被遮蔽 |
| 非敏感数字边界 | 样例 16/18 位银行卡号、19 位订单号、12 位金额、日期及法条编号保持原样；不截取长数字串中的手机号/身份证子串 |
| 统一密钥判定 | 配置完整性和 auto 向量模式对空值、大小写/空白占位值、英文/中文占位片段给出一致结果 |
| 损坏库降级 | 伪造非 SQLite 文件后 GET 返回 200、未就绪、计数 0；POST 返回 503 KB_NOT_READY；原损坏文件内容未被替换 |
| 存储异常边界 | 客户端构造、取集合、读 ID 各阶段注入 InternalError、DatabaseError、Chroma 包装的 ValueError，均安全降级；诊断文本不进入响应 |
| 检索阶段异常 | 状态检查之后的集合异常及向量维度异常返回 503 KB_NOT_READY；模拟云调用 RuntimeError 返回 503 UPSTREAM_EMBEDDING_ERROR，密钥不进入响应 |
| 单客户端与缺库边界 | 正常 POST 仅构造一次 PersistentClient；缺库时不构造客户端、不创建目录；已有空目录请求后仍为空 |

上述损坏数据库、异常数值、集合错误和上游失败均为**故障注入**，不表示真实开发知识库或云服务发生同样故障。真实云端服务连通性和排序未做集成验证。

## 实际失败与修复过程

1. 首次：**47 passed、56 errors、58 warnings in 2.87s**，退出码 1。已有 `.runtime/pytest_tmp` 无法扫描/删除、`.runtime/pytest_cache` 无法写入，均为 Windows ACL 拒绝访问；依赖 `tmp_path` 的用例在 setup 阶段未运行。这次不计为测试通过。
2. 核验两个清理目标的绝对路径均位于仓库且不是重解析点后，使用原生 PowerShell `Remove-Item -LiteralPath ... -Recurse -Force` 清理。普通权限尝试被拒绝；随后受控提升权限清理这两个指定目录成功，未修改其他目录的 ACL。
3. 第二次：**102 passed、1 failed in 12.19s**，退出码 1。故障注入的损坏文件在首次 GET 中触发 Chroma InternalError；Chroma 缓存了部分初始化的 Rust System，随后 POST 的构造/内部清理抛出缺少 `bindings` 的 AttributeError。
4. 修复：已有 SQLite 文件在进入 Chroma 前以 `mode=ro` 连接并执行 `PRAGMA quick_check`；损坏或不可读文件先降级，避免将其交给 Chroma 造成部分初始化缓存。SQLite 连接显式关闭；正常客户端也按请求关闭。最终第三次全量为上述 **103 passed**。

## 文档、只读 Git 与临时目录

README 保留 Day 1 的 11 项与 Day 2 的 43 项记录，补充本次 103 项；Spec 00 增补模块名映射，Spec 01 同步检索和错误响应契约。Chain-01 I02 回填为已核实的 `c44af4a`，I03 标待提交，过程摘要保留真实失败与故障注入说明。

Git 仅执行带 `--no-optional-locks` 的 status/log/diff 等只读检查；所有者检查通过单次命令的 `-c safe.directory=D:/AgentDev/ZhiZu-Agent` 参数处理，未持久修改 Git 配置。最终提交由开发者执行。

最终 pytest 进程退出后，核验绝对路径和重解析点属性，再以原生 PowerShell 成功删除本次使用的 `.runtime/pytest_tmp` 与 `.runtime/pytest_cache`。`Test-Path` 对两个目录均返回 **False**，退出码 0；未清理此前存在的其他 `.runtime` 内容，未触碰 `backend/chroma_db` 或旧 `.pytest_cache`。本轮没有额外创建独立测试目录。
