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

主动放弃了 React、账号体系、跨设备同步、云数据库、向量搜索、LLM 摘要和 Playwright 动态抓取。普通 Jinja2 页面、SQLite 查询和静态 HTML 抓取已经能够完成题目要求。

完成 Web 端后，只增加了一个轻量浏览器扩展。它解决的是“复制 URL → 打开管理页 → 粘贴”的真实操作摩擦，而不是增加新的内容处理能力。

### 采集和管理属于不同场景

最初按照题目把产品理解为一个 Web 收藏夹。实际跑通后重新检查使用场景，发现用户产生收藏意图时通常就在目标网页上。因此把职责拆成：

```text
Extension = Capture
Web = Organize
Backend = Store + Extract
```

扩展读取当前标签页并调用 JSON API；搜索、编辑、正文查看和重新抓取继续留在 Web 端。正文提取只在后端实现一次。

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

## 验证方式

- 单元测试验证 URL 校验和正文提取成功/失败分支。
- 集成测试验证新增、搜索、标签、编辑和删除。
- API 测试验证扩展收藏、标签读取和扩展来源 CORS。
- 对 Manifest JSON、扩展 JavaScript 和 PNG 图标进行静态检查。
- 使用 Chromium 以未打包扩展方式实际加载 Manifest V3 service worker 和 popup，并检查运行时错误。
- 外部请求通过 mock 隔离网络波动。
- 使用真实网址验证 `programmercarl.com` 的标题和 Markdown 提取。
- 使用无头 Chromium 验证页面渲染与完整交互，并检查浏览器错误。

这些验证用于确认“代码能运行”和“功能符合产品规则”是同一件事，而不是只接受 AI 给出的实现结果。
