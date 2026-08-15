const form = document.querySelector("#settings-form");
const serverUrlInput = document.querySelector("#server-url");
const apiTokenInput = document.querySelector("#api-token");
const statusElement = document.querySelector("#status");

async function loadOptions() {
  const settings = await BookmarkSettings.load();
  serverUrlInput.value = settings.serverUrl || BookmarkSettings.DEFAULT_SERVER_URL;
  apiTokenInput.value = settings.apiToken;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const serverUrl = BookmarkSettings.normalizeServerUrl(serverUrlInput.value);
  let parsed;
  try {
    parsed = new URL(serverUrl);
  } catch (_) {
    statusElement.textContent = "Server URL 格式无效。";
    statusElement.className = "error";
    return;
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    statusElement.textContent = "Server URL 必须使用 http:// 或 https://。";
    statusElement.className = "error";
    return;
  }
  if (!apiTokenInput.value.trim()) {
    statusElement.textContent = "请填写 API Token。";
    statusElement.className = "error";
    return;
  }

  const originPattern = `${parsed.origin}/*`;
  const hasPermission = await chrome.permissions.contains({
    origins: [originPattern],
  });
  if (!hasPermission) {
    const granted = await chrome.permissions.request({
      origins: [originPattern],
    });
    if (!granted) {
      statusElement.textContent = "未授权访问这个服务器地址，设置尚未保存。";
      statusElement.className = "error";
      return;
    }
  }

  await BookmarkSettings.save({ serverUrl, apiToken: apiTokenInput.value });
  serverUrlInput.value = serverUrl;
  statusElement.textContent = "设置已保存。";
  statusElement.className = "success";
});

loadOptions().catch(() => {
  statusElement.textContent = "无法读取扩展设置。";
  statusElement.className = "error";
});
