# Day 2 回合 1：法条知识库实测记录

日期：2026-10-06（Asia/Shanghai）。测试使用仓库 `.venv`，Chroma 测试目录均位于 pytest 临时目录或 `.pytest_cache`，未使用正式 `backend/chroma_db`。本次未安装依赖，未改动 `requirements.txt`。

## 数据核对

- 固定 JSON 文件含第 703～734 条连续 32 条，ID、中文条号、法名、章节、完整正文、标签、固定来源 URL 和 `2026-10-05` 核对日期均经单测校验。含多段的条文在单条记录中保留全部段落。
- 法条正文对照工信部网站刊载的[《中华人民共和国民法典》全文](https://fjca.miit.gov.cn/zwgk/zcwj/wjfb/art/2020/art_9f0ef44677164c5eb3a5585bf82a07cb.html)第十四章；指定的[最高人民法院来源页](https://www.court.gov.cn/zixun/xiangqing/233181.html)可由网页搜索索引识别，但本次直接打开超时，因此没有声称逐字从该页直连核对。`verified_date` 是按本轮指定值写入的元数据。
- 押金返还没有这 32 条中的直接规定。押金相关标签只帮助定位返还租赁物、正常损耗与保管责任条文，不表示这些条文直接规定押金返还。

## 执行命令与结果

统一测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_cache/tmp
```

开发过程中实际运行 8 次：首次因 `embedding.py` 语法错误在收集阶段失败；修复后 22 passed；调整数据标签时遗漏 JSON 逗号导致 10 failed、12 passed；修复后 22 passed；新增污染数据测试时 Chroma 的 `update` 因未传入向量试图调用默认模型并被沙箱拒绝，结果 1 failed、23 passed；补传测试向量后 24 passed；补充云端响应与密钥保护单测后 25 passed；补充模型标识隔离后，最终 **25 passed in 5.95s**，无跳过。最终全量包含 Day 1 `test_health.py` 和本轮 `test_kb_ingestion.py`。

命令行自检在隔离目录执行两次：

```powershell
.\.venv\Scripts\python.exe scripts/init_kb.py --mode mock --persist-dir .pytest_cache/day02-round01-verified --verify-queries
.\.venv\Scripts\python.exe scripts/init_kb.py --mode mock --persist-dir .pytest_cache/day02-round01-verified --verify-queries
```

两次均退出码 0，统计如下：

| 执行 | before_count | inserted_count | updated_count | total_count | embedding_mode |
| --- | ---: | ---: | ---: | ---: | --- |
| 首次 | 0 | 32 | 0 | 32 | mock |
| 再次 | 32 | 0 | 32 | 32 | mock |

## 五个问题的 Top-3 召回

以下为上述脚本两次运行时一致的实际顺序。每项来源 URL 均为 `https://www.court.gov.cn/zixun/xiangqing/233181.html`。

| 查询主题 | Top-3 条号与 ID | 核验 |
| --- | --- | --- |
| 押金扣留返还 | 第733条 `LAW-733`、第714条 `LAW-714`、第710条 `LAW-710` | 仅相关条文；**没有押金返还的直接依据** |
| 房屋维修责任 | 第712条 `LAW-712`、第704条 `LAW-704`、第713条 `LAW-713` | 命中维修义务及维修费用核心条文 |
| 擅自转租解约 | 第716条 `LAW-716`、第718条 `LAW-718`、第717条 `LAW-717` | 命中未经同意转租的核心条文；具体情形还需核对第718条 |
| 不定期租赁通知期 | 第730条 `LAW-730`、第722条 `LAW-722`、第707条 `LAW-707` | 命中第730条；法条用语为“合理期限之前通知”，没有固定天数 |
| 危及安全或甲醛超标解约 | 第731条 `LAW-731`、第711条 `LAW-711`、第730条 `LAW-730` | 命中第731条；须核实租赁物确实危及安全或健康 |

测试还验证了 scenarios 文件不会被加载、非法证据 ID 被过滤、空查询报错、集合出现非权威 ID 时拒绝入库或检索、不同向量模式或模型不能混用、云端查询前的手机号及身份证号正则遮蔽、云端接口响应顺序与异常中的密钥保护，以及证据正文和来源从权威 JSON 重新构建。真实 SiliconFlow API 调用未运行；mock 召回排序和分数不代表云端模型表现。
