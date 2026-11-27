# 第三方软件与许可证声明

PullSpool 自身的源代码以 **MIT** 许可证发布，见 [LICENSE](LICENSE)。
本文件列出运行时镜像中包含的第三方组件、许可证和获取完整许可证文本的位置。
各组件仍归其各自版权所有者所有；第三方许可证不改变 PullSpool 自身代码的 MIT 授权。

完整许可证原文放在 [LICENSES/](LICENSES/)。容器基础镜像自带的
`/usr/share/licenses/`、`/usr/share/common-licenses/`、`/usr/share/doc/` 中的许可证文件随镜像一并保留。

> 本文件用于满足许可证归属与再分发声明，不构成法律意见。若二次分发镜像，请保留本文件与
> `LICENSES/` 目录。

---

## 1. 运行时镜像与系统组件

| 组件 | 版本 / 标签 | 许可证 | 上游 |
|---|---|---|---|
| aria2 | 1.37.0（Alpine 3.20 包） | **GPL-2.0-or-later** | https://github.com/aria2/aria2 |
| Caddy | 2.11.9（`caddy:2-alpine`） | **Apache-2.0** | https://github.com/caddyserver/caddy |
| nginx | 1.27.5（`nginx:1.27-alpine`） | **BSD-2-Clause** | https://nginx.org/ |
| Alpine Linux | 3.20 | 各软件包各自许可证 | https://alpinelinux.org/ |
| Python | 3.12（`python:3.12-slim-bookworm`） | **PSF-2.0** | https://www.python.org/ |
| Debian bookworm（Python 基础镜像） | bookworm-slim | 各软件包各自许可证 | https://www.debian.org/ |
| Node.js | 22（仅构建阶段，不进入运行时镜像） | **MIT** | https://nodejs.org/ |
| tini | Alpine 3.20 | **MIT** | https://github.com/krallin/tini |
| iptables | Alpine 3.20 | **GPL-2.0-or-later** | https://www.netfilter.org/ |
| su-exec | Alpine 3.20 | **MIT** | https://github.com/ncopa/su-exec |
| ca-certificates | Alpine 3.20 | **MPL-2.0** | https://github.com/alpinelinux/ca-certificates |
| musl libc | Alpine 3.20 | **MIT** | https://musl.libc.org/ |
| BusyBox | Alpine 3.20 | **GPL-2.0-or-later** | https://busybox.net/ |
| apk-tools | Alpine 3.20 | **GPL-2.0-or-later** | https://gitlab.alpinelinux.org/alpine/apk-tools |
| zlib | Alpine / nginx | **Zlib** | https://zlib.net/ |
| OpenSSL | Alpine / nginx | **Apache-2.0** | https://www.openssl.org/ |

说明：

- `pullspool-backend`、`pullspool-frontend`、`pullspool-aria2`、`pullspool-caddy`
  分别基于上述基础镜像构建；基础镜像中的其他软件包保留各自许可证。
- Caddy 的 Go 模块依赖及其版本见上游 `go.mod`；Caddy 以 Apache-2.0 分发。
- nginx 镜像包含的 `nginx-module-*` 子包也保留在镜像的 `/usr/share/licenses/nginx-*` 中。

### aria2 / GPL-2.0 源码提供

aria2 以 **GPL-2.0-or-later** 分发，PullSpool 未修改 aria2 源码。对应源码可从：

- https://github.com/aria2/aria2/releases/tag/release-1.37.0
- https://git.alpinelinux.org/aports/tree/community/aria2

获取。自该镜像分发之日起三年内，如需要完整对应源码，也可通过项目 Issue 联系我们获取。
完整 GPL-2.0 文本见 [LICENSES/GPL-2.0.txt](LICENSES/GPL-2.0.txt)。

---

## 2. 后端 Python 运行时依赖

以下为生产镜像 `pullspool-backend` 中实际安装的 Python 包（含传递依赖）：

| 包 | 版本 | 许可证 |
|---|---|---|
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| SQLAlchemy | 2.1.9 | MIT |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache-2.0 |
| aiosqlite | 0.22.1 | MIT |
| alembic | 1.20.1 | MIT |
| annotated-doc | 0.0.7 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| argon2-cffi | 25.1.0 | MIT |
| argon2-cffi-bindings | 26.2.0 | MIT |
| attrs | 26.1.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.1 | BSD-3-Clause |
| fastapi | 0.165.0 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| greenlet | 3.5.6 | MIT AND PSF-2.0 |
| h11 | 0.16.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| multidict | 7.2.1 | Apache-2.0 |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| pip | 25.0.1 | MIT |
| propcache | 0.5.4 | Apache-2.0 |
| psutil | 7.2.2 | BSD-3-Clause |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic | 2.14.4 | MIT |
| pydantic-settings | 2.16.3 | MIT |
| pydantic_core | 2.50.5 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| starlette | 1.10.0 | BSD-3-Clause |
| typing-inspection | 0.4.5 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.6 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |
| yarl | 1.25.1 | Apache-2.0 |

Python 标准库及解释器本身由 **PSF-2.0** 覆盖，见 [LICENSES/PSF-2.0.txt](LICENSES/PSF-2.0.txt)。

---

## 3. 前端运行时依赖与内置资源

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| Vue | 3.5.46 | MIT | 运行时框架 |
| Pinia | 3.0.4 | MIT | 状态管理 |
| Vue Router | 4.6.5 | MIT | 路由 |
| Inter（`@fontsource-variable/inter`） | 5.3.0 | **OFL-1.1** | 自托管字体 |
| Lucide | 图标路径 | **ISC** | 手写 SVG 图标来源 |

- Inter 字体以 OFL-1.1 授权，许可证与字体版权声明见 [LICENSES/OFL-1.1.txt](LICENSES/OFL-1.1.txt)。
- Lucide 图标为 ISC 授权，见 [LICENSES/ISC.txt](LICENSES/ISC.txt)。

### 仅构建/开发期使用（不进入运行时镜像）

Node.js 22、Vite、`@vitejs/plugin-vue`、TypeScript、`vue-tsc`、Playwright、
`@types/node` 等只用于构建或测试。它们不随 `pullspool-frontend` 的 nginx 运行时镜像分发。

---

## 4. 完整许可证文本

| 文件 | 覆盖的许可证 |
|---|---|
| [LICENSES/MIT.txt](LICENSES/MIT.txt) | MIT（项目自身及 MIT 依赖） |
| [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt) | Apache-2.0（Caddy、aiohttp、OpenSSL 等） |
| [LICENSES/GPL-2.0.txt](LICENSES/GPL-2.0.txt) | GPL-2.0（aria2、BusyBox、iptables 等） |
| [LICENSES/OFL-1.1.txt](LICENSES/OFL-1.1.txt) | SIL Open Font License 1.1（Inter） |
| [LICENSES/ISC.txt](LICENSES/ISC.txt) | ISC（Lucide） |
| [LICENSES/BSD-2-Clause.txt](LICENSES/BSD-2-Clause.txt) | BSD-2-Clause（nginx） |
| [LICENSES/BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt) | BSD-3-Clause（uvicorn、psutil 等） |
| [LICENSES/MPL-2.0.txt](LICENSES/MPL-2.0.txt) | MPL-2.0（ca-certificates） |
| [LICENSES/PSF-2.0.txt](LICENSES/PSF-2.0.txt) | PSF-2.0（Python、aiohappyeyeballs 等） |
| [LICENSES/MIT-0.txt](LICENSES/MIT-0.txt) | MIT-0（cffi） |
| [LICENSES/Zlib.txt](LICENSES/Zlib.txt) | Zlib（zlib） |

如果某个基础镜像中的软件包未在镜像内附带许可证文件，可通过上表中的上游链接获取。

---

## 5. 包级许可证与版权声明

除上面的通用许可证全文外，运行时依赖的**逐包许可证/版权文本**保存在：

- `THIRD_PARTY_LICENSES/python/`：生产后端镜像内的 Python 包
- `THIRD_PARTY_LICENSES/frontend/`：Vue、Pinia、Vue Router、Inter

这些文件保留了各包自己的版权行和许可证原文；`LICENSES/` 中的文件是可复用的
标准许可证全文。两者应一起随源码或镜像二进制分发。
