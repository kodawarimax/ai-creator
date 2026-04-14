// ===== AI Creator Studio: Frontend Controller =====
import JSZip from 'jszip';
import { jsPDF } from 'jspdf';
import { createClient } from '@supabase/supabase-js';

// ===== Config =====
const API_BASE = window.location.hostname === 'localhost'
  ? "http://localhost:5051"
  : "https://ai-creator-api.onrender.com";

// ===== State =====
const state = {
  story: null,
  panels: null,
  answers: {},
  analyzedStylePrompt: null,
  characterImage: null,
  // Design Editor State
  designPages: [], // Array of SVG strings
  currentPageIndex: 0,
  selectedElement: null,
  isDragging: false,
  isResizing: false,
  dragStart: { x: 0, y: 0 },
  resizeHandle: null,
  // Magazine Scan State
  designSpec: null, // Extracted design spec from scan-pdf
  pageSpecs: [],    // Per-page specs
  ghostVisible: true,
};

const bubbleSettings = { style: "rounded", font: "gothic" };
const SVG_NS = "http://www.w3.org/2000/svg";

// ===== DOM Helper =====
const $ = (id) => document.getElementById(id);

function showScreen(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(id).classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showAILog(msg, containerId = "ai-logs") {
  const logEl = $(containerId);
  if (!logEl) return;
  const entry = document.createElement("div");
  entry.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  logEl.appendChild(entry);
  logEl.scrollTop = logEl.scrollHeight;
}

// ===== Tool & Navigation Handlers =====
$("btn-tool-manga")?.addEventListener("click", () => showScreen("screen-welcome"));
$("btn-tool-slide")?.addEventListener("click", () => showScreen("screen-slide-placeholder")); // Future expansion
$("btn-tool-design")?.addEventListener("click", () => {
  showScreen("screen-design");
  window.dispatchEvent(new Event('resize'));
});
$("design-btn-back")?.addEventListener("click", () => showScreen("screen-top"));
$("manga-btn-back-top")?.addEventListener("click", () => showScreen("screen-top"));

// ===================================================================
// AI Design Creator (Affinity Lite Core)
// ===================================================================
const svgCanvas = $('main-svg');
const canvasContainer = $('canvas-container');
const loadingOverlay = $('ai-loading');

// Project File Loader (Demo / Efficiency)
$("btn-load-workspace-pdf")?.addEventListener("click", () => {
  const filename = $("workspace-pdf-select").value;
  if (!filename) return alert("Select a project file first.");
  
  loadingOverlay.classList.remove("hidden");
  $("ai-status").textContent = `⚡️ Loading ${filename} from project workspace...`;
  
  fetch(`${API_BASE}/api/design/project-load`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename })
  }).then(resp => {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    
    function read() {
      reader.read().then(({ done, value }) => {
        if (done) return;
        const chunk = decoder.decode(value);
        chunk.split('\n\n').forEach(line => {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.replace('data: ', ''));
            if (data.status === "progress") {
               $("ai-status").textContent = `Processing Page ${data.page}/${data.total}...`;
               showAILog(data.message);
            }
            if (data.status === "complete") {
               renderExtractedPages(data.pages);
               loadingOverlay.classList.add("hidden");
               showAILog("✅ Project file loaded successfully.");
            }
            if (data.status === "error") {
               alert(`Load Error: ${data.message}`);
               loadingOverlay.classList.add("hidden");
            }
          }
        });
        read();
      });
    }
    read();
  });
});

// PDF Import with God-Tier SSE Logging
// "Import PDF" now uses the same auto-templatize pipeline as "雑誌スキャン"
$("btn-import-pdf")?.addEventListener("click", () => $("scan-pdf-input").click());

function renderExtractedPages(pages) {
  if (!pages || pages.length === 0) return;
  state.designPages = pages;
  state.currentPageIndex = 0;
  updatePageUI();
}

function updatePageUI() {
  const pageIdx = state.currentPageIndex;
  const svgContent = state.designPages[pageIdx];
  if (!svgContent) return;

  const parser = new DOMParser();
  const doc = parser.parseFromString(svgContent, "image/svg+xml");
  const newSvg = doc.documentElement;
  
  // Preserve essential system groups
  const bg = svgCanvas.querySelector('#bg-rect');
  const guides = svgCanvas.querySelector('#guides-group');
  svgCanvas.innerHTML = '';
  if (bg) svgCanvas.appendChild(bg);
  if (guides) svgCanvas.appendChild(guides);
  
  // Inject new elements
  Array.from(newSvg.children).forEach(child => {
    if (child.id !== 'bg-rect' && child.id !== 'guides-group') {
      svgCanvas.appendChild(child.cloneNode(true));
    }
  });

  const totalP = state.scanTotalPages || state.designPages.length;
  $("page-indicator").textContent = `Page ${pageIdx + 1} / ${totalP}`;
  syncLayersPanel();
  initVectorEditor();
}

function syncLayersPanel() {
  const list = $("layers-list");
  list.innerHTML = "";
  const elements = Array.from(svgCanvas.querySelectorAll("g.selectable")).reverse();
  
  if (elements.length === 0) {
    list.innerHTML = '<div class="layer-item placeholder">No elements</div>';
    return;
  }

  elements.forEach(el => {
    const item = document.createElement("div");
    item.className = "layer-item";
    if (state.selectedElement === el) item.classList.add("active");
    
    const typeIcon = el.dataset.type === "textblock" ? "T" : (el.dataset.type === "image" ? "🖼" : "square");
    item.innerHTML = `<span style="margin-right:8px">${typeIcon}</span><span>${el.dataset.label || el.id}</span>`;
    
    item.onclick = () => selectElement(el);
    list.appendChild(item);
  });
}

function showContextMenu(x, y, el) {
  const menu = $("element-context-menu");
  if (!menu) return;
  const isText = el.dataset.type === "textblock";
  const isPhoto = el.dataset.role === "photo" || el.dataset.type === "image";
  menu.querySelector('[data-action="edit"]').style.display = isText ? "" : "none";
  menu.querySelector('[data-action="replace-image"]').style.display = isPhoto ? "" : "none";
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.classList.remove("hidden");
}

function hideContextMenu() {
  $("element-context-menu")?.classList.add("hidden");
}

function initVectorEditor() {
  const tooltip = $("element-tooltip");

  svgCanvas.querySelectorAll('g.selectable').forEach(el => {
    el.style.pointerEvents = 'all';
    el.onmousedown = (e) => {
      e.stopPropagation();
      hideContextMenu();
      selectElement(el);
      startDrag(e);
    };

    el.onmouseover = (e) => {
      if (tooltip) {
        const label = [el.dataset.role, el.dataset.label].filter(Boolean).join(": ");
        if (label) {
          tooltip.textContent = label;
          tooltip.classList.remove("hidden");
          tooltip.style.left = `${e.clientX + 12}px`;
          tooltip.style.top = `${e.clientY - 24}px`;
        }
      }
    };

    el.onmousemove = (e) => {
      if (tooltip && !tooltip.classList.contains("hidden")) {
        tooltip.style.left = `${e.clientX + 12}px`;
        tooltip.style.top = `${e.clientY - 24}px`;
      }
    };

    el.onmouseout = () => {
      if (tooltip) tooltip.classList.add("hidden");
    };

    el.oncontextmenu = (e) => {
      e.preventDefault();
      e.stopPropagation();
      selectElement(el);
      showContextMenu(e.clientX, e.clientY, el);
    };

    // Double-click: inline contenteditable text editing or image replace
    el.ondblclick = (e) => {
      e.stopPropagation();

      if (el.dataset.role === 'photo' || el.dataset.type === 'image') {
        const input = $('image-replace-input');
        if (input) { input._targetElement = el; input.click(); }
        return;
      }

      const texts = el.querySelectorAll("text");
      if (texts.length === 0) return;

      const bbox = el.getBBox();
      const fs = parseFloat(texts[0]?.getAttribute("font-size") || 4);
      const fill = texts[0]?.getAttribute("fill") || "#000";
      const currentText = Array.from(texts).map(t => t.textContent).join("\n");

      const fo = document.createElementNS(SVG_NS, "foreignObject");
      fo.setAttribute("x", bbox.x - 1);
      fo.setAttribute("y", bbox.y - 1);
      fo.setAttribute("width", Math.max(bbox.width + 10, 40));
      fo.setAttribute("height", Math.max(bbox.height + 10, fs * 2));
      fo.setAttribute("class", "inline-edit-fo");

      const div = document.createElement("div");
      div.setAttribute("contenteditable", "true");
      div.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
      div.style.cssText = `font-family:YuGothic,sans-serif;font-size:${fs}px;color:${fill};background:rgba(255,255,255,0.95);border:1px solid #00f0ff;padding:2px 4px;outline:none;white-space:pre-wrap;min-height:${fs}px;box-sizing:border-box;width:100%;height:100%;overflow:auto;`;
      div.textContent = currentText;
      fo.appendChild(div);
      svgCanvas.appendChild(fo);
      div.focus();

      const range = document.createRange();
      range.selectNodeContents(div);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);

      const commit = () => {
        const newText = div.textContent || "";
        if (newText !== currentText) {
          const lines = newText.split("\n");
          texts.forEach((t, i) => { t.textContent = i < lines.length ? lines[i] : ""; });
        }
        fo.remove();
        updatePropertiesUI(el);
      };

      div.addEventListener("keydown", (ke) => {
        if (ke.key === "Escape") { ke.preventDefault(); commit(); }
      });
      div.addEventListener("blur", commit);
    };
  });
}

function selectElement(el) {
  if (state.selectedElement) state.selectedElement.classList.remove('selected-highlight');
  state.selectedElement = el;
  el.classList.add('selected-highlight');
  
  updatePropertiesUI(el);
  syncLayersPanel();
  updateSelectionBox();
}

function updatePropertiesUI(el) {
  const type = el.dataset.type;
  // Get primary child (rect, text, image)
  const child = el.firstElementChild;
  if (!child) return;

  const x = child.getAttribute("x") || 0;
  const y = child.getAttribute("y") || 0;
  const w = child.getAttribute("width") || 0;
  const h = child.getAttribute("height") || 0;

  $("prop-x").value = x;
  $("prop-y").value = y;
  $("prop-w").value = w;
  $("prop-h").value = h;

  const isText = type === "textblock";
  $("text-toolbar").style.display = isText ? "" : "none";
  $("text-toolbar-hr").style.display = isText ? "" : "none";

  if (isText) {
    const texts = el.querySelectorAll("text");
    const t0 = texts[0];
    $("prop-text-content").value = Array.from(texts).map(t => t.textContent).join("\n");
    const fs = t0?.getAttribute("font-size") || 12;
    $("prop-font-size").value = fs;
    const fill = t0?.getAttribute("fill") || "#000000";
    $("prop-fill").value = fill;
    $("prop-fill-hex").value = fill;
    $("prop-text-color").value = fill;

    // Font family
    const ff = t0?.getAttribute("font-family") || "YuGothic";
    $("prop-font-family").value = ff;

    // Bold
    const fw = t0?.getAttribute("font-weight") || "normal";
    $("btn-bold").classList.toggle("active", fw === "bold");

    // Italic
    const fstyle = t0?.getAttribute("font-style") || "normal";
    $("btn-italic").classList.toggle("active", fstyle === "italic");

    // Text alignment
    const anchor = t0?.getAttribute("text-anchor") || "start";
    $("btn-align-l").classList.toggle("active", anchor === "start");
    $("btn-align-c").classList.toggle("active", anchor === "middle");
    $("btn-align-r").classList.toggle("active", anchor === "end");
  } else {
    const rectEl = el.querySelector("rect") || (child.tagName === "rect" ? child : null);
    if (rectEl) {
      const fillVal = rectEl.getAttribute("fill") || "#000000";
      $("prop-fill").value = fillVal;
      $("prop-fill-hex").value = fillVal;
      const strokeVal = rectEl.getAttribute("stroke") || "#000000";
      $("prop-stroke").value = strokeVal;
      $("prop-stroke-width").value = rectEl.getAttribute("stroke-width") || 0;
    }
  }
}

function updateSelectionBox() {
  const box = $("selection-box");
  if (!state.selectedElement) {
    box.classList.add("hidden");
    return;
  }
  
  const el = state.selectedElement.firstElementChild;
  const rect = el.getBBox();
  const ctm = svgCanvas.getScreenCTM();
  
  // Calculate screen pos for overlay handles
  const pt = svgCanvas.createSVGPoint();
  pt.x = rect.x; pt.y = rect.y;
  const p1 = pt.matrixTransform(el.getScreenCTM());
  
  pt.x = rect.x + rect.width; pt.y = rect.y + rect.height;
  const p2 = pt.matrixTransform(el.getScreenCTM());
  
  const containerRect = canvasContainer.getBoundingClientRect();
  
  box.style.left = `${p1.x - containerRect.left}px`;
  box.style.top = `${p1.y - containerRect.top}px`;
  box.style.width = `${p2.x - p1.x}px`;
  box.style.height = `${p2.y - p1.y}px`;
  box.classList.remove("hidden");
}

// Wire handle mousedown so all 8 handles trigger resize
$("selection-box")?.addEventListener("mousedown", (e) => {
  if (!e.target.classList.contains("al-handle")) return;
  e.stopPropagation();
  e.preventDefault();
  startDrag(e);
});

function detectResizeHandle(e) {
  const box = $("selection-box");
  if (!box || box.classList.contains("hidden")) return null;
  const target = e.target;
  if (!target.classList.contains("al-handle")) return null;
  if (target.classList.contains("al-nw")) return "nw";
  if (target.classList.contains("al-ne")) return "ne";
  if (target.classList.contains("al-sw")) return "sw";
  if (target.classList.contains("al-se")) return "se";
  if (target.classList.contains("al-n")) return "n";
  if (target.classList.contains("al-e")) return "e";
  if (target.classList.contains("al-s")) return "s";
  if (target.classList.contains("al-w")) return "w";
  return null;
}

function startDrag(e) {
  const handle = detectResizeHandle(e);
  state.isDragging = !handle;
  state.isResizing = !!handle;
  state.resizeHandle = handle;
  state.dragStart = { x: e.clientX, y: e.clientY };

  const svgRect = svgCanvas.getBoundingClientRect();
  const scaleX = 420 / svgRect.width;
  const scaleY = 297 / svgRect.height;

  const onMouseMove = (ev) => {
    if (!state.selectedElement) return;
    const dx = (ev.clientX - state.dragStart.x) * scaleX;
    const dy = (ev.clientY - state.dragStart.y) * scaleY;

    if (state.isResizing) {
      const child = state.selectedElement.firstElementChild;
      if (child) {
        let x = parseFloat(child.getAttribute("x") || 0);
        let y = parseFloat(child.getAttribute("y") || 0);
        let w = parseFloat(child.getAttribute("width") || 0);
        let h = parseFloat(child.getAttribute("height") || 0);
        const h_ = state.resizeHandle;
        if (h_ === "se") { w = Math.max(1, w + dx); h = Math.max(1, h + dy); }
        else if (h_ === "sw") { x += dx; w = Math.max(1, w - dx); h = Math.max(1, h + dy); }
        else if (h_ === "ne") { y += dy; w = Math.max(1, w + dx); h = Math.max(1, h - dy); }
        else if (h_ === "nw") { x += dx; y += dy; w = Math.max(1, w - dx); h = Math.max(1, h - dy); }
        else if (h_ === "e") { w = Math.max(1, w + dx); }
        else if (h_ === "w") { x += dx; w = Math.max(1, w - dx); }
        else if (h_ === "s") { h = Math.max(1, h + dy); }
        else if (h_ === "n") { y += dy; h = Math.max(1, h - dy); }
        child.setAttribute("x", x); child.setAttribute("y", y);
        child.setAttribute("width", w); child.setAttribute("height", h);
      }
    } else if (state.isDragging) {
      Array.from(state.selectedElement.children).forEach(child => {
        const cx = parseFloat(child.getAttribute("x") || 0);
        const cy = parseFloat(child.getAttribute("y") || 0);
        child.setAttribute("x", cx + dx);
        child.setAttribute("y", cy + dy);
      });
    }

    state.dragStart = { x: ev.clientX, y: ev.clientY };
    updateSelectionBox();
    updatePropertiesUI(state.selectedElement);
  };

  const onMouseUp = () => {
    state.isDragging = false;
    state.isResizing = false;
    state.resizeHandle = null;
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
  };

  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);
}

// Page Navigation
async function autoTemplatizeAndShow(pageIdx) {
  const pageNum = pageIdx + 1;
  if (state.scanId && !state.designPages[pageIdx]) {
    loadingOverlay.classList.remove('hidden');
    $('ai-status').textContent = `Page ${pageNum} をAI解析中...`;
    try {
      const res = await fetch(`${API_BASE}/api/design/templatize/${state.scanId}/${pageNum}`, { method: 'POST' });
      if (!res.ok) throw new Error(`Templatize error: ${res.status}`);
      const data = await res.json();
      state.designPages[pageIdx] = data.svg;
      state.pageSpecs[pageIdx] = data.spec;
      state.previewMode = false;
      updatePageUI();
      syncLayersPanel();
      initVectorEditor();
      $("page-indicator").textContent = `Page ${pageNum} / ${state.scanTotalPages} (編集モード)`;
      showAILog(`Page ${pageNum} テンプレート化完了: ${data.spec.zones?.length || 0}ゾーン`, "ai-step-logs");
    } catch (err) {
      showPreviewPage(pageNum);
      showAILog(`Page ${pageNum} テンプレート化失敗: ${err.message}`, "ai-step-logs");
    } finally {
      loadingOverlay.classList.add('hidden');
    }
  } else {
    updatePageUI();
    syncLayersPanel();
    initVectorEditor();
  }
}

$("btn-page-prev")?.addEventListener("click", async () => {
  if (state.currentPageIndex > 0) {
    state.currentPageIndex--;
    await autoTemplatizeAndShow(state.currentPageIndex);
  }
});
$("btn-page-next")?.addEventListener("click", async () => {
  const maxIdx = state.scanId ? (state.scanTotalPages - 1) : (state.designPages.length - 1);
  if (state.currentPageIndex < maxIdx) {
    state.currentPageIndex++;
    await autoTemplatizeAndShow(state.currentPageIndex);
  }
});

// Property panel → SVG sync
$("prop-text-content")?.addEventListener("input", () => {
  if (!state.selectedElement) return;
  const texts = state.selectedElement.querySelectorAll("text");
  const lines = $("prop-text-content").value.split("\n");
  texts.forEach((t, i) => { if (i < lines.length) t.textContent = lines[i]; });
});

$("prop-fill")?.addEventListener("input", () => {
  if (!state.selectedElement) return;
  const hex = $("prop-fill").value;
  $("prop-fill-hex").value = hex;
  const type = state.selectedElement.dataset.type;
  if (type === "textblock") {
    state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("fill", hex));
  } else {
    const rect = state.selectedElement.querySelector("rect");
    if (rect) rect.setAttribute("fill", hex);
  }
});

$("prop-fill-hex")?.addEventListener("change", () => {
  const hex = $("prop-fill-hex").value;
  if (/^#[0-9a-fA-F]{6}$/.test(hex)) {
    $("prop-fill").value = hex;
    $("prop-fill").dispatchEvent(new Event("input"));
  }
});

["prop-x", "prop-y", "prop-w", "prop-h"].forEach(id => {
  $(id)?.addEventListener("change", () => {
    if (!state.selectedElement) return;
    const child = state.selectedElement.firstElementChild;
    if (!child) return;
    child.setAttribute("x", $("prop-x").value);
    child.setAttribute("y", $("prop-y").value);
    if (child.getAttribute("width") !== null) child.setAttribute("width", $("prop-w").value);
    if (child.getAttribute("height") !== null) child.setAttribute("height", $("prop-h").value);
    updateSelectionBox();
  });
});

// Text toolbar event listeners
$("prop-font-family")?.addEventListener("change", () => {
  if (!state.selectedElement) return;
  const ff = $("prop-font-family").value;
  state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("font-family", ff));
});

$("prop-font-size")?.addEventListener("input", () => {
  if (!state.selectedElement) return;
  const fs = $("prop-font-size").value;
  state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("font-size", fs));
});

$("btn-bold")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  const isActive = $("btn-bold").classList.toggle("active");
  const fw = isActive ? "bold" : "normal";
  state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("font-weight", fw));
});

$("btn-italic")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  const isActive = $("btn-italic").classList.toggle("active");
  const fs = isActive ? "italic" : "normal";
  state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("font-style", fs));
});

$("btn-align-l")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("text-anchor", "start"));
  $("btn-align-l").classList.add("active");
  $("btn-align-c").classList.remove("active");
  $("btn-align-r").classList.remove("active");
});

$("btn-align-c")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("text-anchor", "middle"));
  $("btn-align-l").classList.remove("active");
  $("btn-align-c").classList.add("active");
  $("btn-align-r").classList.remove("active");
});

$("btn-align-r")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("text-anchor", "end"));
  $("btn-align-l").classList.remove("active");
  $("btn-align-c").classList.remove("active");
  $("btn-align-r").classList.add("active");
});

$("prop-text-color")?.addEventListener("input", () => {
  if (!state.selectedElement) return;
  const col = $("prop-text-color").value;
  $("prop-fill").value = col;
  $("prop-fill-hex").value = col;
  state.selectedElement.querySelectorAll("text").forEach(t => t.setAttribute("fill", col));
});

$("prop-stroke")?.addEventListener("input", () => {
  if (!state.selectedElement) return;
  const col = $("prop-stroke").value;
  state.selectedElement.querySelectorAll("rect").forEach(r => r.setAttribute("stroke", col));
});

$("prop-stroke-width")?.addEventListener("input", () => {
  if (!state.selectedElement) return;
  const sw = $("prop-stroke-width").value;
  state.selectedElement.querySelectorAll("rect").forEach(r => r.setAttribute("stroke-width", sw));
});

$("btn-duplicate")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  const clone = state.selectedElement.cloneNode(true);
  // Offset by 5mm
  Array.from(clone.children).forEach(child => {
    const cx = parseFloat(child.getAttribute("x") || 0);
    const cy = parseFloat(child.getAttribute("y") || 0);
    child.setAttribute("x", cx + 5);
    child.setAttribute("y", cy + 5);
  });
  // Assign a new id to avoid duplicates
  clone.id = `el-${Date.now()}`;
  clone.dataset.id = clone.id;
  svgCanvas.appendChild(clone);
  // Re-init editor on the clone and select it
  clone.style.pointerEvents = 'all';
  clone.onmousedown = (e) => { e.stopPropagation(); selectElement(clone); startDrag(e); };
  clone.ondblclick = state.selectedElement.ondblclick;
  selectElement(clone);
  syncLayersPanel();
});

// ===================================================================
// Context Menu
// ===================================================================
$("element-context-menu")?.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;
  const el = state.selectedElement;
  hideContextMenu();
  if (!el) return;

  if (action === "edit") {
    el.ondblclick?.(new MouseEvent("dblclick"));
  } else if (action === "replace-image") {
    const input = $("image-replace-input");
    if (input) { input._targetElement = el; input.click(); }
  } else if (action === "bring-front") {
    el.parentNode.appendChild(el);
    initVectorEditor(); syncLayersPanel();
  } else if (action === "send-back") {
    el.parentNode.insertBefore(el, el.parentNode.firstElementChild);
    initVectorEditor(); syncLayersPanel();
  } else if (action === "bring-forward") {
    const next = el.nextElementSibling;
    if (next) el.parentNode.insertBefore(next, el);
    initVectorEditor(); syncLayersPanel();
  } else if (action === "send-backward") {
    const prev = el.previousElementSibling;
    if (prev) el.parentNode.insertBefore(el, prev);
    initVectorEditor(); syncLayersPanel();
  } else if (action === "duplicate") {
    $("btn-duplicate")?.click();
  } else if (action === "delete") {
    $("btn-delete-element")?.click();
  }
});

document.addEventListener("click", (e) => {
  if (!e.target.closest("#element-context-menu")) hideContextMenu();
});

// Image Replace Handler
$("image-replace-input")?.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const el = e.target._targetElement;
  if (!el) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    const b64 = ev.target.result;
    let img = el.querySelector('image');
    if (img) {
      img.setAttribute('href', b64);
    } else {
      const rect = el.querySelector('rect');
      const x = rect?.getAttribute('x') || 0;
      const y = rect?.getAttribute('y') || 0;
      const w = rect?.getAttribute('width') || 50;
      const h = rect?.getAttribute('height') || 50;
      el.innerHTML = '';
      const imgEl = document.createElementNS(SVG_NS, 'image');
      imgEl.setAttribute('x', x);
      imgEl.setAttribute('y', y);
      imgEl.setAttribute('width', w);
      imgEl.setAttribute('height', h);
      imgEl.setAttribute('href', b64);
      imgEl.setAttribute('preserveAspectRatio', 'xMidYMid slice');
      el.appendChild(imgEl);
      el.dataset.type = 'image';
    }
    syncLayersPanel();
  };
  reader.readAsDataURL(file);
  e.target.value = '';
});

// Keyboard Shortcuts
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;

  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (state.selectedElement) {
      state.selectedElement.remove();
      state.selectedElement = null;
      updateSelectionBox();
      syncLayersPanel();
    }
  }

  if ((e.metaKey || e.ctrlKey) && e.key === 'd') {
    e.preventDefault();
    $("btn-duplicate")?.click();
  }

  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key) && state.selectedElement) {
    e.preventDefault();
    const step = e.shiftKey ? 5 : 1;
    const dx = e.key === 'ArrowRight' ? step : e.key === 'ArrowLeft' ? -step : 0;
    const dy = e.key === 'ArrowDown' ? step : e.key === 'ArrowUp' ? -step : 0;
    Array.from(state.selectedElement.children).forEach(child => {
      const cx = parseFloat(child.getAttribute("x") || 0);
      const cy = parseFloat(child.getAttribute("y") || 0);
      child.setAttribute("x", cx + dx);
      child.setAttribute("y", cy + dy);
    });
    updateSelectionBox();
    updatePropertiesUI(state.selectedElement);
  }

  if (e.key === 'Escape') {
    if (state.selectedElement) {
      state.selectedElement.classList.remove('selected-highlight');
      state.selectedElement = null;
      updateSelectionBox();
    }
    hideContextMenu();
  }
});

// ===================================================================
// AI Manga Logic (Legacy Support & Refinement)
// ===================================================================
// ... (Preservation of QUESTIONS, renderQuestion, selectChoice etc.) ...
// Note: All Manga Fetch calls will now point to Port 5051

// Alignment Tools
$("btn-align-left")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  Array.from(state.selectedElement.children).forEach(child => child.setAttribute("x", 10));
  updateSelectionBox();
  updatePropertiesUI(state.selectedElement);
});

$("btn-align-center")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  const rect = state.selectedElement.getBBox();
  const dx = 210 - (rect.x + rect.width / 2);
  Array.from(state.selectedElement.children).forEach(child => {
    const cx = parseFloat(child.getAttribute("x") || 0);
    child.setAttribute("x", cx + dx);
  });
  updateSelectionBox();
  updatePropertiesUI(state.selectedElement);
});

// Delete Logic
$("btn-delete-element")?.addEventListener("click", () => {
  if (!state.selectedElement) return;
  state.selectedElement.remove();
  state.selectedElement = null;
  updateSelectionBox();
  syncLayersPanel();
});

// ===================================================================
// AI Producer Suite (Productivity Logic)
// ===================================================================
$("btn-magic-fill")?.addEventListener("click", async () => {
  const theme = $("theme-prompt").value;
  if (!theme) return alert("Please enter a theme prompt first.");

  const elements = Array.from(svgCanvas.querySelectorAll("g.selectable")).map(el => ({
    id: el.dataset.id,
    role: el.dataset.role,
    label: el.dataset.label,
    current_text: Array.from(el.querySelectorAll("text")).map(t => t.textContent).join(" ")
  }));

  loadingOverlay.classList.remove("hidden");
  $("ai-status").textContent = "✨ AI Producing Magic...";
  showAILog(`Applying theme: "${theme}" to ${elements.length} elements.`);

  try {
    const res = await fetch(`${API_BASE}/api/magic/autofill`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme, elements })
    });
    const data = await res.json();

    if (data.results) {
      data.results.forEach(result => {
        const el = svgCanvas.querySelector(`[data-id="${result.id}"]`);
        if (!el) return;
        const texts = el.querySelectorAll("text");
        const lines = result.content.split("\n");
        lines.forEach((line, i) => { if (texts[i]) texts[i].textContent = line; });
      });
      showAILog("✨ Magic Autofill complete!");
    }
  } catch (err) {
    showAILog(`Magic Error: ${err.message}`);
  } finally {
    loadingOverlay.classList.add("hidden");
  }
});

$("btn-sync-styles")?.addEventListener("click", () => {
  const primaryColor = $("style-primary").value;
  const headlineFont = $("style-font-headline").value;

  // Sync Headlines
  svgCanvas.querySelectorAll('g[data-role="headline"], g[data-role="subheadline"]').forEach(el => {
    el.querySelectorAll("text").forEach(t => {
      t.setAttribute("fill", primaryColor);
      t.style.fontFamily = headlineFont;
    });
  });

  // Sync decorative rects
  svgCanvas.querySelectorAll('g[data-role="decoration"] rect, g[data-role="frame"] rect').forEach(r => {
    r.setAttribute("fill", primaryColor);
  });

  showAILog("🎨 Styles synced across current page.");
});

// ===================================================================
// Video Production Logic (Remotion Bridge)
// ===================================================================
const videoModal = $("video-editor-modal");

$("btn-video-editor")?.addEventListener("click", () => {
  videoModal.classList.remove("hidden");
  showAILog("🎬 Preparing Video Composition...");
});

$("btn-close-video")?.addEventListener("click", () => {
  videoModal.classList.add("hidden");
});

$("btn-trigger-render")?.addEventListener("click", async () => {
  const elements = Array.from(svgCanvas.querySelectorAll("g.selectable")).map(el => ({
    id: el.dataset.id,
    type: el.dataset.type,
    role: el.dataset.role,
    x: parseFloat(el.firstElementChild.getAttribute("x") || 0),
    y: parseFloat(el.firstElementChild.getAttribute("y") || 0),
    w: parseFloat(el.firstElementChild.getAttribute("width") || 0),
    h: parseFloat(el.firstElementChild.getAttribute("height") || 0),
    content: Array.from(el.querySelectorAll("text")).map(t => t.textContent).join("\n"),
    href: el.querySelector("image")?.getAttribute("href")
  }));

  const preset = $("video-preset").value;
  const duration = $("video-duration").value;

  $("btn-trigger-render").disabled = true;
  $("btn-trigger-render").textContent = "⏳ Rendering...";
  showAILog(`🚀 Rendering ${duration}s video (Preset: ${preset})...`);

  try {
    const res = await fetch(`${API_BASE}/api/video/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ elements, page_num: state.currentPage, preset, duration })
    });
    const data = await res.json();
    
    if (data.status === "processing") {
      showAILog(`✅ Job started: ${data.job_id}. Checking status...`);
      pollRenderStatus(data.job_id);
    }
  } catch (err) {
    showAILog(`❌ Render Error: ${err.message}`);
    $("btn-trigger-render").disabled = false;
    $("btn-trigger-render").textContent = "🚀 Start MP4 Export";
  }
});

async function pollRenderStatus(jobId) {
  const check = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/video/status/${jobId}`);
      const data = await res.json();
      if (data.status === "complete") {
        showAILog("🎉 Video Ready! Downloading...");
        window.location.href = `${API_BASE}${data.url}`;
        $("btn-trigger-render").disabled = false;
        $("btn-trigger-render").textContent = "🚀 Start MP4 Export";
      } else {
        setTimeout(check, 3000);
      }
    } catch (e) {
      console.error(e);
    }
  };
  check();
}

// ===================================================================
// Designer-First Pipeline: Preview → Design System → Templatize
// ===================================================================

// Phase 1: Instant Preview
$("btn-scan-magazine")?.addEventListener("click", () => $("scan-pdf-input").click());
$("scan-pdf-input")?.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('pdf', file);

  loadingOverlay.classList.remove('hidden');
  $('ai-status').textContent = "PDFプレビュー生成中...";
  $('ai-step-logs').innerHTML = '';

  try {
    // Phase 1: Instant preview (no AI, <1s)
    const res = await fetch(`${API_BASE}/api/design/preview-pdf`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`Server Error: ${res.status}`);
    const data = await res.json();

    state.scanId = data.scan_id;
    state.scanTotalPages = data.total_pages;
    state.previewPages = data.pages;
    state.currentPageIndex = 0;
    state.previewMode = true;

    // Show filmstrip
    renderFilmstrip(data.pages);
    showAILog(`${data.total_pages}ページのプレビュー完了`, "ai-step-logs");

    // Auto-templatize first page immediately (no manual button needed)
    $('ai-status').textContent = "ページ1をAI解析中（要素を自動検出）...";
    showAILog("AI Visionでページ1の要素を自動検出中...", "ai-step-logs");
    try {
      const tRes = await fetch(`${API_BASE}/api/design/templatize/${data.scan_id}/1`, { method: 'POST' });
      if (!tRes.ok) throw new Error(`Templatize error: ${tRes.status}`);
      const tData = await tRes.json();
      state.previewMode = false;
      state.designPages = state.designPages || [];
      state.designPages[0] = tData.svg;
      state.pageSpecs[0] = tData.spec;
      updatePageUI();
      syncLayersPanel();
      initVectorEditor();
      $("page-indicator").textContent = `Page 1 / ${data.total_pages} (編集モード)`;
      showAILog(`Page 1 テンプレート化完了: ${tData.spec.zones?.length || 0}ゾーン検出`, "ai-step-logs");
    } catch (tErr) {
      // Fallback to preview mode if templatize fails
      showPreviewPage(1);
      showAILog(`自動テンプレート化失敗（プレビューモード）: ${tErr.message}`, "ai-step-logs");
    }

    loadingOverlay.classList.add('hidden');

    // Phase 2: Extract design system in background
    showAILog("バックグラウンドでデザインシステムを抽出中...", "ai-step-logs");
    extractDesignSystem(data.scan_id);

  } catch (err) {
    $('ai-status').textContent = "エラー";
    alert("Preview Failed: " + err.message);
    loadingOverlay.classList.add('hidden');
  } finally {
    e.target.value = '';
  }
});

function renderFilmstrip(pages) {
  const strip = $("filmstrip");
  if (!strip) return;
  strip.classList.remove("hidden");
  strip.innerHTML = pages.map((p, i) =>
    `<div class="filmstrip-thumb${i === 0 ? ' active' : ''}" data-page="${p.page}">
      <img src="${API_BASE}${p.preview_url}" alt="Page ${p.page}">
      <span>${p.page}</span>
    </div>`
  ).join('');
  strip.querySelectorAll('.filmstrip-thumb').forEach(el => {
    el.addEventListener('click', async () => {
      strip.querySelectorAll('.filmstrip-thumb').forEach(t => t.classList.remove('active'));
      el.classList.add('active');
      const pg = parseInt(el.dataset.page);
      state.currentPageIndex = pg - 1;

      // Auto-templatize if not already done
      if (state.scanId && !state.designPages[pg - 1]) {
        loadingOverlay.classList.remove('hidden');
        $('ai-status').textContent = `Page ${pg} をAI解析中...`;
        try {
          const res = await fetch(`${API_BASE}/api/design/templatize/${state.scanId}/${pg}`, { method: 'POST' });
          if (!res.ok) throw new Error(`Templatize error: ${res.status}`);
          const data = await res.json();
          state.designPages[pg - 1] = data.svg;
          state.pageSpecs[pg - 1] = data.spec;
          state.previewMode = false;
          updatePageUI();
          syncLayersPanel();
          initVectorEditor();
          $("page-indicator").textContent = `Page ${pg} / ${state.scanTotalPages} (編集モード)`;
          showAILog(`Page ${pg} テンプレート化完了: ${data.spec.zones?.length || 0}ゾーン`, "ai-step-logs");
        } catch (err) {
          showPreviewPage(pg);
          showAILog(`Page ${pg} テンプレート化失敗: ${err.message}`, "ai-step-logs");
        } finally {
          loadingOverlay.classList.add('hidden');
        }
      } else if (state.designPages[pg - 1]) {
        state.previewMode = false;
        updatePageUI();
        syncLayersPanel();
        initVectorEditor();
        $("page-indicator").textContent = `Page ${pg} / ${state.scanTotalPages} (編集モード)`;
      } else {
        showPreviewPage(pg);
      }
    });
  });
}

function showPreviewPage(pageNum) {
  const svgCanvas = $('main-svg');
  svgCanvas.innerHTML = '';
  // Show preview image filling the SVG canvas
  const url = `${API_BASE}/api/design/preview/${state.scanId}/${pageNum}`;
  svgCanvas.innerHTML = `
    <image x="0" y="0" width="420" height="297" href="${url}" id="preview-image"/>
  `;
  const totalP = state.scanTotalPages || 1;
  $("page-indicator").textContent = `Page ${pageNum} / ${totalP} (プレビュー)`;

  // Show templatize button
  const btn = $("btn-templatize");
  if (btn) btn.classList.remove("hidden");
}

// Phase 2: Design System (background)
async function extractDesignSystem(scanId) {
  try {
    const res = await fetch(`${API_BASE}/api/design/extract-design-system/${scanId}`, { method: 'POST' });
    if (!res.ok) throw new Error(`Design system error: ${res.status}`);
    const data = await res.json();
    state.designSpec = data.design_system;
    renderDesignSpecPanel(data.design_system);
    showAILog(`デザインシステム抽出完了 (${data.model_used})`, "ai-step-logs");
  } catch (err) {
    console.error("Design system error:", err);
    showAILog(`デザインシステム抽出失敗: ${err.message}`, "ai-step-logs");
  }
}

// Phase 3: Templatize (on-demand per page)
$("btn-templatize")?.addEventListener("click", async () => {
  if (!state.scanId) return;
  const pageNum = state.currentPageIndex + 1;

  loadingOverlay.classList.remove('hidden');
  $('ai-status').textContent = `Page ${pageNum} をテンプレート化中...`;
  showAILog(`AI Visionでページ ${pageNum} を分析中...`, "ai-step-logs");

  try {
    const res = await fetch(`${API_BASE}/api/design/templatize/${state.scanId}/${pageNum}`, { method: 'POST' });
    if (!res.ok) throw new Error(`Templatize error: ${res.status}`);
    const data = await res.json();

    // Switch from preview mode to edit mode
    state.previewMode = false;
    state.designPages = state.designPages || [];
    state.designPages[pageNum - 1] = data.svg;
    updatePageUI();
    syncLayersPanel();
    initVectorEditor();

    $("page-indicator").textContent = `Page ${pageNum} / ${state.scanTotalPages} (編集モード)`;
    showAILog(`Page ${pageNum} テンプレート化完了: ${data.spec.zones?.length || 0}ゾーン検出`, "ai-step-logs");
  } catch (err) {
    alert("Templatize Failed: " + err.message);
    showAILog(`テンプレート化失敗: ${err.message}`, "ai-step-logs");
  } finally {
    loadingOverlay.classList.add('hidden');
  }
});

// Ghost Reference Toggle
$("btn-ghost-toggle")?.addEventListener("click", () => {
  state.ghostVisible = !state.ghostVisible;
  const ghostLayer = svgCanvas.querySelector('#ghost-layer');
  const slider = $("ghost-opacity-slider");
  if (ghostLayer) {
    ghostLayer.setAttribute('opacity', state.ghostVisible ? (slider ? slider.value / 100 : 0.3) : '0');
  }
  const btn = $("btn-ghost-toggle");
  if (btn) btn.textContent = state.ghostVisible ? '👻 参照ON' : '👻 参照OFF';
});

// Ghost Opacity Slider
$("ghost-opacity-slider")?.addEventListener("input", (e) => {
  const val = e.target.value;
  $("ghost-opacity-label").textContent = `${val}%`;
  const ghostLayer = svgCanvas.querySelector('#ghost-layer');
  if (ghostLayer) ghostLayer.setAttribute('opacity', val / 100);
  state.ghostVisible = val > 0;
});

// IDML Export
$("export-idml")?.addEventListener("click", async () => {
  if (!state.scanId) return alert("先にPDFをスキャンしてください");
  showAILog("IDML生成中...");
  try {
    const res = await fetch(`${API_BASE}/api/design/export-idml/${state.scanId}`);
    if (!res.ok) throw new Error(`Export error: ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${state.scanId}.idml`; a.click();
    URL.revokeObjectURL(url);
    showAILog("IDML エクスポート完了!");
  } catch (err) {
    alert("IDML Export Failed: " + err.message);
  }
});

// Design Spec Panel Renderer (supports both old color_palette and new brand_colors)
function renderDesignSpecPanel(spec) {
  const panel = $("design-spec-panel");
  if (!panel) return;
  panel.classList.remove("hidden");

  const colors = spec.brand_colors || spec.color_palette || [];
  const paletteEl = $("spec-palette");
  if (paletteEl && colors.length) {
    paletteEl.innerHTML = colors.map(c =>
      `<div class="spec-swatch" style="background:${c.hex}" title="${c.name || c.role}: ${c.usage || ''}" data-hex="${c.hex}">
        <span class="swatch-label">${c.hex}</span>
      </div>`
    ).join('');
    paletteEl.querySelectorAll('.spec-swatch').forEach(el => {
      el.addEventListener('click', () => {
        navigator.clipboard.writeText(el.dataset.hex);
        showAILog(`Copied: ${el.dataset.hex}`);
      });
    });
  }

  const typoEl = $("spec-typography");
  if (typoEl && spec.typography) {
    const unique = [];
    const seen = new Set();
    for (const t of spec.typography) {
      const key = `${t.role}-${t.style || ''}-${t.weight || ''}`;
      if (!seen.has(key)) { seen.add(key); unique.push(t); }
    }
    typoEl.innerHTML = unique.slice(0, 8).map(t =>
      `<div class="spec-typo-item">
        <span class="typo-role">${t.role}</span>
        <span class="typo-detail">${t.estimated_size_pt || '?'}pt / ${t.weight || '?'} / ${t.style || '?'} / ${t.direction || 'h'}</span>
      </div>`
    ).join('');
  }

  // Layout Patterns (new)
  const patternsEl = $("spec-page-types");
  if (patternsEl) {
    const patterns = spec.layout_patterns || [];
    const types = spec.page_types || [];
    if (patterns.length) {
      patternsEl.innerHTML = patterns.map(p =>
        `<span class="page-type-badge" title="${p.description || ''}">${p.name}</span>`
      ).join(' ');
    } else if (types.length) {
      patternsEl.innerHTML = types.map((t, i) =>
        `<span class="page-type-badge">${i + 1}: ${t}</span>`
      ).join(' ');
    }
  }
}

// ===================================================================
// Trace / Drawing Tools (rect, text, image on top of ghost reference)
// ===================================================================
state.currentTool = 'select';
state.isDrawing = false;
state.drawStart = null;
state.drawPreview = null;

document.querySelectorAll('.al-tool-btn[data-tool]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.al-tool-btn[data-tool]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.currentTool = btn.dataset.tool;
    svgCanvas.style.cursor = state.currentTool === 'select' ? 'default' : 'crosshair';
  });
});

// Keyboard shortcuts for tool switch
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
  const toolMap = { 'v': 'select', 'm': 'rect', 't': 'text', 'i': 'image' };
  if (toolMap[e.key]) {
    document.querySelector(`.al-tool-btn[data-tool="${toolMap[e.key]}"]`)?.click();
  }
});

svgCanvas.addEventListener('mousedown', (e) => {
  if (state.currentTool === 'select') return;
  e.preventDefault();

  const ctm = svgCanvas.getScreenCTM().inverse();
  const pt = svgCanvas.createSVGPoint();
  pt.x = e.clientX; pt.y = e.clientY;
  const svgPt = pt.matrixTransform(ctm);

  state.isDrawing = true;
  state.drawStart = { x: svgPt.x, y: svgPt.y };

  // Create a preview shape
  const preview = document.createElementNS(SVG_NS, 'rect');
  preview.setAttribute('x', svgPt.x);
  preview.setAttribute('y', svgPt.y);
  preview.setAttribute('width', 0);
  preview.setAttribute('height', 0);
  const toolColors = { rect: ['rgba(0,240,255,0.1)', '#00f0ff'], text: ['rgba(255,200,0,0.1)', '#FFD700'], image: ['rgba(100,200,100,0.1)', '#66CC66'] };
  const [fillC, strokeC] = toolColors[state.currentTool] || toolColors.rect;
  preview.setAttribute('fill', fillC);
  preview.setAttribute('stroke', strokeC);
  preview.setAttribute('stroke-width', '0.5');
  preview.setAttribute('stroke-dasharray', '2,2');
  preview.id = 'draw-preview';
  svgCanvas.appendChild(preview);
  state.drawPreview = preview;
});

svgCanvas.addEventListener('mousemove', (e) => {
  if (!state.isDrawing || !state.drawPreview) return;

  const ctm = svgCanvas.getScreenCTM().inverse();
  const pt = svgCanvas.createSVGPoint();
  pt.x = e.clientX; pt.y = e.clientY;
  const svgPt = pt.matrixTransform(ctm);

  const x = Math.min(state.drawStart.x, svgPt.x);
  const y = Math.min(state.drawStart.y, svgPt.y);
  const w = Math.abs(svgPt.x - state.drawStart.x);
  const h = Math.abs(svgPt.y - state.drawStart.y);

  state.drawPreview.setAttribute('x', x);
  state.drawPreview.setAttribute('y', y);
  state.drawPreview.setAttribute('width', w);
  state.drawPreview.setAttribute('height', h);
});

svgCanvas.addEventListener('mouseup', (e) => {
  if (!state.isDrawing) return;
  state.isDrawing = false;
  if (state.drawPreview) state.drawPreview.remove();
  state.drawPreview = null;

  const ctm = svgCanvas.getScreenCTM().inverse();
  const pt = svgCanvas.createSVGPoint();
  pt.x = e.clientX; pt.y = e.clientY;
  const svgPt = pt.matrixTransform(ctm);

  const x = Math.round(Math.min(state.drawStart.x, svgPt.x) * 10) / 10;
  const y = Math.round(Math.min(state.drawStart.y, svgPt.y) * 10) / 10;
  const w = Math.round(Math.abs(svgPt.x - state.drawStart.x) * 10) / 10;
  const h = Math.round(Math.abs(svgPt.y - state.drawStart.y) * 10) / 10;

  if (w < 2 && h < 2) return; // Too small, ignore

  const id = `el-${Date.now()}`;
  const g = document.createElementNS(SVG_NS, 'g');
  g.id = id;
  g.dataset.id = id;
  g.classList.add('element', 'selectable', 'zone-overlay');

  if (state.currentTool === 'rect') {
    g.dataset.type = 'rect';
    g.dataset.role = 'decoration';
    g.dataset.label = 'New Rect';
    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('x', x);
    rect.setAttribute('y', y);
    rect.setAttribute('width', w);
    rect.setAttribute('height', h);
    rect.setAttribute('fill', '#E0E0E0');
    rect.setAttribute('stroke', '#999');
    rect.setAttribute('stroke-width', '0.5');
    g.appendChild(rect);
  } else if (state.currentTool === 'text') {
    g.dataset.type = 'textblock';
    g.dataset.role = 'body';
    g.dataset.label = 'New Text';
    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('x', x);
    rect.setAttribute('y', y);
    rect.setAttribute('width', w);
    rect.setAttribute('height', h);
    rect.setAttribute('fill', 'none');
    rect.setAttribute('stroke', '#00f0ff');
    rect.setAttribute('stroke-width', '0.3');
    rect.setAttribute('stroke-dasharray', '2,1');
    g.appendChild(rect);
    const text = document.createElementNS(SVG_NS, 'text');
    text.setAttribute('x', x + 1);
    text.setAttribute('y', y + Math.min(h * 0.4, 6));
    text.setAttribute('font-family', "YuGothic, 'Hiragino Sans', sans-serif");
    text.setAttribute('font-size', Math.min(Math.max(h * 0.3, 3), 8));
    text.setAttribute('fill', '#000000');
    text.textContent = 'テキストを入力';
    g.appendChild(text);
  } else if (state.currentTool === 'image') {
    g.dataset.type = 'image';
    g.dataset.role = 'photo';
    g.dataset.label = 'New Image';
    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('x', x);
    rect.setAttribute('y', y);
    rect.setAttribute('width', w);
    rect.setAttribute('height', h);
    rect.setAttribute('fill', '#E0E0E0');
    rect.setAttribute('stroke', '#999');
    rect.setAttribute('stroke-width', '0.5');
    rect.setAttribute('stroke-dasharray', '2,2');
    g.appendChild(rect);
    const label = document.createElementNS(SVG_NS, 'text');
    label.setAttribute('x', x + w / 2);
    label.setAttribute('y', y + h / 2);
    label.setAttribute('font-family', "YuGothic, sans-serif");
    label.setAttribute('font-size', '4');
    label.setAttribute('fill', '#666');
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('dominant-baseline', 'middle');
    label.textContent = '[画像をダブルクリックで差替]';
    g.appendChild(label);
  }

  // Add to content layer or directly to SVG
  const contentLayer = svgCanvas.querySelector('#content-layer');
  if (contentLayer) {
    contentLayer.appendChild(g);
  } else {
    svgCanvas.appendChild(g);
  }

  // Register event handlers and select the new element
  initVectorEditor();
  selectElement(g);
  syncLayersPanel();

  // Switch back to select tool
  document.querySelector('.al-tool-btn[data-tool="select"]')?.click();
});

// Final initialization
initVectorEditor();
showScreen("screen-top");
