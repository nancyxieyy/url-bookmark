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
