const copyButton = document.querySelector("[data-copy-token]");

copyButton?.addEventListener("click", async () => {
  const token = document.querySelector("[data-token-value]")?.textContent?.trim();
  if (!token) return;
  try {
    await navigator.clipboard.writeText(token);
    copyButton.textContent = "已复制";
  } catch (_) {
    copyButton.textContent = "复制失败，请手动选择";
  }
});
