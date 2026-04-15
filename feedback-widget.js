const STORAGE_KEY = "aic_feedback_v1";
const REPO_URL = "https://github.com/kodawarimax/ai-creator";

const SECTION_LABELS = {
  top: "トップ画面（ツール選択）",
  "manga-welcome": "漫画: モード選択",
  "manga-qa": "漫画: Q&A",
  "manga-generating": "漫画: 生成中",
  "design-editor": "デザインエディタ",
  slide: "スライド",
  global: "全体",
};

const SCREEN_TO_SECTION = {
  "screen-top": "top",
  "screen-welcome": "manga-welcome",
  "screen-qa": "manga-qa",
  "screen-generating": "manga-generating",
  "screen-design": "design-editor",
};

const CATEGORY_LABELS = {
  layout: "レイアウト",
  color: "カラー",
  typography: "タイポ",
  interaction: "インタラクション",
  flow: "情報設計",
  responsive: "モバイル",
  a11y: "アクセシビリティ",
  other: "その他",
};

const $ = (id) => document.getElementById(id);
const load = () => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
};
const save = (items) => localStorage.setItem(STORAGE_KEY, JSON.stringify(items));

let currentRating = 0;

function detectSection() {
  const active = document.querySelector(".screen.active");
  if (!active) return "top";
  return SCREEN_TO_SECTION[active.id] || "top";
}

function refreshCountBadge() {
  const items = load();
  const countEl = $("feedback-count");
  const listCountEl = $("feedback-list-count");
  if (countEl) {
    if (items.length > 0) {
      countEl.textContent = String(items.length);
      countEl.hidden = false;
    } else {
      countEl.hidden = true;
    }
  }
  if (listCountEl) listCountEl.textContent = String(items.length);
}

function refreshSectionTag() {
  const section = detectSection();
  const tagEl = $("feedback-section-tag");
  const selectEl = $("feedback-section-select");
  if (tagEl) tagEl.textContent = SECTION_LABELS[section] || section;
  if (selectEl) selectEl.value = section;
}

function renderList() {
  const listEl = $("feedback-list");
  if (!listEl) return;
  const items = load();
  if (items.length === 0) {
    listEl.innerHTML = '<div class="feedback-list-empty">まだフィードバックがありません。<br>「コメント追加」タブから投稿してください。</div>';
    return;
  }
  listEl.innerHTML = items
    .map((item, idx) => {
      const stars = "★".repeat(item.rating) + "☆".repeat(5 - item.rating);
      const section = SECTION_LABELS[item.section] || item.section;
      const category = CATEGORY_LABELS[item.category] || item.category;
      const date = new Date(item.createdAt).toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
      return `
        <div class="feedback-item">
          <button type="button" class="feedback-item-del" data-idx="${idx}" aria-label="削除">✕</button>
          <div class="feedback-item-head">
            <span class="feedback-item-section">${escapeHtml(section)}</span>
            <span class="feedback-item-stars" aria-label="${item.rating}つ星">${stars}</span>
          </div>
          <div class="feedback-item-meta">${escapeHtml(category)} · ${date}</div>
          <div class="feedback-item-body">${escapeHtml(item.comment)}</div>
        </div>
      `;
    })
    .join("");

  listEl.querySelectorAll(".feedback-item-del").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.idx, 10);
      const items = load();
      items.splice(idx, 1);
      save(items);
      renderList();
      refreshCountBadge();
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function showToast(msg) {
  const el = $("feedback-toast");
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => (el.hidden = true), 2000);
}

function setRating(n) {
  currentRating = n;
  document.querySelectorAll("#feedback-stars button").forEach((b) => {
    const v = parseInt(b.dataset.v, 10);
    b.classList.toggle("active", v <= n);
  });
}

function buildMarkdown(items) {
  const lines = [`# AIクリエイター デザインフィードバック (${items.length}件)`, ""];
  lines.push(`**送信日時**: ${new Date().toLocaleString("ja-JP")}`);
  lines.push(`**UserAgent**: ${navigator.userAgent}`);
  lines.push(`**画面サイズ**: ${window.innerWidth} × ${window.innerHeight}`);
  lines.push("");
  lines.push("---");
  items.forEach((item, i) => {
    const stars = "★".repeat(item.rating) + "☆".repeat(5 - item.rating);
    lines.push(`## ${i + 1}. ${SECTION_LABELS[item.section] || item.section}`);
    lines.push("");
    lines.push(`- **評価**: ${stars} (${item.rating}/5)`);
    lines.push(`- **カテゴリ**: ${CATEGORY_LABELS[item.category] || item.category}`);
    lines.push(`- **投稿時刻**: ${new Date(item.createdAt).toLocaleString("ja-JP")}`);
    lines.push("");
    lines.push("**コメント:**");
    lines.push("");
    lines.push(item.comment.split("\n").map((l) => "> " + l).join("\n"));
    lines.push("");
    lines.push("---");
  });
  return lines.join("\n");
}

function init() {
  const fab = $("feedback-fab");
  const panel = $("feedback-panel");
  const closeBtn = $("feedback-panel-close");
  if (!fab || !panel) return;

  fab.addEventListener("click", () => {
    const hidden = panel.hasAttribute("hidden");
    if (hidden) {
      refreshSectionTag();
      panel.removeAttribute("hidden");
      renderList();
    } else {
      panel.setAttribute("hidden", "");
    }
  });

  closeBtn?.addEventListener("click", () => panel.setAttribute("hidden", ""));

  document.querySelectorAll(".feedback-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      document.querySelectorAll(".feedback-tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".feedback-tab-pane").forEach((p) => p.classList.toggle("active", p.id === `feedback-pane-${target}`));
      if (target === "list") renderList();
    });
  });

  const starsEl = $("feedback-stars");
  starsEl?.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => setRating(parseInt(b.dataset.v, 10)));
    b.addEventListener("mouseenter", () => {
      const v = parseInt(b.dataset.v, 10);
      starsEl.querySelectorAll("button").forEach((bb) => bb.classList.toggle("hover-fill", parseInt(bb.dataset.v, 10) <= v));
    });
  });
  starsEl?.addEventListener("mouseleave", () => {
    starsEl.querySelectorAll("button").forEach((bb) => bb.classList.remove("hover-fill"));
  });

  $("feedback-clear")?.addEventListener("click", () => {
    $("feedback-comment").value = "";
    setRating(0);
  });

  $("feedback-save")?.addEventListener("click", () => {
    const comment = $("feedback-comment").value.trim();
    if (!comment) {
      showToast("コメントを入力してください");
      return;
    }
    if (currentRating === 0) {
      showToast("評価（星）を選択してください");
      return;
    }
    const items = load();
    items.push({
      section: $("feedback-section-select").value,
      category: $("feedback-category").value,
      rating: currentRating,
      comment,
      createdAt: Date.now(),
    });
    save(items);
    $("feedback-comment").value = "";
    setRating(0);
    refreshCountBadge();
    showToast("保存しました");
  });

  $("feedback-copy")?.addEventListener("click", async () => {
    const items = load();
    if (items.length === 0) return showToast("まだフィードバックがありません");
    const md = buildMarkdown(items);
    try {
      await navigator.clipboard.writeText(md);
      showToast("クリップボードにコピーしました");
    } catch {
      showToast("コピー失敗");
    }
  });

  $("feedback-delete-all")?.addEventListener("click", () => {
    if (!confirm("保存済みのフィードバックを全て削除します。よろしいですか？")) return;
    save([]);
    renderList();
    refreshCountBadge();
    showToast("削除しました");
  });

  $("feedback-submit-github")?.addEventListener("click", () => {
    const items = load();
    if (items.length === 0) return showToast("まだフィードバックがありません");
    const body = buildMarkdown(items);
    const title = `[Design] フィードバック ${items.length}件 (${new Date().toLocaleDateString("ja-JP")})`;
    const params = new URLSearchParams({
      title,
      body,
      labels: "design,feedback",
    });
    const url = `${REPO_URL}/issues/new?${params.toString()}`;
    if (url.length > 7000) {
      // URL too long for GitHub — fallback to copy
      navigator.clipboard.writeText(body).then(() => {
        showToast("本文をコピー → Issue作成画面へ");
        setTimeout(() => window.open(`${REPO_URL}/issues/new/choose`, "_blank"), 400);
      });
      return;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  });

  refreshCountBadge();

  const observer = new MutationObserver(() => {
    if (!panel.hasAttribute("hidden")) refreshSectionTag();
  });
  document.querySelectorAll(".screen").forEach((s) => observer.observe(s, { attributes: true, attributeFilter: ["class"] }));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
