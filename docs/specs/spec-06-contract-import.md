# Spec 06：Word/PDF 合同导入（2026-11-03 合议定稿）

## 1. 边界

采用MIT许可的python-docx 1.2.0及pdfplumber 0.11.10（pdfminer.six 20260107）。POST /api/contracts/parse仅将原文件送到自有服务离线提取，不导入聊天、Embedding、检索或审查服务，不归档合同，不创建业务会话。浏览器先脱敏再首次可见渲染，用户点击原有分析按钮才提交当前可见快照。上传前常驻说明此区别。OCR、子进程、账号和持久化不在范围。

## 2. HTTP与限额

严格X-Interaction-Version:4；multipart/form-data中恰有一个file，零普通字段，扩展名仅.docx/.pdf且与实际内容一致。Request手动解析，不能使用File依赖提前读取，也不能使用路由级async with form自动关闭已转交的文件。max_part_size只约束非文件字段，不是文件限额；spool_max_size只决定临时存储切换。

精确POST路由使用实际receive字节计数上限11MiB，文件实际大小上限10MiB；不缓存整个请求体，不接收压缩Content-Encoding。其余JSON接口维持256KiB及原结构检查。接收期限60秒，接收/解析总并发2，读取前准入，超额503 PARSER_BUSY，无无限队列。HTTP/1.1提前拒绝可加Connection:close；HTTP/2不添加连接专用头。前端兼容结构化503及连接中断，不自动重传。

只接受标准结尾的浏览器multipart请求（boundary长度1～70，终止标记后仅可有CR/LF，无任意epilogue）。receive检查终止标记，截断时在表单解析器仍拥有临时文件期间抛受控错误，确保未完成part也关闭。

PDF最多50页（有界枚举至第51页即拒绝）；DOCX最多2000 ZIP条目、累计实际展开50MiB、单XML10MiB、XML深度64/节点100000、异常压缩比1000:1、表格嵌套深度8。拒绝重复关键条目、非法路径、宏、DTD/实体及无效主文档类型，不extractall、不访问外部关系。清洗前累计文字100000，单页布局对象100000、累计表格单元格20000；超限报错不发布部分正文。

## 3. ParseJob所有权与存活性

FORM_READING：HTTP拥有FormData/文件/槽位；中断或异常由HTTP清理。手动form()的MultiPartException和被转换的HTTPException(400)均映射受控反馈。

STARTING：任务接管前仍归HTTP；受管任务创建并注册成功即转交ParseJob。RUNNING：任务拥有文件/槽位；HTTP只等待，不在finally关闭或释放。DONE/FAILED：实际工作已结束后唯一清理文件及槽位；未开始工作的受管任务若取消也须清理。run_in_threadpool不暴露executor.submit/Future；不得把取消的asyncio.Task.done()当成底层线程结束。受管任务的HTTP等待用shield隔离原生取消；工作包装器的实际完成标识及幂等清理守卫是最终依据。测试覆盖AnyIO scope、原生Task.cancel、接收中断、线程启动前/后取消及提交失败，资源恰好清理一次。

任务接管采用先登记、关闭的启动门、创建任务、登记完成回调、最后开门的顺序；任一步失败均撤销登记、禁止工作启动并取消已创建任务，文件/槽位仍由路由唯一清理。默认及eager任务工厂都不得越过未开启的门；覆盖登记部分成功后抛错、create_task失败、回调登记前/后抛错。

使用run_in_threadpool，无外层wait_for硬超时、不abandon线程。20秒协作deadline在打开前后、每页/每表/每批次检查；超期不发布成功，但单个库调用无法强制中断。两个解析线程均卡死可能使解析槽位持续占用，恢复可能需重启；重启会清空练习会话与审查上下文。禁止自动重启、自动归还未结束槽位或无限补线程。不承诺硬超时、硬内存隔离或保证20秒响应。

## 4. 提取与清洗

DOCX按正文顺序交替遍历段落和表格，包含常见自动编号、合并单元格去重、嵌套表格；不按文本值去重。发现修订/文本框/嵌入正文等无法可靠处理的结构报INCOMPLETE_EXTRACTION。页眉页脚文字不混入正文，存在时提示人工核查。图片内文字未提取应提示；纯图片文档报扫描错误，不声称完整提取。

PDF逐页检查文字量/分布、图片覆盖、轮廓和乱码，不仅检查首页。全部正文扫描报SCANNED_DOCUMENT，部分扫描报INCOMPLETE_EXTRACTION且给1-based pages，不返回text；单页异常不跳过。空白页可略过，logo/签名图片不直接等同扫描。大幅正文图片伴少量边缘字仍不能当可完整读取。判定为规则启发式，非完整性证明；复杂多栏/不可读正文保守拒绝。

doc-extract-v2：正文外大图不再仅因内部缺字就判扫描。对缺少可读文字层的大图执行有界栅格排布检查（不是OCR）：源图最多400万像素/压缩数据10MiB，受支持原始/Flate/JPEG/JPX编码，Flate按声明行容量有界解压，最多256×256灰度采样，以重复文字行带作为疑似文字信号。正文充足且图形无文字信号可回填并始终提示图片文字未提取；正文很少但全部位于可检查的图形外也可回填。只有边缘文字/无正文的大幅图片仍拒绝（正文少于80字且图覆盖15%以上即检查，不用页眉字数冒充正文）；图内疑似文字、无法安全解码或容量不符，正文即便充足也返回INCOMPLETE_EXTRACTION并给页码。未支持的透明/图像蒙版或显式Decode数组按未知处理，不以未合成的原始像素放行。至少80个正文字符覆盖图像可视为已有文字层。该规则不能证明图像无条款，也不声称能识别logo语义；倾斜/低对比图片仍须人工核查，未知大图不通过增加外部正文绕过。

含AcroForm交互表单的PDF首版保守拒绝，避免把表单值遗漏后当完整正文；Word内容控件/简单字段/数学对象等未支持正文也拒绝。pdfminer原始诊断不进入应用日志。无编号部件的普通Word允许，存在未支持的编号格式时拒绝并提示重新保存。

表格统一为“| 列1 | 列2 |”，不强推首行为表头；保留空位，转义单元格竖线/明确单元格内换行。PDF用bbox排除同区域正文字符，再按页面位置合并，不能全文与表格各追加一次。未知表格提取失败报错，不静默丢弃。

统一LF和NFC，清理无意义控制字符、行尾空白、多余空白段。不得全文NFKC、删除全部空格、改金额日期或模型清洗。只去除高置信重复边缘页码/装饰标题，不删除实质合同条款；不做跨页激进拼接。乱码以替代符/cid/异常映射检测，不按中文比例拒绝。

v2清洗名单明确为BOM U+FEFF、零宽空格U+200B、WORD JOINER U+2060、软连字符U+00AD及原Cc规则（保留LF/TAB）；不按Cf整类删除。ZWNJ U+200C、ZWJ U+200D和其他有语义的格式字符保留，码点计数口径不变，保护姓名连接和emoji。

清洗后原文>20000报422 TEXT_TOO_LONG，禁止截取前5000。10～5000正常回填；5001～20000完整回填并按当前可见脱敏正文派生over_limit，禁用分析；少于10字提示不足。API char_count计提取原文，编辑框按Array.from及Python len的Unicode码点口径计当前脱敏正文；不得UTF-16 maxlength静默切断。手工删减后提醒只分析保留文本。

## 5. 共享隐私逻辑分隔

复用fold-codepoint-v1、Unicode数字/全角X映射及原文索引；升级policy版本和启动备用规则。手机号保留3-4-4分组及可选国家码，身份证保留6-8-4及连续15位。不识别逐字空格、不做导入join。

H=[空格、TAB、NBSP、窄NBSP、全角空格]，分组间SEP为1～4个H或一个连字符及左右各0～4个H，或左右各0～4个H夹一个CRLF/LF/CR。最多一个逻辑换行，不跨空白行或|。候选前后不得通过上述分隔紧邻数字，防止从更长数字串截片；使用有界、前后端一致检查，不无限向远处找数字。普通金额/日期/表格列、12位串、“2500 元 2500 元”、5000空白及现有连字符样本必须回归，pattern<=1024。首帧、待应用文本、错误和日志不得展示原始号码；姓名地址仍人工核对。

## 6. 响应

成功200：{status:success,text,char_count,document:{format,size_bytes,page_count,table_count},limits:{analysis_chars:5000,import_chars:20000},warnings:[{code,message,pages}],request_id,extractor:{name,version,policy_version}}。DOCX page_count=null。版本从已安装包读取，不写模糊版本。

失败：{detail:{code,message,retryable,pages,request_id,extractor,policy_version}}，格式尚未识别时extractor=null。request_id为服务端HTTP诊断UUID，不作业务幂等键，不记录正文/原文件名/路径/作者/堆栈。全部响应no-store。

400 INVALID_UPLOAD；413 FILE_TOO_LARGE/REQUEST_TOO_LARGE；415 UNSUPPORTED_FILE_TYPE/FILE_TYPE_MISMATCH；422 EMPTY_FILE/ENCRYPTED_DOCUMENT/CORRUPTED_DOCUMENT/UNSAFE_DOCUMENT/DOCUMENT_LIMIT_EXCEEDED/SCANNED_DOCUMENT/INCOMPLETE_EXTRACTION/UNREADABLE_TEXT/NO_EXTRACTABLE_TEXT/TEXT_TOO_LONG；503 PARSER_BUSY；504 PARSE_TIMEOUT/UPLOAD_TIMEOUT；500 PARSE_FAILED。版本错误复用409 INTERACTION_VERSION。结构错误不可重试，网络/繁忙可人工重试，无自动云回退。

## 7. 单卡前端状态机

按钮在示例按钮左侧，同层次；编辑表面接受单文件拖入，局部浅色悬停，防止浏览器导航，不影响文字拖动。IME期间禁止开始上传。状态idle/loading/awaiting_apply/applying/success/error/cancelled，与review phase分开。

选择后直接loading，永不先清空原文。成功先校验并本机脱敏；revision已改→同一张awaiting_apply卡（已编辑），未改但原文非空→同卡（非空），未改且原文空→回填。点应用再次检查epoch/revision/IME/编辑上下文；IME内收到响应只暂存安全文字，compositionend后重判。实际开始新上传、示例、历史/条款切换退出编辑、取消、卸载均执行统一失效：epoch递增、abort、清自身spinner和候选；旧finally不能改新任务。普通右栏展开不作废导入。

替换确认基线为本张卡片展示/更新时的confirmRevision，与上传起始revision分开。点替换发现正文再次修改时不写rawText，更新同一卡片提示及基线，要求下一次明确点击；若又有编辑继续重核。上传期间已有编辑仅在首次显示卡片时纳入基线，不平白多要求一次确认。成功提示只报告本次候选计数加应用时终扫新增计数，不用历史累计maskCounts冒充本次数量；无命中只说明本次未发现规则可识别号码，不保证没有个人信息。

仅安全文字写响应式状态，首次render前完成遮蔽；规则未就绪不导入。原始文件名不直接展示（可能含PII）。成功摘要如“已提取6页 · 4,386字 · 含2个表格，请核对隐私与条款”；DOCX不伪造页数。Loading不编造百分比，取消只表示停止等待/不回填。导入不分析、不覆盖submittedText/旧结果，不抢走其他面板焦点。

保持100vh App Shell，状态位在卡片内，长错误由现有面板滚动，计数在右、状态在左；移动/矮窗/200%下控件可达。提供aria-busy/status/alert、键盘文件入口。验收包括真实HTTP大文件/中断、无云调用、跨语言脱敏一致、首帧无PII、超限完整回填、混合扫描拒绝、取消资源所有权及旧工作台回归。
