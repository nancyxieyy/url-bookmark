# URL Bookmark

这是一个网址收藏夹作业。Web 端用于搜索和整理收藏，轻量浏览器扩展用于在浏览网页时快速采集。后端会自动读取标题、提取主要正文并保存为 Markdown；本地使用 SQLite，线上使用 Supabase PostgreSQL 持久化收藏、标签和正文。

这个项目最重要的产品规则是：**抓取失败不等于收藏失败。**

## 功能

- 粘贴 URL，自动提取标题和正文
- 使用 Trafilatura 识别主要内容并转换为 Markdown
- 新增、查看、编辑收藏，并在首页将收藏移入回收站
- 回收站保留删除内容 30 天，支持恢复和立即彻底删除
- 抓取前检测重复 URL；已收藏的网址直接带出现有标签供修改
- 为一个收藏添加多个标签，并按标签筛选
- 抓取成功后使用 LLM 推荐标签，由用户确认后再保存
- 为收藏添加可选备注，并可在详情页新增、修改或删除
- 在详情页按网页格式渲染 Markdown，而不是显示原始标记
- 输入关键词或选择标签时即时筛选，不需要额外点击“搜索”
- 收藏支持卡片与紧凑列表两种排版，整张收藏卡片都可进入详情
- 使用 `success`、`fetch_failed`、`extract_failed` 记录抓取状态
- 抓取失败时保留网址，之后可以手动重新抓取
- 使用 SQLite 在本地持久化数据
- 通过 Chrome/Edge 扩展抓取当前页面、确认推荐标签和备注，并显示最近三条收藏
- 使用快捷键直接把当前页面保存到 `Inbox`

## 设计说明

我把 Bookmark 作为核心实体，把 Markdown 正文作为收藏之后生成的增强内容。这样设计是因为，用户最核心的需求是先把网址保存下来，而正文抓取可能因为网络、反爬、登录墙或页面结构等原因失败。如果把“抓取成功”作为“收藏成功”的前提，用户反而可能因为一次临时错误丢掉原本想保存的网址。

因此，应用把“收藏”和“抓取”分开处理。URL 格式合法且不指向受保护的本地网络时，会创建 Bookmark 并记录抓取状态：

- 抓取成功：保存标题和 Markdown，状态为 `success`。
- 网页无法访问：仍保存网址，状态为 `fetch_failed`。
- 网页可以访问但无法识别正文：仍保存网址，状态为 `extract_failed`。
- 重新抓取失败：保留之前成功保存的标题和正文，只更新状态和错误原因。

技术上选择 FastAPI + Jinja2，是因为本项目重点是数据处理和抓取流程，不需要复杂的前端状态管理。SQLModel 用于描述 Bookmark、Tag 和它们的多对多关系；数据保存在 `data/bookmarks.db`，SQLite 不需要额外安装数据库服务，适合本地作业演示。

正文提取使用 Trafilatura，而不是直接对 HTML 调用 `get_text()`。后者通常会把导航栏、菜单、页脚和 Cookie 提示等非正文内容一起保存，而 Trafilatura 会先判断网页的主要内容区域，再输出 Markdown。

Web 端采用“抓取 → 确认标签 → 收藏”的两阶段交互。第一次只抓取并生成临时草稿，随后仍在首页原表单中显示标签下拉；AI 推荐也直接放在这个下拉菜单里，不再额外占用一块页面。用户点击“收藏”后草稿才进入“我的收藏”。放弃的草稿会在 24 小时后自动清理。

抓取前会先检查活动收藏中是否已有同一 URL。比较时忽略 `#fragment`、域名大小写和 HTTP/HTTPS 默认端口，但保留路径与查询参数。命中重复项时不会再次抓网页或调用模型，而是显示“该网址已收藏过”，并在原标签下拉中带出现有标签供修改。回收站里的记录不阻止重新收藏。扩展接口同样不会创建重复记录，而会合并本次选择的标签。

正文抓取成功后，后端会把标题、已有标签列表和 Markdown 前 4,000 字发送给 LLM。推荐结果不会自动写入数据库；用户点击建议并最终收藏后才会入库。服务端会再次校验模型输出，总推荐数最多 5 个，其中新标签最多 2 个。这个功能遵循：

> AI 提建议，人维护自己的分类体系。

抓取链路如下：

```text
输入 URL → URL 与网络目标校验 → 平台元数据回退 / 通用 HTTP 请求
         → 标题与页面简介 → 正文识别 → Markdown → Bookmark + Tags + Note
```

URL 抓取设置了请求超时、最多 5 次重定向和 5 MB 响应限制。每次重定向后都会重新检查目标地址，避免跳转到 localhost 或私网地址。针对本地代理常用的 `198.18.0.0/15` Fake-IP，只允许域名解析结果使用该网段，直接输入该 IP 仍会被拒绝。

为缩短等待时间，普通网页只执行一次首次网络目标校验，跳转后仍会逐次重新校验；HTTP 抓取最多等待 8 秒，AI 推荐最多等待 10 秒。重复 URL 会先利用 URL 索引精确匹配，只有大小写、默认端口或片段不同的情况才进入兼容比较。

在功能范围上，我主动放弃了 React、账号体系、向量搜索、LLM 摘要和基于 Playwright 的动态网页抓取。这些功能不属于题目要求的核心链路，而且会增加实现和运行复杂度。LLM 只用于低风险的标签建议，不负责自动分类。当前优先保证的是：

> 收藏 → 正文提取 → Markdown 保存 → 标签整理 → 搜索找回

删除使用软删除：Bookmark 会记录 `deleted_at`，不再出现在“我的收藏”和搜索结果中，但会在回收站保留 30 天。用户可以撤销删除，也可以主动彻底删除；超过 30 天的记录会在下一次访问首页或回收站时自动清理。这样既避免卡片上的误操作直接造成数据丢失，也不需要为这个作业额外维护定时任务。

在完成题目要求的 Web 管理端后，我额外实现了一个轻量浏览器扩展作为收藏入口。实际使用时，收藏意图通常发生在用户正在浏览目标网页的时候；“复制网址 → 打开收藏页面 → 粘贴网址”的操作链路偏长。因此扩展只负责采集，搜索、编辑、正文查看和重新抓取仍然留在 Web 端，避免维护两套完整界面。

```text
插件 = Capture
网页 = Organize
后端 = Store + Extract
```

## 技术结构

```text
浏览器 / Jinja2 页面
        ↓
FastAPI 路由与产品规则
        ├── SQLModel → SQLite（Bookmark / Tag）
        ├── Extractor → httpx → Trafilatura → Markdown
        └── Tag Recommender → DeepSeek API → 用户确认
```

```text
当前网页 → Chrome / Edge Extension → FastAPI JSON API
                                      ├── SQLite
                                      └── Trafilatura → Markdown
```

```text
app/
├── main.py                 # 页面路由与应用规则
├── models.py               # Bookmark / Tag 数据模型
├── database.py             # SQLite / PostgreSQL 连接与轻量迁移
├── schemas.py              # 抓取结果类型
├── services/extractor.py   # URL 校验、HTTP 获取与正文提取
├── services/tag_recommender.py # AI 标签推荐与输出校验
├── templates/              # Jinja2 页面
└── static/style.css        # 页面样式
tests/                      # 自动化测试与浏览器验收脚本
extension/                  # Chrome / Edge 扩展
data/                       # 本地数据库目录
AI_NOTES.md                 # 更详细的 AI 协作记录
```

## 安装与启动

推荐使用 Python 3.11 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8000>。

数据库会在第一次启动时自动创建在 `data/bookmarks.db`。该文件已加入 `.gitignore`，因此不会把本地收藏提交到仓库。

## 免费部署：Render + Supabase

线上部署使用 Render Free Web Service 运行 FastAPI，使用 Supabase PostgreSQL 持久化数据。本地开发仍默认使用 SQLite，不需要配置 Supabase。

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/nancyxieyy/url-bookmark)

部署时 Render 会根据 `render.yaml` 要求填写三个 Secret：

- `DATABASE_URL`：Supabase Dashboard 的 **Connect → Session pooler** PostgreSQL 连接串。建议使用 Session pooler，保留连接串中的 `sslmode=require`，不要提交到 GitHub。
- `APP_PASSWORD`：网页版访问密码，建议使用至少 16 位随机密码。
- `DEEPSEEK_API_KEY`：用于生成 AI 标签推荐；未配置时只有推荐功能不可用，收藏和正文抓取不受影响。

`DEEPSEEK_MODEL` 默认使用 `deepseek-v4-flash`。本地开发可以直接打开项目根目录中已被 `.gitignore` 排除的 `.env`，在 `DEEPSEEK_API_KEY=` 后填入密钥。

`APP_USERNAME` 默认为 `admin`。部署完成后，浏览器访问 Render 提供的固定 `*.onrender.com` 地址时会显示 HTTP Basic Auth 登录框。

部署配置会执行：

```text
Build: pip install -r requirements.txt
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health check: GET /health
```

应用会自动识别标准 `postgresql://` / `postgres://` 连接串并使用 psycopg 3。本地没有 `DATABASE_URL` 时继续使用 `data/bookmarks.db`。

## 安装浏览器扩展

扩展默认连接已经部署的 `https://url-bookmark.onrender.com`，不需要在本机启动 FastAPI。

Chrome：

1. 打开 `chrome://extensions`。
2. 开启右上角“开发者模式”。
3. 点击“加载已解压的扩展程序”。
4. 选择项目中的 `extension` 目录。

Edge 的步骤相同，扩展管理地址为 `edge://extensions`。

扩展提供两条路径：

- **精细保存**：点击扩展图标后先抓取当前页面，再确认 AI 推荐标签、已有标签和可选备注，最后收藏。
- **快速保存**：按 `Cmd/Ctrl + Shift + S`，直接把当前页面保存到 `Inbox`。如果快捷键和浏览器已有功能冲突，可以在 `chrome://extensions/shortcuts` 中修改。

弹窗底部显示最近三条收藏。标题可直接打开网页版详情，也可以在弹窗内把收藏移入回收站。

扩展只向后端发送当前页面的 URL、浏览器标题、标签和备注。正文抓取与 AI 标签推荐仍由 FastAPI 完成。对应接口为：

```http
GET /api/tags
GET /api/bookmarks/recent
POST /api/bookmarks/preview
POST /api/bookmarks/{id}/confirm
POST /api/bookmarks/{id}/delete
POST /api/bookmarks
POST /api/bookmarks/{id}/tag-suggestions
```

```json
{
  "url": "https://example.com/article",
  "title": "Article title",
  "tags": ["AI", "Reading"],
  "notes": "之后精读"
}
```

## 测试与验证

运行自动化测试：

```bash
pytest -q
```

测试覆盖：

- 无效协议和本机地址拦截
- 代理 Fake-IP 域名兼容与直接 Fake-IP 拦截
- 正文提取成功、YouTube 元数据回退和网页访问失败
- 抓取草稿、重复 URL 检测、备注、Markdown 安全渲染、首页下拉标签确认、即时搜索、标签筛选和编辑
- 卡片/列表切换、整张卡片进入详情和详情操作按钮布局
- 首页删除确认、回收站、撤销删除、彻底删除和 30 天自动清理
- 扩展两阶段收藏、AI 推荐、备注、最近三条、删除、JSON API 和扩展来源 CORS
- AI 推荐输出清洗、已有标签优先、数量限制和失败降级

外部网页请求在自动化测试中使用 mock，避免把网络波动误判成代码错误。

项目还包含实际运行过的浏览器验收脚本 `tests/browser_smoke.py`。它验证首页渲染、安全提示、抓取失败仍保存、标签、详情、编辑、首页删除确认、回收站恢复、彻底删除和浏览器控制台错误。`tests/ai_tag_browser_smoke.py` 另行验证 AI 推荐、点选和保存都在首页完成。运行方式：

```bash
python -m pip install -r requirements-dev.txt
playwright install chromium
uvicorn app.main:app --port 8765
```

保持服务运行，在另一个终端执行：

```bash
source .venv/bin/activate
python tests/browser_smoke.py
python tests/ai_tag_browser_smoke.py
```

保持后端运行时，还可以让 Chromium 真正加载未打包扩展并检查 service worker、popup、标签 API 和页面运行错误：

```bash
python tests/extension_smoke.py
```

## AI 使用说明

开发过程中我主要使用 ChatGPT 和 Codex。

ChatGPT 用于前期需求拆解和方案讨论，例如确定 Bookmark 与正文抓取是否应该绑定、异常状态如何划分、哪些功能属于本次 MVP，以及哪些功能应该主动放弃。

Codex 用于具体实现，包括项目结构、SQLModel 数据模型、CRUD、标签、正文提取服务、搜索、异常处理、页面、测试和文档。我先确定功能列表和产品规则，再实现各模块；每完成一个阶段都会运行测试或实际启动应用，而不是只根据生成的代码判断功能是否完成。

在 Web 端完成后，我重新从实际使用场景检查产品形态：产生收藏意图时，用户通常正在目标网页上，而不是已经打开收藏管理页。因此又把“采集”和“管理”拆开，增加了轻量扩展作为第二个客户端。扩展复用同一个后端和数据库，不在浏览器中重复实现正文提取。

AI 协作过程中出现过几个实际问题：

1. SQLModel 的关系类型在 Python 3.14 下被错误解析成 `list['Bookmark']`，导致应用第一次执行 CRUD 时 mapper 初始化失败。这个问题是在集成测试中发现的，最后通过调整注解方式解决。
2. pytest 9 没有自动把项目根目录加入导入路径，第一轮测试无法导入 `app`。补充最小的 `pytest.ini` 后，测试才真正执行到业务代码。
3. URL 安全校验最初把 `programmercarl.com` 拦截成内网地址。实际排查发现，本地代理把域名解析成了 `198.18.0.8`，这是代理使用的 Fake-IP。之后修改规则为：允许域名经代理解析到 Fake-IP 网段，但直接输入该 IP 仍然拒绝，并增加对应测试。
4. 浏览器测试第一次运行时，一个文本选择器同时匹配了标签链接和筛选下拉项。页面功能本身正确，但验收脚本不够精确；收窄为具有明确角色的链接选择器后，完整流程通过。

这些问题说明，AI 生成代码后仍需要通过测试、真实运行和具体输入来校正。AI 主要用于加快实现和补充思路，产品规则、异常策略、功能取舍和最终验收仍由我判断。更详细的记录见 `AI_NOTES.md`。

## 已知限制

- 通用抓取不执行 JavaScript，因此高度依赖客户端渲染的页面可能只能保存标题、页面简介或原始链接。
- YouTube 会优先使用公开视频元数据回退，避免服务器直接访问观看页时常见的 HTTP 429；这不会自动获取视频字幕或转录全文。
- 登录墙、付费墙、验证码和严格反爬网站可能抓取失败。
- 搜索使用 SQLite `LIKE`，没有分词、相关性排序或语义搜索。
- AI 标签推荐依赖 `DEEPSEEK_API_KEY` 和外部模型服务；请求失败时不会影响收藏数据。
- 标签名称目前区分大小写。
- 这是本地单用户作业，没有账号、权限和跨设备同步。
- Render 免费实例休眠后的第一次请求可能需要等待一段时间，扩展抓取也会受到这段冷启动时间影响。
