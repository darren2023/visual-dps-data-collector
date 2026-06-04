/**
 * 配置项旁「?」悬停说明（data-tip 纯文本，data-tip-html 支持简单 HTML）
 */
(function initFieldTips() {
  function escapeAttr(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;");
  }

  /** 生成问号按钮 HTML（供动态插入时使用） */
  window.fieldTipButton = function fieldTipButton(text, html = false) {
    const attr = html ? "data-tip-html" : "data-tip";
    return `<button type="button" class="field-tip" aria-label="字段说明" ${attr}="${escapeAttr(text)}">?</button>`;
  };

  document.querySelectorAll(".field-tip[data-tip-html]").forEach((btn) => {
    const html = btn.getAttribute("data-tip-html");
    if (!html) return;
    const pop = document.createElement("span");
    pop.className = "field-tip-pop";
    pop.setAttribute("role", "tooltip");
    pop.innerHTML = html;
    btn.appendChild(pop);
    btn.removeAttribute("data-tip-html");
  });

  document.querySelectorAll(".field-tip").forEach((btn) => {
    btn.addEventListener("click", (e) => e.preventDefault());
  });
})();
