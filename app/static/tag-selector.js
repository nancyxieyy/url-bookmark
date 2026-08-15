document.querySelectorAll("[data-tag-select]").forEach((selector) => {
  const trigger = selector.querySelector("[data-tag-trigger]");
  const menu = selector.querySelector("[data-tag-menu]");
  const summary = selector.querySelector("[data-tag-summary]");
  const newTagInput = selector.querySelector("[data-new-tag]");
  const options = selector.querySelector("[data-tag-options]");
  const doneButton = selector.querySelector("[data-tag-done]");

  const selectedNames = () =>
    [...selector.querySelectorAll("[data-tag-option]:checked")].map(
      (input) => input.value,
    );

  const updateSummary = () => {
    const selected = selectedNames();
    if (!selected.length) {
      summary.textContent = "选择标签";
      return;
    }
    summary.textContent =
      selected.length <= 2
        ? selected.join("、")
        : `${selected.slice(0, 2).join("、")} +${selected.length - 2}`;
  };

  const setOpen = (open) => {
    menu.hidden = !open;
    trigger.setAttribute("aria-expanded", String(open));
    selector.classList.toggle("open", open);
  };

  const findOption = (name) =>
    [...selector.querySelectorAll("[data-tag-option]")].find(
      (input) => input.value.toLocaleLowerCase() === name.toLocaleLowerCase(),
    );

  const createOption = (name) => {
    const label = document.createElement("label");
    label.className = "tag-menu-option";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "tag_choices";
    checkbox.value = name;
    checkbox.dataset.tagOption = "";

    const check = document.createElement("span");
    check.className = "tag-check";
    check.setAttribute("aria-hidden", "true");
    check.textContent = "✓";

    const text = document.createElement("span");
    text.textContent = name;
    label.append(checkbox, check, text);
    options.prepend(label);
    return checkbox;
  };

  const setTagSelected = (name, selected = true) => {
    const cleanName = name.trim().slice(0, 50);
    if (!cleanName) return false;
    const option = findOption(cleanName) || createOption(cleanName);
    option.checked = selected;
    updateSummary();
    return option.checked;
  };

  const addNewTag = () => {
    const name = newTagInput.value.trim();
    if (!name) return;

    setTagSelected(name);
    newTagInput.value = "";
  };

  selector.tagSelection = {
    isSelected: (name) => Boolean(findOption(name)?.checked),
    toggle: (name) => setTagSelected(name, !findOption(name)?.checked),
  };

  trigger.addEventListener("click", () => setOpen(menu.hidden));
  doneButton.addEventListener("click", () => {
    setOpen(false);
    trigger.focus();
  });
  selector.addEventListener("change", updateSummary);
  newTagInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addNewTag();
    }
    if (event.key === "Escape") {
      setOpen(false);
      trigger.focus();
    }
  });

  document.addEventListener("click", (event) => {
    if (!selector.contains(event.target)) setOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !menu.hidden) {
      setOpen(false);
      trigger.focus();
    }
  });

  updateSummary();
});

document.querySelectorAll("[data-tag-recommender]").forEach((recommender) => {
  const form = recommender.closest("form");
  const selector = form?.querySelector("[data-tag-select]");
  const button = recommender.querySelector("[data-recommend-tags]");
  const status = recommender.querySelector("[data-recommend-status]");
  const results = recommender.querySelector("[data-recommend-results]");
  if (!selector?.tagSelection) return;

  const renderGroup = (label, tags, kind) => {
    if (!tags.length) return null;
    const group = document.createElement("div");
    group.className = "tag-recommend-group";
    const heading = document.createElement("span");
    heading.className = "tag-recommend-group-label";
    heading.textContent = label;
    const list = document.createElement("div");
    list.className = "tag-recommend-list";

    tags.forEach((tag) => {
      const suggestion = document.createElement("button");
      suggestion.type = "button";
      suggestion.className = `tag-suggestion ${kind}`;
      suggestion.textContent = `＋ ${tag}`;
      suggestion.setAttribute("aria-pressed", "false");
      suggestion.addEventListener("click", () => {
        const selected = selector.tagSelection.toggle(tag);
        suggestion.setAttribute("aria-pressed", String(selected));
        suggestion.textContent = `${selected ? "✓" : "＋"} ${tag}`;
      });
      list.append(suggestion);
    });

    group.append(heading, list);
    return group;
  };

  const loadSuggestions = async () => {
    if (recommender.classList.contains("loading")) return;
    recommender.classList.add("loading");
    button.disabled = true;
    status.textContent = "正在阅读正文并整理标签…";
    results.hidden = true;
    results.replaceChildren();

    try {
      const response = await fetch(recommender.dataset.endpoint, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "AI 推荐暂时不可用。");

      const existing = renderGroup("优先匹配已有标签", payload.existing_tags, "existing");
      const fresh = renderGroup("建议的新标签", payload.new_tags, "new");
      if (existing) results.append(existing);
      if (fresh) results.append(fresh);
      results.hidden = !existing && !fresh;
      status.textContent = existing || fresh
        ? "点击推荐项才会加入；保存修改后才会入库。"
        : "没有找到足够相关的新建议，可以继续使用当前标签。";
      button.textContent = "重新生成";
    } catch (error) {
      status.textContent = error.message || "AI 推荐暂时不可用。";
    } finally {
      recommender.classList.remove("loading");
      button.disabled = false;
    }
  };

  button.addEventListener("click", loadSuggestions);
  if (recommender.dataset.autoRecommend === "true") {
    const url = new URL(window.location.href);
    url.searchParams.delete("recommend");
    window.history.replaceState({}, "", url);
    loadSuggestions();
  }
});

document.addEventListener("click", (event) => {
  const openButton = event.target.closest("[data-dialog-open]");
  if (openButton) {
    const dialog = document.getElementById(openButton.dataset.dialogOpen);
    if (dialog) dialog.showModal();
    return;
  }

  const closeButton = event.target.closest("[data-dialog-close]");
  if (closeButton) closeButton.closest("dialog")?.close();
});

document.querySelectorAll("[data-live-search]").forEach((form) => {
  const search = form.querySelector("[data-library-search]");
  const tag = form.querySelector("[data-library-tag]");
  const status = form.querySelector("[data-search-status]");
  const results = document.querySelector("[data-library-results]");
  if (!search || !tag || !results) return;

  let timer;
  let controller;

  const refresh = async () => {
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    const url = new URL(window.location.href);
    const query = search.value.trim();
    if (query) url.searchParams.set("q", query);
    else url.searchParams.delete("q");
    if (tag.value) url.searchParams.set("tag", tag.value);
    else url.searchParams.delete("tag");
    url.searchParams.delete("message");
    url.hash = "library";

    results.classList.add("loading");
    status.textContent = "正在筛选…";
    try {
      const response = await fetch(url, {
        headers: { Accept: "text/html" },
        signal: requestController.signal,
      });
      if (!response.ok) throw new Error("筛选失败");
      const html = await response.text();
      const nextPage = new DOMParser().parseFromString(html, "text/html");
      const nextResults = nextPage.querySelector("[data-library-results]");
      if (!nextResults) throw new Error("筛选结果不可用");
      results.replaceChildren(...nextResults.childNodes);
      window.history.replaceState({}, "", url);
      const count = results.querySelectorAll(".bookmark-card").length;
      status.textContent = count ? `已显示 ${count} 条` : "没有匹配结果";
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = "筛选暂时失败";
    } finally {
      if (controller === requestController) results.classList.remove("loading");
    }
  };

  const schedule = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(refresh, 180);
  };

  search.addEventListener("input", schedule);
  tag.addEventListener("change", refresh);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    refresh();
  });
  document.addEventListener("click", (event) => {
    const tagLink = event.target.closest(".bookmark-card .tag");
    if (!tagLink) return;
    event.preventDefault();
    tag.value = new URL(tagLink.href).searchParams.get("tag") || "";
    refresh();
  });
});

document.querySelectorAll("[data-library]").forEach((library) => {
  const buttons = [...library.querySelectorAll("[data-view-mode]")];
  const applyMode = (mode) => {
    const selected = mode === "list" ? "list" : "grid";
    library.classList.toggle("list-view", selected === "list");
    buttons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.viewMode === selected));
    });
    try { window.localStorage.setItem("bookmark-view", selected); } catch (_) {}
  };

  let initialMode = "grid";
  try { initialMode = window.localStorage.getItem("bookmark-view") || "grid"; } catch (_) {}
  applyMode(initialMode);
  buttons.forEach((button) => {
    button.addEventListener("click", () => applyMode(button.dataset.viewMode));
  });
});

document.addEventListener("click", (event) => {
  const card = event.target.closest("[data-card-link]");
  if (!card || event.target.closest("a, button, input, select, textarea, form, dialog")) return;
  window.location.href = card.dataset.cardLink;
});

document.addEventListener("keydown", (event) => {
  const card = event.target.closest("[data-card-link]");
  if (card && event.target === card && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    window.location.href = card.dataset.cardLink;
  }
});
