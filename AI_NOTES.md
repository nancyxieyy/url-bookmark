# AI Collaboration Notes

## AI 分工

本项目使用 ChatGPT 进行需求拆解和方案讨论，使用 Codex 完成项目结构、数据模型、CRUD、标签、正文提取、页面、测试和文档。AI 负责提高实现速度，功能边界、异常规则、安全取舍和最终验收由我判断。

## 关键设计判断

### Bookmark 是核心实体，Markdown 是派生内容

用户首先需要确保网址不丢失，正文提取只是收藏后的增强能力。因此：

- URL 无效或指向受保护的本地网络时不创建收藏。
- URL 合法但抓取失败时仍保存 Bookmark。
- 抓取结果使用 `success`、`fetch_failed` 和 `extract_failed` 表达。
- 重新抓取失败时保留旧标题和正文。

### 控制 MVP 范围

主动放弃了 React、账号体系、向量搜索、LLM 摘要和 Playwright 动态抓取。普通 Jinja2 页面、数据库查询和静态 HTML 抓取已经能够完成题目要求。后来只在“正文属于什么主题”这个低风险、可由用户修改的环节加入 LLM 标签推荐。

### AI 推荐不等于 AI 自动分类

标签推荐会优先复用已有标签，只允许少量新标签。模型返回后，服务端仍会检查标签是否真的来自已有列表、去重并限制数量。前端不会默认勾选推荐项；只有用户点击建议并保存修改，标签才会写入数据库。

```text
Markdown → LLM 推荐 → 已有标签 + 少量新标签 → 用户确认 → 保存
```

推荐失败属于可选增强失败，不会修改 Bookmark 的抓取状态、正文或现有标签。

输入网址后不再跳转到编辑页。Web 表单先“抓取”，再在原位置展开标签下拉，AI 推荐也放进同一个下拉菜单；用户确认后才点击“收藏”。抓取阶段的数据标记为临时草稿，不出现在收藏列表、搜索或扩展标签接口中，超过 24 小时会自动清理。

搜索框使用短暂防抖后请求服务端并局部替换结果列表；标签下拉改变时立即执行同一流程。因此仍然能够搜索完整 Markdown 正文，又不需要用户点击按钮或承受整页刷新。

来源平台在 Bookmark 创建或网址修改时根据域名写入，已有记录由启动迁移补齐。首页平台按钮、标签和关键词共享同一套服务端查询参数：选择平台后，标签下拉只保留该平台实际使用的标签；排序可按平台正序/倒序、加入时间或最近修改切换。所有变化仍然只替换收藏结果区域，不进行整页跳转。

重复检测在网络抓取之前执行。URL 比较忽略不会改变服务器资源的片段、域名大小写和默认端口，但不随意删除查询参数。命中后复用已有 Bookmark，只允许用户调整标签，避免重复正文、重复模型调用和列表污染。

性能调整后，常见的完全相同 URL 会先使用数据库索引命中；普通网页避免首次 DNS/安全校验重复执行。抓取和 AI 推荐分别设置 8 秒与 10 秒上限，并只向模型发送正文前 4,000 字。慢站会更快降级为保留网址，而不是让收藏操作长时间无响应。

### 删除需要可恢复

首页卡片可以直接删除，但第一次删除只是写入 `deleted_at` 并移入回收站。回收站提供恢复和彻底删除，超过 30 天的数据在后续访问时清理。这个取舍让常用操作更短，同时给误删留下恢复空间。

完成 Web 端后，只增加了一个轻量浏览器扩展。它解决的是“复制 URL → 打开管理页 → 粘贴”的真实操作摩擦，而不是增加新的内容处理能力。

### 采集和管理属于不同场景

最初按照题目把产品理解为一个 Web 收藏夹。实际跑通后重新检查使用场景，发现用户产生收藏意图时通常就在目标网页上。因此把职责拆成：

```text
Extension = Capture
Web = Organize
Backend = Store + Extract
```

扩展读取当前标签页并调用 JSON API；搜索、编辑、正文查看和重新抓取继续留在 Web 端。正文提取只在后端实现一次。

扩展的精细保存也使用“自动抓取 → 用户确认 → 收藏”两阶段流程：点击工具栏图标时立即开始抓取，不再要求用户在弹窗里重复点击。标签交互与 Web 端保持一致，统一为“第一行新增标签 + AI 推荐 + 已有标签复选 + 完成”的多选下拉，不提供逗号分隔输入。弹窗同时保留可选备注和最近三条收藏；删除仍然只是移入同一个 30 天回收站。

### 正文展示和特殊平台回退

数据库继续保存 Markdown 原文，详情页则用禁用原始 HTML 的渲染器生成安全 HTML，避免把 `#`、链接和列表符号直接显示给用户。通用提取在精确模式无结果时会尝试召回率更高的模式，再回退到页面简介。

YouTube 观看页会限制云服务器访问并经常返回 HTTP 429，因此对公开视频使用元数据接口保存视频标题、频道和原始链接。这提高了收藏成功率，但不会把不存在的字幕或视频转录伪装成正文。

### URL 抓取需要安全边界

服务器请求用户填写的 URL 可能产生 SSRF 风险。因此只接受 HTTP/HTTPS，并检查本机、私网、链路本地和保留地址；每次重定向后重新校验，同时设置超时、重定向次数和响应大小限制。

## 实际发现并纠正的问题

### 1. SQLModel 与 Python 3.14 注解兼容

关系字段最初被 SQLAlchemy 解析成字符串形式的 `list['Bookmark']`，只有执行第一次 Bookmark CRUD 时才触发 mapper 错误。集成测试暴露问题后，调整模型注解，使关系可以正确初始化。

### 2. 测试导入路径

第一轮 pytest 只完成了文件发现，却无法导入 `app`。补充 `pytest.ini` 的项目路径配置后，测试才实际运行到业务逻辑。

### 3. 公开网站被误判为内网地址

实际收藏 `https://programmercarl.com/` 时，安全规则错误拦截了公开网站。排查 DNS 后发现本地代理返回 `198.18.0.8`，属于代理常用 Fake-IP 网段。最终规则允许“域名解析到 Fake-IP”，但继续拒绝用户直接输入该 IP，并加入两个相反方向的测试防止回归。

### 4. 浏览器测试选择器不唯一

浏览器测试最初按文字查找 `Browser Test`，同时匹配到标签链接和下拉选项，触发 Playwright strict mode 错误。页面行为正确，但测试定位方式不可靠。改用 `role=link` 后，完整交互验收通过。

### 5. 自定义 Server URL 需要匹配浏览器权限

Extension Settings 第一版已经允许修改 Server URL，但 Manifest 仍然只永久授权 Render 域名。实际加载未打包扩展验收时检查到，自定义服务即使保存成功也会被 Chrome 的 host permission 拦截。最终没有申请永久 `<all_urls>`，而是把 HTTP/HTTPS 放入 `optional_host_permissions`；用户保存自定义地址时，扩展只申请该具体 origin 的权限。

### 6. Web AI 推荐和插件 API 不能共用同一种认证要求

现有 Web 标签下拉和插件都调用 `/api/bookmarks/{id}/tag-suggestions`。如果简单给全部 `/api` 挂 Bearer 依赖，Web 页面即使已经通过 Basic Auth，也会在生成推荐时收到 401。最后把实际推荐逻辑提取为共享函数：Web 使用 Basic Auth 保护的 `/bookmarks/{id}/tag-suggestions`，插件继续使用 Bearer 保护的 `/api/...`，没有要求同一个请求同时携带两种凭证。

### 7. 旧式字段补丁不足以支持后续 Schema 演进

原来的启动逻辑通过检查列名补充四个字段，没有 migration 版本，也无法证明失败后是否会错误推进。考虑到后续还会增加 Token、URL identity 和 Snapshot，最终选择轻量自定义 `schema_migrations`，而不是立即引入 Alembic。Migration 集中在独立模块、有固定顺序，每个版本的 DDL 和版本记录在同一事务中执行；测试覆盖空数据库、部分旧 Schema、重复运行和故意失败回滚。

## Feature：版本化 Migration 与 Extension API Token

### 为什么做

后续 Browser DOM、URL identity 和 Snapshot 都会改变 Schema，继续使用启动时零散的字段补丁会难以验证升级顺序。与此同时，Basic Auth 是网页登录方式，不适合保存在插件中，因此需要一个权限受限、可立即吊销的独立 Token。

### AI initial proposal

AI 建议当前规模使用集中式自定义 `schema_migrations`，为每个版本提供独立事务；认证则把 Web Basic Auth 和 Extension Bearer Token 分开，并只给现有插件所需的 API 挂 Token 依赖。

### Problem / disagreement

实现认证时发现，Web 标签下拉也在调用 `/api/.../tag-suggestions`，不能直接把这个地址改成只接受 Bearer。扩展设置完成后又在实际 Manifest 验收中发现，自定义 Server URL 与固定 Render host permission 不一致。

### Human decision

保留共享的标签推荐业务函数，但为 Web 和插件提供分别受 Basic/Bearer 保护的入口。自定义服务器不申请永久全站权限，而是在用户保存设置时申请该具体 origin 的 optional host permission。Token 明文只展示一次，数据库只保存 hash。

### Validation

自动测试验证新旧 SQLite、幂等 migration、失败不推进版本、Token 生成/重新生成、权限边界和 CORS。随后启动真实 Uvicorn 验证 HTTP 状态，并使用 Chromium 加载未打包扩展验证 storage、Bearer header、401 UI 和运行时错误。

## 验证方式

- 单元测试验证 URL 校验和正文提取成功/失败分支。
- 集成测试验证抓取草稿、首页标签确认、即时搜索、标签、备注、Markdown 渲染、编辑、软删除、恢复、彻底删除和过期清理。
- API 测试验证扩展两阶段收藏、备注、最近收藏、删除、标签读取和扩展来源 CORS。
- 对 Manifest JSON、扩展 JavaScript 和 PNG 图标进行静态检查。
- 使用 Chromium 以未打包扩展方式实际加载 Manifest V3 service worker 和 popup，操作抓取、推荐标签、备注、收藏和最近收藏删除，并检查运行时错误。
- 外部请求通过 mock 隔离网络波动。
- 使用真实网址验证 `programmercarl.com` 的标题和 Markdown 提取。
- 使用临时 SQLite 数据库启动真实 Uvicorn，验证 `/health` 公开、Web 未登录 401、Basic Auth 设置页 200、插件 API 无 Token 401 及正确 Bearer 200。
- 使用未打包 Manifest V3 扩展验证 Server URL/API Token 写入 `chrome.storage.local`、请求携带 Bearer、Token 错误提示和 service worker/popup 无异常。
- 使用无头 Chromium 验证卡片/列表切换、整卡点击、详情按钮、Markdown 渲染、备注、首页删除确认、回收站恢复和彻底删除，并检查浏览器错误。
- 使用拦截后的结构化模型响应验证推荐标签的展示、点选和保存，避免测试依赖真实 API 费用和网络稳定性。

这些验证用于确认“代码能运行”和“功能符合产品规则”是同一件事，而不是只接受 AI 给出的实现结果。
