importScripts("settings.js");

async function notify(title, message) {
  await chrome.notifications.create({
    type: "basic",
    iconUrl: "icon.png",
    title,
    message,
  });
}

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "quick-save-inbox") return;

  try {
    const settings = await BookmarkSettings.load();
    if (!settings.serverUrl) {
      await notify("URL Bookmark", "未配置服务器，请先打开扩展设置。");
      return;
    }
    if (!settings.apiToken) {
      await notify("URL Bookmark", "未配置 API Token，请先打开扩展设置。");
      return;
    }
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url?.startsWith("http://") && !tab?.url?.startsWith("https://")) {
      await notify("URL Bookmark", "当前页面不是可收藏的网页。");
      return;
    }

    const response = await fetch(BookmarkSettings.endpoint(settings, "/api/bookmarks"), {
      method: "POST",
      headers: BookmarkSettings.headers(settings, { "Content-Type": "application/json" }),
      body: JSON.stringify({
        url: tab.url,
        title: tab.title || "未命名网页",
        tags: ["Inbox"],
      }),
    });
    const result = await response.json();
    if (response.status === 401) {
      await notify("URL Bookmark", "API Token 无效，请在扩展设置中重新配置。");
      return;
    }
    if (!response.ok) throw new Error(result.detail || "保存失败");
    await notify(result.duplicate ? "该网址已收藏过" : "已保存到 Inbox", result.title);
  } catch (error) {
    await notify("无法连接服务器", "请检查 Server URL、网络和服务状态。");
  }
});
