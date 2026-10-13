# 固定版本前端运行时

下载日期：2026-10-13（北京时间）。页面从本目录加载 Vue 与 TailwindCSS browser 运行时，无需 npm 安装、构建或外部 CDN。由 FastAPI 的 `/vendor` 静态路由提供，HTML 使用 `./vendor/…` 相对路径。

| 文件 | 版本 | 来源 | 大小（字节） | SHA-256 |
| --- | --- | --- | --- | --- |
| `vue-3.5.13.global.prod.js` | 3.5.13 | [jsDelivr / Vue](https://cdn.jsdelivr.net/npm/vue@3.5.13/dist/vue.global.prod.js) | 157924 | `c459ba7cc8db65c982589fa5d64c7ff478877e8e5b0fd75683207cec6a4e89e8` |
| `tailwindcss-browser-4.1.13.js` | 4.1.13 | [jsDelivr / @tailwindcss/browser](https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.1.13) | 260856 | `9cad698b24b432ff797742dda999b82a111f87fe520afae40be92381d3d14890` |

JavaScript 按下载原件保存，未重打包或改写。两份文件与首轮浏览器验证所用的同版本下载文件逐字节一致。jsDelivr 的包入口可能附带头注释与 source map 注释；它们不是运行时依赖，验证中没有外网请求。

许可证随分发保留：[Vue MIT](vue-LICENSE.txt)、[TailwindCSS MIT](tailwindcss-LICENSE.txt)。许可证原始下载地址为 [vue@3.5.13/LICENSE](https://cdn.jsdelivr.net/npm/vue@3.5.13/LICENSE) 和 [tailwindcss@4.1.13/LICENSE](https://cdn.jsdelivr.net/npm/tailwindcss@4.1.13/LICENSE)。

离线保证范围是页面资源加载、脱敏与交互。真实合同分析仍调用本地后端，后端的云端聊天、向量服务需要相应网络和凭据。法条来源链接及 `/docs` 是用户主动打开的辅助入口，不属于工作台启动资源。

更新版本时同步修改 HTML 引用、来源、校验值与静态资源测试，再运行 `node scripts/check_day08_frontend.cjs`。
