const API_URL = "http://127.0.0.1:8000/api/bookmarks";

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
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url?.startsWith("http://") && !tab?.url?.startsWith("https://")) {
      await notify("URL Bookmark", "当前页面不是可收藏的网页。");
      return;
    }

    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: tab.url,
        title: tab.title || "未命名网页",
        tags: ["Inbox"],
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "保存失败");
    await notify("已保存到 Inbox", result.title);
  } catch (error) {
    await notify("保存失败", "请确认本地 URL Bookmark 服务正在运行。");
  }
});
