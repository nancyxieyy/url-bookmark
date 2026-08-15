const form = document.querySelector("#bookmark-form");
const retryButton = document.querySelector("#preview-button");
const saveButton = document.querySelector("#save-button");
const titleElement = document.querySelector("#page-title");
const urlElement = document.querySelector("#page-url");
const notesInput = document.querySelector("#notes");
const statusElement = document.querySelector("#status");
const recentList = document.querySelector("#recent-list");
const captureSummary = document.querySelector("#capture-summary");
const captureMethodElement = document.querySelector("#capture-method");
const captureLengthElement = document.querySelector("#capture-length");
const captureSourceElement = document.querySelector("#capture-source");
const fallbackActions = document.querySelector("#fallback-actions");
const urlOnlyButton = document.querySelector("#url-only-button");
const tagSelect = document.querySelector("[data-tag-select]");
const tagTrigger = tagSelect.querySelector("[data-tag-trigger]");
const tagMenu = tagSelect.querySelector("[data-tag-menu]");
const tagSummary = tagSelect.querySelector("[data-tag-summary]");
const tagOptions = tagSelect.querySelector("[data-tag-options]");
const newTagInput = tagSelect.querySelector("[data-new-tag]");
const tagDone = tagSelect.querySelector("[data-tag-done]");
const recommendedSection = document.querySelector("#recommended-section");
const recommendedTagsElement = document.querySelector("#recommended-tags");
const manageLink = document.querySelector("#manage-link");
const settingsLink = document.querySelector("#settings-link");

let currentPage = { title: "", url: "", tabId: null };
let extensionSettings = null;
let localCapture = null;
let chosenContent = null;
let duplicateBookmark = null;
let availableTags = [];
let recommendations = [];
const selectedTags = new Set();

settingsLink.addEventListener("click", () => chrome.runtime.openOptionsPage());

async function apiFetch(path, options = {}) {
  const requestOptions = { ...options };
  requestOptions.headers = BookmarkSettings.headers(extensionSettings, options.headers || {});
  try {
    return await fetch(BookmarkSettings.endpoint(extensionSettings, path), requestOptions);
  } catch (_) {
    throw new Error("无法连接服务器，请检查 Server URL 和网络。");
  }
}

async function apiPayload(response, fallbackMessage) {
  let payload = {};
  try { payload = await response.json(); } catch (_) {}
  if (response.status === 401) throw new Error("API Token 无效，请在扩展设置中重新配置。");
  if (!response.ok) throw new Error(payload.detail || fallbackMessage);
  return payload;
}

function showStatus(message, type) {
  statusElement.textContent = message;
  statusElement.className = `status ${type}`;
}

function uniqueTags(tags) {
  const seen = new Set();
  return tags.filter((tag) => {
    const key = tag.trim().toLocaleLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function updateTagSummary() {
  const tags = [...selectedTags];
  tagSummary.textContent = tags.length === 0
    ? "选择标签"
    : tags.length <= 2 ? tags.join("、") : `${tags.slice(0, 2).join("、")} +${tags.length - 2}`;
}

function renderTagOptions() {
  tagOptions.replaceChildren();
  const tags = uniqueTags([...availableTags, ...selectedTags]);
  if (!tags.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "还没有标签，可从第一行添加。";
    tagOptions.append(empty);
  }
  tags.forEach((tag) => {
    const label = document.createElement("label");
    label.className = "tag-menu-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = tag;
    checkbox.checked = selectedTags.has(tag);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedTags.add(tag);
      else selectedTags.delete(tag);
      updateTagSummary();
      renderRecommendations();
    });
    const check = document.createElement("span");
    check.className = "tag-check";
    check.setAttribute("aria-hidden", "true");
    check.textContent = "✓";
    const text = document.createElement("span");
    text.textContent = tag;
    label.append(checkbox, check, text);
    tagOptions.append(label);
  });
  updateTagSummary();
}

function renderRecommendations() {
  recommendedTagsElement.replaceChildren();
  recommendations.forEach((tag) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-suggestion";
    const selected = selectedTags.has(tag);
    button.setAttribute("aria-pressed", String(selected));
    button.textContent = `${selected ? "✓" : "＋"} ${tag}`;
    button.addEventListener("click", () => {
      if (selectedTags.has(tag)) selectedTags.delete(tag);
      else {
        selectedTags.add(tag);
        availableTags = uniqueTags([...availableTags, tag]);
      }
      renderTagOptions();
      renderRecommendations();
    });
    recommendedTagsElement.append(button);
  });
  recommendedSection.hidden = recommendations.length === 0;
}

function openTagMenu() {
  tagMenu.hidden = false;
  tagSelect.classList.add("open");
  tagTrigger.setAttribute("aria-expanded", "true");
}

function closeTagMenu() {
  tagMenu.hidden = true;
  tagSelect.classList.remove("open");
  tagTrigger.setAttribute("aria-expanded", "false");
}

tagTrigger.addEventListener("click", () => tagMenu.hidden ? openTagMenu() : closeTagMenu());
tagDone.addEventListener("click", closeTagMenu);
newTagInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  const tag = newTagInput.value.trim().slice(0, 50);
  if (!tag) return;
  availableTags = uniqueTags([...availableTags, tag]);
  selectedTags.add(tag);
  newTagInput.value = "";
  renderTagOptions();
});
document.addEventListener("click", (event) => {
  if (!event.composedPath().includes(tagSelect)) closeTagMenu();
});

function renderRecent(bookmarks) {
  recentList.replaceChildren();
  if (!bookmarks.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "还没有收藏。";
    recentList.append(empty);
    return;
  }
  bookmarks.forEach((bookmark) => {
    const item = document.createElement("article");
    item.className = "recent-item";
    const link = document.createElement("a");
    link.className = "recent-copy";
    link.href = `${extensionSettings.serverUrl}/bookmarks/${bookmark.id}`;
    link.target = "_blank";
    const title = document.createElement("strong");
    title.textContent = bookmark.title;
    const tags = document.createElement("small");
    tags.textContent = bookmark.tags.length ? bookmark.tags.join("、") : "暂无标签";
    link.append(title, tags);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "recent-delete";
    remove.textContent = "删除";
    remove.addEventListener("click", async () => {
      if (!window.confirm(`把“${bookmark.title}”移入回收站吗？`)) return;
      const response = await apiFetch(`/api/bookmarks/${bookmark.id}/delete`, { method: "POST" });
      await apiPayload(response, "删除失败，请稍后再试。");
      showStatus("已移入回收站。", "success");
      await loadRecent();
    });
    item.append(link, remove);
    recentList.append(item);
  });
}

async function loadRecent() {
  const response = await apiFetch("/api/bookmarks/recent?limit=3");
  renderRecent(await apiPayload(response, "无法读取最近收藏"));
}

async function loadAvailableTags() {
  const response = await apiFetch("/api/tags");
  availableTags = uniqueTags(await apiPayload(response, "无法读取标签"));
  renderTagOptions();
}

async function extractCurrentPage() {
  await chrome.scripting.executeScript({
    target: { tabId: currentPage.tabId },
    files: ["vendor/Readability.js", "vendor/turndown.js", "capture.js"],
  });
  const results = await chrome.scripting.executeScript({
    target: { tabId: currentPage.tabId },
    func: () => globalThis.captureBookmarkPage(),
  });
  return results[0]?.result || null;
}

function displayChosenContent(label, content) {
  chosenContent = content;
  captureSummary.hidden = false;
  captureMethodElement.textContent = label;
  captureLengthElement.textContent = content.markdownContent
    ? `${content.length.toLocaleString()} 字符` : "未保存正文";
  captureSourceElement.textContent = `来源：${localCapture?.source || new URL(currentPage.url).hostname}`;
  fallbackActions.hidden = true;
  form.hidden = false;
}

function applyDuplicate(bookmark) {
  duplicateBookmark = bookmark;
  selectedTags.clear();
  bookmark.tags.forEach((tag) => selectedTags.add(tag));
  availableTags = uniqueTags([...availableTags, ...bookmark.tags]);
  notesInput.value = bookmark.notes || "";
  renderTagOptions();
  form.hidden = false;
  showStatus("该网址已收藏过，可以修改标签和备注。", "success");
}

async function checkDuplicate() {
  const response = await apiFetch("/api/bookmarks/check-duplicate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: currentPage.url }),
  });
  const result = await apiPayload(response, "重复检测失败");
  if (result.duplicate && result.bookmark) applyDuplicate(result.bookmark);
}

async function captureCurrentPage() {
  retryButton.hidden = true;
  form.hidden = true;
  captureSummary.hidden = true;
  recommendations = [];
  renderRecommendations();
  showStatus("正在本地读取当前页面…", "success");
  try {
    localCapture = await extractCurrentPage();
    if (!localCapture) throw new Error("页面没有返回可用内容。");
    currentPage.title = localCapture.title || currentPage.title;
    titleElement.textContent = currentPage.title;
    if (localCapture.readability) {
      displayChosenContent(localCapture.readability.label || "✓ 已从浏览器读取正文", localCapture.readability);
      showStatus("正文已读取，推荐标签会自动显示在标签菜单中。", "success");
    } else {
      chosenContent = null;
      captureSummary.hidden = false;
      captureMethodElement.textContent = "⚠ 未能自动识别正文";
      captureLengthElement.textContent = "仍可只收藏网址";
      captureSourceElement.textContent = `来源：${localCapture.source}`;
      fallbackActions.hidden = false;
      retryButton.hidden = false;
      showStatus("未识别到正文，仍可只收藏网址。", "error");
    }
    await checkDuplicate();
    if (chosenContent?.markdownContent) await generateRecommendations();
  } catch (error) {
    localCapture = { source: new URL(currentPage.url).hostname };
    chosenContent = null;
    captureSummary.hidden = false;
    captureMethodElement.textContent = "⚠ 无法读取页面正文";
    captureLengthElement.textContent = "可只收藏网址";
    captureSourceElement.textContent = `来源：${localCapture.source}`;
    fallbackActions.hidden = false;
    retryButton.hidden = false;
    showStatus(error.message || "无法读取当前页面。", "error");
    await checkDuplicate().catch(() => {});
  }
}

urlOnlyButton.addEventListener("click", () => {
  displayChosenContent("仅收藏网址", { markdownContent: "", length: 0 });
  showStatus("将只保存网址、标题、标签和备注。", "success");
});

async function generateRecommendations() {
  if (!chosenContent?.markdownContent) return;
  try {
    const response = await apiFetch("/api/bookmarks/browser-tag-suggestions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: currentPage.title, markdown_content: chosenContent.markdownContent }),
    });
    const payload = await apiPayload(response, "AI 推荐暂时不可用");
    recommendations = uniqueTags([...payload.existing_tags, ...payload.new_tags]);
    renderRecommendations();
  } catch (_) {
    recommendations = [];
    renderRecommendations();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!chosenContent && !duplicateBookmark) return;
  saveButton.disabled = true;
  closeTagMenu();
  showStatus("正在保存…", "success");
  try {
    const response = await apiFetch("/api/bookmarks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: currentPage.url,
        title: currentPage.title,
        markdown_content: chosenContent?.markdownContent || "",
        capture_method: "browser",
        tags: [...selectedTags],
        notes: notesInput.value,
        replace_existing: Boolean(duplicateBookmark),
      }),
    });
    const result = await apiPayload(response, "保存失败");
    duplicateBookmark = result;
    showStatus(result.duplicate ? "标签和备注已更新。" : `已收藏：${result.title}`, "success");
    saveButton.querySelector("span").textContent = "收藏成功";
    availableTags = uniqueTags([...availableTags, ...result.tags]);
    await loadRecent();
  } catch (error) {
    showStatus(error.message || "保存失败，请稍后重试。", "error");
  } finally {
    saveButton.disabled = false;
  }
});

retryButton.addEventListener("click", captureCurrentPage);

async function loadPopup() {
  extensionSettings = await BookmarkSettings.load();
  manageLink.href = extensionSettings.serverUrl || "#";
  if (!extensionSettings.serverUrl) {
    showStatus("未配置服务器，请先打开扩展设置。", "error");
    return;
  }
  if (!extensionSettings.apiToken) {
    showStatus("未配置 API Token，请先打开扩展设置。", "error");
    return;
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentPage = { title: tab?.title || "未命名网页", url: tab?.url || "", tabId: tab?.id };
  titleElement.textContent = currentPage.title;
  urlElement.textContent = currentPage.url;
  urlElement.title = currentPage.url;
  if (!Number.isInteger(currentPage.tabId)
      || (!currentPage.url.startsWith("http://") && !currentPage.url.startsWith("https://"))) {
    showStatus("当前页面不是可收藏的 HTTP/HTTPS 网页。", "error");
    return;
  }
  void loadRecent().catch((error) => {
    recentList.innerHTML = '<span class="muted">最近收藏暂时无法读取。</span>';
    if (String(error.message || "").includes("API Token")) showStatus(error.message, "error");
  });
  void loadAvailableTags().catch(() => renderTagOptions());
  await captureCurrentPage();
}

loadPopup().catch(() => showStatus("无法读取当前标签页。", "error"));
