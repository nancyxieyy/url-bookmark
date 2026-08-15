const API_BASE = "https://url-bookmark.onrender.com";

const form = document.querySelector("#bookmark-form");
const previewButton = document.querySelector("#preview-button");
const saveButton = document.querySelector("#save-button");
const titleElement = document.querySelector("#page-title");
const urlElement = document.querySelector("#page-url");
const existingTagsElement = document.querySelector("#existing-tags");
const recommendedFieldset = document.querySelector("#recommended-fieldset");
const recommendedTagsElement = document.querySelector("#recommended-tags");
const newTagsInput = document.querySelector("#new-tags");
const notesInput = document.querySelector("#notes");
const statusElement = document.querySelector("#status");
const recentList = document.querySelector("#recent-list");

let currentPage = { title: "", url: "" };
let previewBookmark = null;
let availableTags = [];
const selectedTags = new Set();

function showStatus(message, type) {
  statusElement.textContent = message;
  statusElement.className = `status ${type}`;
}

function parseNewTags(value) {
  return value.replaceAll("，", ",").split(",").map((tag) => tag.trim()).filter(Boolean);
}

function tagButton(tag, recommended = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "tag-button";
  button.textContent = recommended ? `＋ ${tag}` : tag;
  if (selectedTags.has(tag)) button.classList.add("selected");
  button.addEventListener("click", () => {
    if (selectedTags.has(tag)) selectedTags.delete(tag);
    else selectedTags.add(tag);
    renderTags();
  });
  return button;
}

function renderTags(recommendations = null) {
  existingTagsElement.replaceChildren();
  const combined = [...new Set([...availableTags, ...selectedTags])];
  if (!combined.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "还没有标签，可以在下方新建。";
    existingTagsElement.append(empty);
  } else {
    combined.forEach((tag) => existingTagsElement.append(tagButton(tag)));
  }

  if (recommendations !== null) {
    recommendedFieldset.dataset.tags = JSON.stringify(recommendations);
  }
  const saved = JSON.parse(recommendedFieldset.dataset.tags || "[]");
  recommendedTagsElement.replaceChildren();
  saved.forEach((tag) => recommendedTagsElement.append(tagButton(tag, true)));
  recommendedFieldset.hidden = saved.length === 0;
}

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

async function loadPopup() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentPage = { title: tab?.title || "未命名网页", url: tab?.url || "" };
  titleElement.textContent = currentPage.title;
  urlElement.textContent = currentPage.url;
  urlElement.title = currentPage.url;
  previewButton.disabled = !currentPage.url.startsWith("http://") && !currentPage.url.startsWith("https://");

  try {
    const [tagsResponse] = await Promise.all([fetch(`${API_BASE}/api/tags`), loadRecent()]);
    if (!tagsResponse.ok) throw new Error("无法读取标签");
    availableTags = await tagsResponse.json();
    renderTags([]);
  } catch (_) {
    showStatus("无法连接收藏服务，请稍后重试。", "error");
    recentList.innerHTML = '<span class="muted">服务未连接。</span>';
  }
}

previewButton.addEventListener("click", async () => {
  if (!currentPage.url.startsWith("http://") && !currentPage.url.startsWith("https://")) {
    showStatus("当前页面不是可收藏的 HTTP/HTTPS 网页。", "error");
    return;
  }
  previewButton.disabled = true;
  previewButton.querySelector("span").textContent = "正在抓取…";
  showStatus("正在抓取正文和生成标签建议…", "success");

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
    notesInput.value = result.notes || "";

    let suggestions = [];
    if (!result.duplicate && result.status === "success") {
      const suggestionResponse = await fetch(`${API_BASE}/api/bookmarks/${result.id}/tag-suggestions`, { method: "POST" });
      if (suggestionResponse.ok) {
        const payload = await suggestionResponse.json();
        suggestions = [...payload.existing_tags, ...payload.new_tags];
      }
    }
    renderTags(suggestions);
    form.hidden = false;
    previewButton.hidden = true;
    showStatus(
      result.duplicate
        ? "该网址已收藏过，可以修改标签和备注。"
        : result.status === "success"
          ? "抓取完成，请确认标签和备注。"
          : "正文未完整提取，仍可添加标签和备注后收藏。",
      "success",
    );
  } catch (error) {
    showStatus(error.message || "抓取失败，请稍后重试。", "error");
    previewButton.disabled = false;
    previewButton.querySelector("span").textContent = "抓取当前页面";
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!previewBookmark) return;
  const tags = [...new Set([...selectedTags, ...parseNewTags(newTagsInput.value)])];
  saveButton.disabled = true;
  showStatus("正在保存…", "success");
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/${previewBookmark.id}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags, notes: notesInput.value }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "保存失败");
    showStatus(previewBookmark.duplicate ? "标签和备注已更新。" : `已收藏：${result.title}`, "success");
    saveButton.querySelector("span").textContent = "收藏成功";
    availableTags = [...new Set([...availableTags, ...result.tags])];
    await loadRecent();
  } catch (error) {
    showStatus(error.message || "保存失败，请稍后重试。", "error");
  } finally {
    saveButton.disabled = false;
  }
});

loadPopup().catch(() => showStatus("无法读取当前标签页。", "error"));
