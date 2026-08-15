const API_BASE = "http://127.0.0.1:8000";

const form = document.querySelector("#bookmark-form");
const titleElement = document.querySelector("#page-title");
const urlElement = document.querySelector("#page-url");
const existingTagsElement = document.querySelector("#existing-tags");
const newTagsInput = document.querySelector("#new-tags");
const saveButton = document.querySelector("#save-button");
const statusElement = document.querySelector("#status");

let currentPage = { title: "", url: "" };
const selectedTags = new Set();

function showStatus(message, type) {
  statusElement.textContent = message;
  statusElement.className = `status ${type}`;
}

function parseNewTags(value) {
  return value
    .replaceAll("，", ",")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function renderExistingTags(tags) {
  existingTagsElement.replaceChildren();
  if (!tags.length) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "还没有标签，可以在下方新建。";
    existingTagsElement.append(empty);
    return;
  }

  for (const tag of tags) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-button";
    button.textContent = tag;
    button.addEventListener("click", () => {
      if (selectedTags.has(tag)) {
        selectedTags.delete(tag);
        button.classList.remove("selected");
      } else {
        selectedTags.add(tag);
        button.classList.add("selected");
      }
    });
    existingTagsElement.append(button);
  }
}

async function loadPopup() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentPage = { title: tab?.title || "未命名网页", url: tab?.url || "" };
  titleElement.textContent = currentPage.title;
  urlElement.textContent = currentPage.url;
  urlElement.title = currentPage.url;

  try {
    const response = await fetch(`${API_BASE}/api/tags`);
    if (!response.ok) throw new Error("无法读取标签");
    renderExistingTags(await response.json());
  } catch (error) {
    renderExistingTags([]);
    showStatus("无法连接本地服务，请先启动 uvicorn。", "error");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentPage.url.startsWith("http://") && !currentPage.url.startsWith("https://")) {
    showStatus("当前页面不是可收藏的 HTTP/HTTPS 网页。", "error");
    return;
  }

  const tags = [...new Set([...selectedTags, ...parseNewTags(newTagsInput.value)])];
  saveButton.disabled = true;
  showStatus("正在保存并抓取正文…", "success");

  try {
    const response = await fetch(`${API_BASE}/api/bookmarks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...currentPage, tags }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "保存失败");
    const suffix = result.status === "success" ? "正文已提取。" : "网址已保存，正文可稍后重试。";
    showStatus(`已保存：${result.title} ${suffix}`, "success");
    saveButton.querySelector("span").textContent = "保存成功";
  } catch (error) {
    showStatus(error.message || "保存失败，请检查本地服务。", "error");
  } finally {
    saveButton.disabled = false;
  }
});

loadPopup().catch(() => showStatus("无法读取当前标签页。", "error"));
