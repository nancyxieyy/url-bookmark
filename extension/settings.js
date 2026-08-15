(function exposeBookmarkSettings(global) {
  const DEFAULT_SERVER_URL = "https://url-bookmark.onrender.com";

  function normalizeServerUrl(value) {
    return String(value || "").trim().replace(/\/+$/, "");
  }

  async function load() {
    const stored = await chrome.storage.local.get(["serverUrl", "apiToken"]);
    return {
      serverUrl: normalizeServerUrl(stored.serverUrl || DEFAULT_SERVER_URL),
      apiToken: String(stored.apiToken || "").trim(),
    };
  }

  async function save({ serverUrl, apiToken }) {
    const normalizedUrl = normalizeServerUrl(serverUrl);
    await chrome.storage.local.set({
      serverUrl: normalizedUrl,
      apiToken: String(apiToken || "").trim(),
    });
    return { serverUrl: normalizedUrl, apiToken: String(apiToken || "").trim() };
  }

  function endpoint(settings, path) {
    return `${normalizeServerUrl(settings.serverUrl)}${path}`;
  }

  function headers(settings, extra = {}) {
    return {
      ...extra,
      Authorization: `Bearer ${settings.apiToken}`,
    };
  }

  global.BookmarkSettings = {
    DEFAULT_SERVER_URL,
    normalizeServerUrl,
    load,
    save,
    endpoint,
    headers,
  };
})(globalThis);
