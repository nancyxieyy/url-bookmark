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
