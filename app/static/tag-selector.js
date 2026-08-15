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

  const addNewTag = () => {
    const name = newTagInput.value.trim();
    if (!name) return;

    const existing = [...selector.querySelectorAll("[data-tag-option]")].find(
      (input) => input.value.toLocaleLowerCase() === name.toLocaleLowerCase(),
    );
    if (existing) {
      existing.checked = true;
    } else {
      const label = document.createElement("label");
      label.className = "tag-menu-option";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "tag_choices";
      checkbox.value = name;
      checkbox.checked = true;
      checkbox.dataset.tagOption = "";

      const check = document.createElement("span");
      check.className = "tag-check";
      check.setAttribute("aria-hidden", "true");
      check.textContent = "✓";

      const text = document.createElement("span");
      text.textContent = name;
      label.append(checkbox, check, text);
      options.prepend(label);
    }

    newTagInput.value = "";
    updateSummary();
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
