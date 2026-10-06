# Day 2 回合 2：向量维度与知识库 API 实测

日期：2026-10-06（北京时间）。测试使用仓库 `.venv`；所有 Chroma 测试实例均在 `tmp_path` 或单独的 `.runtime/tmp` 验证目录中。未调用真实 SiliconFlow API，未触碰 `backend/chroma_db` 或原有 `.pytest_cache`，未修改 `requirements.txt`。

## 实际命令与测试结果

最终全量命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/pytest_tmp
```

最终输出：**43 passed in 6.99s**，退出码 0，无失败或跳过。覆盖 `test_health.py`、`test_kb_ingestion.py`、`test_kb_api.py`；`pytest.ini` 将默认缓存设为 `.runtime/pytest_cache`，最终运行没有 pytest 缓存或 ACL 警告。新增测试模拟空、512 维和 1536 维云端返回，均验证为包含期望 1024 与实际维度的 `ValueError`，错误不含合成密钥；还覆盖元数据维度不一致、旧集合维度元数据补录、空集合、非法 ID 污染、脱敏与请求边界。

过程中的复测记录：首次窄范围测试使用新路径时，`.runtime/pytest_tmp` 与 `.runtime/pytest_cache` 当时也出现 ACL 拒绝访问，结果 3 passed、11 errors；核验两目录位于仓库后清理并重新生成。下一次窄范围测试为 29 passed、2 failed，原因是更新 Chroma metadata 时重传了不可修改的 `hnsw:space`；修正后窄范围 **31 passed**。其后第一次全量 **42 passed**，调整“提前退租”mock 召回后窄范围 **31 passed**，补充空/污染集合测试后全量 **43 passed**；进一步确保 POST 只打开既有集合后，最终全量仍为 **43 passed**。早期失败未计为通过。

## 接口实测输出

使用 `.\.venv\Scripts\python.exe -c` 在独立验证目录运行 FastAPI `TestClient`，先请求空知识库，再用 mock 向量入库 32 条并请求接口。验证命令退出码 0；下表是实际响应的关键字段。验证目录在进程结束后清理。

| 请求 | 实际输出 |
| --- | --- |
| 入库前 `GET /api/kb/status` | HTTP 200；`indexed_count=0`，`is_ready=false` |
| 入库前 `POST /api/kb/search` | HTTP 503；`detail.code=KB_NOT_READY`，`indexed_count=0`，提示运行 `scripts/init_kb.py` |
| 入库后 `GET /api/kb/status` | HTTP 200；`indexed_count=32`，`is_ready=true` |
| 押金返还查询 | HTTP 200；`LAW-733, LAW-714, LAW-710, LAW-713`；`direct_basis_sufficient=false`，提示本章无直接押金返还条文，并需补充合同约定及其他依据 |
| 房屋维修查询 | HTTP 200；`LAW-712, LAW-704, LAW-713, LAW-732`；`direct_basis_sufficient=true` |
| 未经同意转租查询 | HTTP 200；`LAW-716, LAW-718, LAW-711, LAW-717`；`direct_basis_sufficient=true` |
| 提前退租通知查询 | HTTP 200；`LAW-730, LAW-722, LAW-707, LAW-711`；`direct_basis_sufficient=false`，提示本章没有适用于所有提前退租情形的统一通知天数或费用规定 |
| 含合成手机号与身份证号的维修查询 | HTTP 200；返回 `query=维修联系[手机号]身份证[身份证号]`，`top_k=2`；原号码未出现在响应中 |

检索返回均为 `LAW-703`～`LAW-734`，证据来源保留固定最高法 URL。mock 排序是离线测试结果，`direct_basis_sufficient` 仅表示本章是否为该问题提供直接条文依据，不能替代具体法律判断。真实云端向量的响应维度和排序仍需有凭据时单独集成验证。

## 临时目录与边界

本轮独立接口验证目录与 `.runtime/pytest_tmp`、`.runtime/pytest_cache` 在确认位于仓库内后清理。首次接口探针在 Python 进程仍持有 Chroma 文件句柄时清理失败；该进程退出后清理成功，随后独立探针退出码 0。原有受限 `.pytest_cache` 未访问或处理。只读 Git 状态与改动文件清单在本轮最终汇报中给出。
