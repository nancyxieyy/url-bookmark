const API_BASE = "https://url-bookmark.onrender.com";

const form = document.querySelector("#bookmark-form");
const retryButton = document.querySelector("#preview-button");
const saveButton = document.querySelector("#save-button");
const titleElement = document.querySelector("#page-title");
const urlElement = document.querySelector("#page-url");
const notesInput = document.querySelector("#notes");
const statusElement = document.querySelector("#status");
const recentList = document.querySelector("#recent-list");
const tagSelect = document.querySelector("[data-tag-select]");
const tagTrigger = tagSelect.querySelector("[data-tag-trigger]");
const tagMenu = tagSelect.querySelector("[data-tag-menu]");
const tagSummary = tagSelect.querySelector("[data-tag-summary]");
const tagOptions = tagSelect.querySelector("[data-tag-options]");
const newTagInput = tagSelect.querySelector("[data-new-tag]");
const tagDone = tagSelect.querySelector("[data-tag-done]");
const recommendedSection = document.querySelector("#recommended-section");
const recommendedTagsElement = document.querySelector("#recommended-tags");

let currentPage = { title: "", url: "" };
let previewBookmark = null;
let availableTags = [];
let recommendations = [];
const selectedTags = new Set();

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
    : tags.length <= 2
      ? tags.join("、")
      : `${tags.slice(0, 2).join("、")} +${tags.length - 2}`;
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

tagTrigger.addEventListener("click", () => {
  if (tagMenu.hidden) openTagMenu();
  else closeTagMenu();
});
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
    link.href = `${API_BASE}/bookmarks/${bookmark.id}`;
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
      const response = await fetch(`${API_BASE}/api/bookmarks/${bookmark.id}/delete`, { method: "POST" });
      if (!response.ok) {
        showStatus("删除失败，请稍后再试。", "error");
        return;
      }
      showStatus("已移入回收站。", "success");
      await loadRecent();
    });
    item.append(link, remove);
    recentList.append(item);
  });
}

async function loadRecent() {
  const response = await fetch(`${API_BASE}/api/bookmarks/recent?limit=3`);
  if (!response.ok) throw new Error("无法读取最近收藏");
  renderRecent(await response.json());
}

async function loadAvailableTags() {
  const response = await fetch(`${API_BASE}/api/tags`);
  if (!response.ok) throw new Error("无法读取标签");
  availableTags = uniqueTags(await response.json());
  renderTagOptions();
}

async function loadSuggestions(bookmarkId) {
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/${bookmarkId}/tag-suggestions`, { method: "POST" });
    if (!response.ok) return;
    const payload = await response.json();
    recommendations = uniqueTags([...payload.existing_tags, ...payload.new_tags]);
    renderRecommendations();
  } catch (_) {
    recommendations = [];
    renderRecommendations();
  }
}

async function captureCurrentPage() {
  if (!currentPage.url.startsWith("http://") && !currentPage.url.startsWith("https://")) {
    showStatus("当前页面不是可收藏的 HTTP/HTTPS 网页。", "error");
    return;
  }

  retryButton.hidden = true;
  form.hidden = true;
  showStatus("正在自动抓取当前页面…", "success");
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...currentPage, tags: [], notes: "" }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "抓取失败");

    previewBookmark = result;
    selectedTags.clear();
    result.tags.forEach((tag) => selectedTags.add(tag));
    availableTags = uniqueTags([...availableTags, ...result.tags]);
    recommendations = [];
    notesInput.value = result.notes || "";
    renderTagOptions();
    renderRecommendations();
    form.hidden = false;
    showStatus(
      result.duplicate
        ? "该网址已收藏过，可以修改标签和备注。"
        : result.status === "success"
          ? "抓取完成，请确认标签和备注。"
          : "正文未完整提取，仍可添加标签和备注后收藏。",
      "success",
    );

    if (!result.duplicate && result.status === "success") {
      void loadSuggestions(result.id);
    }
  } catch (error) {
    showStatus(error.message || "抓取失败，请稍后重试。", "error");
    retryButton.hidden = false;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!previewBookmark) return;
  saveButton.disabled = true;
  closeTagMenu();
  showStatus("正在保存…", "success");
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/${previewBookmark.id}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: [...selectedTags], notes: notesInput.value }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "保存失败");
    showStatus(previewBookmark.duplicate ? "标签和备注已更新。" : `已收藏：${result.title}`, "success");
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
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentPage = { title: tab?.title || "未命名网页", url: tab?.url || "" };
  titleElement.textContent = currentPage.title;
  urlElement.textContent = currentPage.url;
  urlElement.title = currentPage.url;

  void loadRecent().catch(() => {
    recentList.innerHTML = '<span class="muted">最近收藏暂时无法读取。</span>';
  });
  void loadAvailableTags().catch(() => renderTagOptions());
  await captureCurrentPage();
}

loadPopup().catch(() => showStatus("无法读取当前标签页。", "error"));
