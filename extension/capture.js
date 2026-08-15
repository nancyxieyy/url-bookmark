(() => {
  const FORBIDDEN_TAGS = [
    "script", "style", "noscript", "iframe", "object", "embed",
    "form", "input", "textarea", "select", "option", "button",
    "video", "audio", "source", "track", "canvas",
  ];
  const MAX_MARKDOWN_CHARS = 1_000_000;

  function absoluteWebUrl(value) {
    if (!value || value.startsWith("data:") || value.startsWith("blob:")) return "";
    try {
      const resolved = new URL(value, document.baseURI);
      return ["http:", "https:"].includes(resolved.protocol) ? resolved.href : "";
    } catch (_) {
      return "";
    }
  }

  function stripSensitiveNodes(root) {
    root.querySelectorAll(FORBIDDEN_TAGS.join(",")).forEach((node) => node.remove());
    root.querySelectorAll("[contenteditable]").forEach((node) => node.remove());
  }

  function matchesHost(...domains) {
    const host = location.hostname.toLowerCase();
    return domains.some((domain) => host === domain || host.endsWith(`.${domain}`));
  }

  function firstNode(root, selectors) {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      if (node) return node;
    }
    return null;
  }

  function cleanText(value) {
    return (value || "").replace(/\s+/g, " ").trim();
  }

  function firstText(root, selectors) {
    for (const selector of selectors) {
      const text = cleanText(root.querySelector(selector)?.textContent);
      if (text) return text;
    }
    return "";
  }

  function metaContent(root, ...keys) {
    for (const key of keys) {
      const selector = `meta[property="${key}"], meta[name="${key}"]`;
      const content = cleanText(root.querySelector(selector)?.getAttribute("content"));
      if (content) return content;
    }
    return "";
  }

  function imageUrls(root, selectors, fallback = "") {
    const urls = [];
    selectors.forEach((selector) => {
      root.querySelectorAll(selector).forEach((image) => {
        const candidate = image.getAttribute("src")
          || image.getAttribute("data-src")
          || image.getAttribute("data-original")
          || image.getAttribute("data-lazy-src");
        const url = absoluteWebUrl(candidate);
        if (url && !urls.includes(url)) urls.push(url);
      });
    });
    const fallbackUrl = absoluteWebUrl(fallback);
    if (fallbackUrl && !urls.includes(fallbackUrl)) urls.push(fallbackUrl);
    return urls.slice(0, 9);
  }

  function appendMetadata(article, items) {
    const list = document.createElement("ul");
    items.filter((item) => item.value).forEach((item) => {
      const entry = document.createElement("li");
      const label = document.createElement("strong");
      label.textContent = `${item.label}：`;
      entry.append(label);
      if (item.href) {
        const link = document.createElement("a");
        link.href = item.href;
        link.textContent = item.value;
        entry.append(link);
      } else {
        entry.append(document.createTextNode(item.value));
      }
      list.append(entry);
    });
    if (list.childElementCount) article.append(list);
  }

  function appendTextSection(article, heading, text) {
    const value = cleanText(text);
    if (!value) return;
    const title = document.createElement("h2");
    title.textContent = heading;
    const paragraph = document.createElement("p");
    paragraph.textContent = value;
    article.append(title, paragraph);
  }

  function appendNodeSection(article, heading, node) {
    if (!node || !cleanText(node.textContent)) return false;
    const title = document.createElement("h2");
    title.textContent = heading;
    const content = node.cloneNode(true);
    stripSensitiveNodes(content);
    article.append(title, content);
    return true;
  }

  function appendImages(article, urls, heading = "图片") {
    if (!urls.length) return;
    const title = document.createElement("h2");
    title.textContent = heading;
    article.append(title);
    urls.forEach((url, index) => {
      const image = document.createElement("img");
      image.src = url;
      image.alt = `${heading} ${index + 1}`;
      article.append(image);
    });
  }

  function platformArticle({ platform, title, label, author = "", community = "", body = "", bodyNode = null, images = [], imageHeading = "图片" }) {
    const article = document.createElement("article");
    const heading = document.createElement("h1");
    heading.textContent = title;
    article.append(heading);
    appendMetadata(article, [
      { label: "平台", value: platform },
      { label: "作者", value: author },
      { label: "社区", value: community },
      { label: "来源", value: "查看原页面", href: location.href },
    ]);
    if (!appendNodeSection(article, platform === "YouTube" ? "视频简介" : "正文", bodyNode)) {
      appendTextSection(article, platform === "YouTube" ? "视频简介" : "正文", body);
    }
    appendImages(article, images, imageHeading);
    const markdown = htmlToMarkdown(article.outerHTML);
    if (!markdown) return null;
    return {
      title: title.slice(0, 500),
      markdownContent: markdown,
      length: cleanText(article.textContent).length,
      label,
    };
  }

  function captureXiaohongshu(root) {
    if (!matchesHost("xiaohongshu.com", "xhslink.com")) return null;
    const title = firstText(root, ["#detail-title", ".note-content .title", ".note-scroller .title", "[class*='note'] [class*='title']"])
      || metaContent(root, "og:title", "twitter:title")
      || document.title;
    const bodyNode = firstNode(root, ["#detail-desc", ".note-content .desc", ".note-scroller .desc", ".note-text", "[class*='note-text']", "[class*='note'] [class*='desc']"]);
    const body = cleanText(bodyNode?.textContent) || metaContent(root, "og:description", "description");
    const author = firstText(root, [".author-wrapper .username", ".author-container .username", "[class*='author'] [class*='name']"]);
    const images = imageUrls(
      root,
      ["#noteContainer .swiper-slide img", ".note-content .swiper-slide img", ".note-scroller [class*='swiper'] img", ".note-slider-img", "#noteContainer img[class*='note']"],
      metaContent(root, "og:image", "twitter:image"),
    );
    if (!body && !images.length) return null;
    return platformArticle({ platform: "小红书", title, label: "✓ 已读取小红书笔记", author, body, bodyNode, images, imageHeading: "笔记图片" });
  }

  function captureYouTube(root) {
    if (!matchesHost("youtube.com", "youtu.be")) return null;
    const title = metaContent(root, "og:title", "twitter:title")
      || firstText(root, ["h1.ytd-watch-metadata", "#title h1", "h1"])
      || document.title;
    const author = firstText(root, ["#owner #channel-name", "ytd-video-owner-renderer #channel-name", "#upload-info #channel-name"])
      || metaContent(root, "author");
    const bodyNode = firstNode(root, ["#description-inline-expander #description", "#description-inline-expander", "ytd-text-inline-expander#description", "#description"]);
    const body = cleanText(bodyNode?.textContent) || metaContent(root, "og:description", "description");
    const images = imageUrls(root, [], metaContent(root, "og:image", "twitter:image"));
    return platformArticle({ platform: "YouTube", title, label: "✓ 已读取 YouTube 视频信息", author, body, bodyNode, images, imageHeading: "视频封面" });
  }

  function captureReddit(root) {
    if (!matchesHost("reddit.com", "redd.it")) return null;
    const post = root.querySelector("shreddit-post");
    const title = cleanText(post?.getAttribute("post-title"))
      || firstText(root, ["shreddit-post h1", "[data-testid='post-container'] h1", ".thing.link .title a"])
      || metaContent(root, "og:title", "twitter:title")
      || document.title;
    const author = cleanText(post?.getAttribute("author"))
      || firstText(root, ["shreddit-post [slot='credit-bar']", "[data-testid='post_author_link']", ".tagline .author"]);
    const community = cleanText(post?.getAttribute("subreddit-prefixed-name") || post?.getAttribute("subreddit-name"))
      || firstText(root, ["shreddit-post [slot='subreddit-name']", "[data-testid='subreddit-name']"]);
    const bodyNode = firstNode(root, ["shreddit-post [slot='text-body']", "[data-testid='post-container'] [data-click-id='text']", ".thing.link .usertext-body"]);
    const body = cleanText(bodyNode?.textContent) || metaContent(root, "og:description", "description");
    const images = imageUrls(root, ["shreddit-post [slot='post-media-container'] img", "[data-testid='post-container'] [data-click-id='media'] img", "[data-testid='post-content'] img"], metaContent(root, "og:image", "twitter:image"));
    return platformArticle({ platform: "Reddit", title, label: "✓ 已读取 Reddit 帖子", author, community, body, bodyNode, images, imageHeading: "帖子图片" });
  }

  function captureKnownPlatform(root) {
    return captureXiaohongshu(root) || captureYouTube(root) || captureReddit(root);
  }

  function htmlToMarkdown(html) {
    const parsed = new DOMParser().parseFromString(html || "", "text/html");
    stripSensitiveNodes(parsed);
    parsed.querySelectorAll("a[href]").forEach((link) => {
      const href = absoluteWebUrl(link.getAttribute("href"));
      if (href) link.setAttribute("href", href);
      else link.removeAttribute("href");
    });
    parsed.querySelectorAll("img").forEach((image) => {
      const src = absoluteWebUrl(image.getAttribute("src"));
      if (src) image.setAttribute("src", src);
      else image.remove();
    });
    const turndown = new TurndownService({
      bulletListMarker: "-",
      codeBlockStyle: "fenced",
      emDelimiter: "*",
      headingStyle: "atx",
    });
    return turndown.turndown(parsed.body).trim().slice(0, MAX_MARKDOWN_CHARS);
  }

  globalThis.captureBookmarkPage = () => {
    const clone = document.cloneNode(true);
    stripSensitiveNodes(clone);

    const platformCapture = captureKnownPlatform(clone);
    if (platformCapture) {
      return {
        title: platformCapture.title,
        source: location.hostname,
        readability: platformCapture,
      };
    }

    let article = null;
    try {
      article = new Readability(clone, { charThreshold: 80 }).parse();
    } catch (_) {
      article = null;
    }

    let readability = null;
    if (article?.content && (article.textContent || "").trim().length >= 80) {
      const markdown = htmlToMarkdown(article.content);
      if (markdown) {
        readability = {
          title: (article.title || document.title || "未命名网页").trim(),
          markdownContent: markdown,
          length: (article.textContent || "").trim().length,
        };
      }
    }

    return {
      title: (readability?.title || document.title || "未命名网页").slice(0, 500),
      source: location.hostname,
      readability,
    };
  };
})();
