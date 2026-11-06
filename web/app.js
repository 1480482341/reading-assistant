let articleId = null;
let current = null;
let popupToken = 0;
let full = null;
let annotations = [];
let bookmarks = [];
let colorMode = null;
let hlTarget = null;
let suppressHlClick = false;

const popup = document.getElementById("popup");
const hlPopup = document.getElementById("hl-popup");
const bodyEl = document.getElementById("article-body");

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function checkHealth() {
  try {
    const health = await fetch("/api/health").then(r => r.json());
    document.getElementById("banner").hidden = health.claude_available === true;
  } catch (err) {
    document.getElementById("banner").hidden = false;
  }
}

function hidePopup() {
  popupToken += 1;
  popup.hidden = true;
  const sel = window.getSelection();
  if (sel) sel.removeAllRanges();
}

function showMessage(title, body) {
  articleId = null;
  full = null;
  annotations = [];
  bookmarks = [];
  renderBookmarks();
  document.getElementById("article-title").textContent = title;
  document.getElementById("article-title-zh").hidden = true;
  document.getElementById("article-meta").textContent = "";
  bodyEl.textContent = body;
}

// Split article text exactly like the server's app/annotations.py:
// split_paragraphs — split on newline runs, trim each piece, drop empties.
function paragraphs() {
  return full.text.split(/\n+/).map(s => s.trim()).filter(Boolean);
}

// Rebuild the article body from paragraphs() and the current annotations,
// wrapping each highlighted range in a colored span with its annotation id.
function renderBody() {
  const paras = paragraphs();
  bodyEl.innerHTML = paras.map((para, i) => {
    const anns = annotations
      .filter(a => a.para_index === i)
      .sort((x, y) => x.start_offset - y.start_offset);
    const frags = [];
    let cursor = 0;
    for (const a of anns) {
      const start = Math.max(a.start_offset, cursor);
      const end = Math.min(a.end_offset, para.length);
      if (end <= start) continue;
      if (start > cursor) frags.push({ text: para.slice(cursor, start) });
      frags.push({ text: para.slice(start, end), ann: a });
      cursor = end;
    }
    if (cursor < para.length) frags.push({ text: para.slice(cursor) });
    const inner = frags.map(f => f.ann
      ? `<span class="hl hl-${f.ann.color}" data-annotation-id="${f.ann.id}">${escapeHtml(f.text)}</span>`
      : escapeHtml(f.text)).join("");
    return `<p data-para="${i}">${inner}</p>`;
  }).join("");
}

// --- Color mode: select text to highlight it in the active color. ---

// Turn color mode on for `color`, or off when the same color is chosen again.
function setColorMode(color) {
  if (colorMode === color) color = null;
  colorMode = color;
  for (const b of document.querySelectorAll(".actions .swatch")) {
    b.classList.toggle("active", colorMode === b.dataset.color);
  }
}

// Character offset of the (container, offset) boundary within p's text
// content, so offsets match the trimmed paragraph string the server checks.
function offsetInPara(p, container, offset) {
  if (container.nodeType === Node.TEXT_NODE) {
    let pos = 0;
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node === container) return pos + offset;
      pos += node.textContent.length;
    }
    return pos;
  }
  // Element boundary: offset is a child index. Locate the element's first
  // text node, then add the text length of the children before that index.
  let base = -1;
  let pos = 0;
  const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (container.contains(node)) { base = pos; break; }
    pos += node.textContent.length;
  }
  if (base < 0) return p.textContent.length;
  let before = 0;
  for (let i = 0; i < offset && i < container.childNodes.length; i++) {
    before += container.childNodes[i].textContent.length;
  }
  return base + before;
}

// Map a DOM selection to character offsets within a single paragraph.
// A selection that starts in one <p> and ends in another is clamped to the
// end of the start paragraph; collapsed or empty selections return null.
function selectionToRange(sel) {
  if (!sel || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  if (range.collapsed) return null;
  const startEl = range.startContainer.nodeType === Node.TEXT_NODE
    ? range.startContainer.parentElement : range.startContainer;
  const p = startEl ? startEl.closest("p[data-para]") : null;
  if (!p || !bodyEl.contains(p)) return null;
  const start = offsetInPara(p, range.startContainer, range.startOffset);
  const endEl = range.endContainer.nodeType === Node.TEXT_NODE
    ? range.endContainer.parentElement : range.endContainer;
  const end = endEl && p.contains(endEl)
    ? offsetInPara(p, range.endContainer, range.endOffset)
    : p.textContent.length;
  if (start === end) return null;
  return { paraIndex: Number(p.dataset.para), start, end };
}

// POST the range as a new annotation in the given color, then re-render.
// The server replaces overlapping rows in the same paragraph; mirror that
// on the local array so the UI matches the stored state.
async function applyAnnotation(range, color) {
  if (!articleId) return;
  const para = paragraphs()[range.paraIndex];
  if (!para) return;
  try {
    const resp = await fetch(`/api/articles/${articleId}/annotations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        para_index: range.paraIndex,
        start_offset: range.start,
        end_offset: range.end,
        quote: para.slice(range.start, range.end),
        color,
      }),
    });
    if (!resp.ok) return;
    const ann = await resp.json();
    annotations = annotations.filter(a =>
      !(a.para_index === ann.para_index &&
        a.start_offset < ann.end_offset &&
        a.end_offset > ann.start_offset));
    annotations.push(ann);
    renderBody();
  } catch (err) {
    console.error("Failed to save annotation:", err);
  }
}

// --- Highlight popup: recolor or remove an existing annotation. ---

function hideHlPopup() {
  hlPopup.hidden = true;
  hlTarget = null;
}

function openHlPopup(span) {
  hlTarget = span;
  hidePopup();
  for (const b of hlPopup.querySelectorAll(".swatch")) {
    b.classList.toggle("active", span.classList.contains(`hl-${b.dataset.color}`));
  }
  const rect = span.getBoundingClientRect();
  hlPopup.hidden = false;
  const left = Math.min(window.scrollX + rect.left,
    window.scrollX + window.innerWidth - 250);
  hlPopup.style.left = `${left}px`;
  hlPopup.style.top = `${window.scrollY + rect.bottom + 8}px`;
}

function showArticle(article) {
  full = article;
  articleId = full.id;
  document.getElementById("article-title").textContent = full.title;
  const titleZh = document.getElementById("article-title-zh");
  titleZh.textContent = full.title_zh || "";
  titleZh.hidden = !full.title_zh;
  document.getElementById("article-meta").textContent =
    `${full.topic || ""} · ${full.word_count || ""} words · ${full.status}`;
  annotations = full.annotations || [];
  bookmarks = full.bookmarks || [];
  renderBody();
  renderBookmarks();
  fetch(`/api/articles/${full.id}/marks`)
    .then(r => r.json())
    .then(renderRightPanel)
    .catch(err => console.error("Failed to load marks:", err));
}

async function loadArticle() {
  const requested = new URLSearchParams(location.search).get("id");
  if (requested && !/^\d+$/.test(requested)) {
    showMessage("文章不存在", "链接里的文章编号无效，回到文章库重新选择。");
    return;
  }
  if (requested) {
    const resp = await fetch(`/api/articles/${encodeURIComponent(requested)}`);
    if (!resp.ok) {
      showMessage("文章不存在", "这篇文章可能已被删除，回到文章库重新选择。");
      return;
    }
    showArticle(await resp.json());
    return;
  }
  const today = await fetch("/api/articles/today").then(r => r.json());
  if (!today.length) {
    showMessage("今天还没有文章",
      "还没有可读文章：等后台抓取完成，或用 POST /api/articles/ingest 粘贴链接或正文。");
    return;
  }
  const full = await fetch(`/api/articles/${today[0].id}`).then(r => r.json());
  showArticle(full);
}

function sentenceAround(text, needle) {
  const i = text.indexOf(needle);
  if (i < 0) return "";
  const start = text.lastIndexOf(".", i) + 1;
  let end = text.indexOf(".", i);
  end = end < 0 ? text.length : end + 1;
  return text.slice(start, end).trim();
}

function showPopup(rect, item, text) {
  current = { item, text };
  document.getElementById("popup-term").textContent = item.term || text;
  document.getElementById("popup-gloss").textContent = item.gloss_zh || "";
  document.getElementById("popup-why").textContent =
    [item.grammar_role, item.why].filter(Boolean).join(" · ");
  popup.hidden = false;
  const left = Math.min(window.scrollX + rect.left, window.scrollX + window.innerWidth - 300);
  popup.style.left = `${left}px`;
  popup.style.top = `${window.scrollY + rect.bottom + 8}px`;
}

async function onSelect() {
  const sel = window.getSelection();
  const text = String(sel).trim().slice(0, 500);
  if (!text || !articleId) return;
  const rect = sel.getRangeAt(0).getBoundingClientRect();
  const token = ++popupToken;

  const res = await fetch(
    `/api/lookup?article_id=${articleId}&text=${encodeURIComponent(text)}`
  ).then(r => r.json());
  if (token !== popupToken) return;

  if (res.hit) {
    showPopup(rect, res.item, text);
    return;
  }

  showPopup(rect, { term: text, gloss_zh: "分析中…（约 5–10 秒）" }, text);
  try {
    const resp = await fetch("/api/lookup/miss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ article_id: articleId, text }),
    });
    if (!resp.ok) throw new Error("model unavailable");
    const miss = await resp.json();
    if (token !== popupToken) return;
    showPopup(rect, miss.item, text);
  } catch (err) {
    if (token !== popupToken) return;
    showPopup(rect, { term: text, gloss_zh: "模型不可用，可先记下来" }, text);
  }
}

function appendMark(listEl, item) {
  const li = document.createElement("li");
  li.innerHTML = `<span class="lemma">${escapeHtml(item.term)}</span>
                  <span class="count">${escapeHtml(item.gloss_zh || "")}</span>`;
  listEl.appendChild(li);
}

// Fill both sidebar lists from GET /api/articles/{id}/marks.
function renderRightPanel(marks) {
  const markedList = document.getElementById("marked-list");
  const grammarList = document.getElementById("grammar-list");
  markedList.innerHTML = "";
  grammarList.innerHTML = "";
  for (const item of marks.occurrences || []) appendMark(markedList, item);
  for (const item of marks.grammar || []) appendMark(grammarList, item);
}

function addToSidebar(item) {
  const list = item.type === "grammar"
    ? document.getElementById("grammar-list")
    : document.getElementById("marked-list");
  appendMark(list, item);
}

// --- Bookmarks: add, jump to, and delete reading positions. ---

// Height of the sticky topbar; the reading anchor is measured relative to it.
function topbarHeight() {
  const bar = document.querySelector(".topbar");
  return bar ? bar.getBoundingClientRect().height : 0;
}

// Current reading anchor: the first paragraph whose top edge sits at or
// below the topbar, plus the fractional position of that edge within the
// paragraph. Pure DOM measurement — nothing is read from or written to the
// server here.
function currentBookmarkAnchor() {
  const top = topbarHeight();
  for (const p of bodyEl.querySelectorAll("p[data-para]")) {
    const rect = p.getBoundingClientRect();
    if (rect.top >= top) {
      const ratio = Math.min(1, Math.max(0, (top - rect.top) / rect.height));
      return {
        paraIndex: Number(p.dataset.para),
        offsetRatio: ratio,
        label: p.textContent.slice(0, 40),
      };
    }
  }
  return null;
}

// POST the current anchor as a new bookmark; only touch local state when
// the server accepted it.
async function addBookmark() {
  if (!articleId) return;
  const anchor = currentBookmarkAnchor();
  if (!anchor) return;
  try {
    const resp = await fetch(`/api/articles/${articleId}/bookmarks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        para_index: anchor.paraIndex,
        offset_ratio: anchor.offsetRatio,
        label: anchor.label,
      }),
    });
    if (!resp.ok) return;
    bookmarks.push(await resp.json());
    renderBookmarks();
  } catch (err) {
    console.error("Failed to add bookmark:", err);
  }
}

// Fill the bookmark list from the local bookmarks array. Labels go through
// textContent, never innerHTML, so they cannot inject markup.
function renderBookmarks() {
  const list = document.getElementById("bookmark-list");
  list.innerHTML = "";
  for (const bm of bookmarks) {
    const li = document.createElement("li");
    const jump = document.createElement("button");
    jump.type = "button";
    jump.className = "bm-jump";
    jump.textContent = bm.label || "书签";
    jump.addEventListener("click", () => jumpToBookmark(bm));
    const del = document.createElement("button");
    del.type = "button";
    del.className = "bm-del";
    del.textContent = "×";
    del.title = "删除书签";
    del.addEventListener("click", async () => {
      try {
        const resp = await fetch(`/api/bookmarks/${bm.id}`, {
          method: "DELETE",
        });
        if (!resp.ok) return;
        bookmarks = bookmarks.filter(x => String(x.id) !== String(bm.id));
        renderBookmarks();
      } catch (err) {
        console.error("Failed to delete bookmark:", err);
      }
    });
    li.appendChild(jump);
    li.appendChild(del);
    list.appendChild(li);
  }
}

// Scroll to a bookmark's paragraph, then adjust so the saved offset lands
// right below the topbar.
function jumpToBookmark(bm) {
  const p = bodyEl.querySelector(`p[data-para="${bm.para_index}"]`);
  if (!p) return;
  p.scrollIntoView({ block: "start" });
  window.scrollBy(0, -topbarHeight() + bm.offset_ratio * p.offsetHeight);
}

async function save() {
  if (!current || !articleId) return;
  await fetch("/api/occurrences", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      article_id: articleId,
      text: current.text,
      sentence: current.item.sentence || sentenceAround(bodyEl.textContent, current.text),
      item: current.item,
    }),
  });
  addToSidebar(current.item);
  hidePopup();
}

document.addEventListener("mouseup", e => {
  if (hlPopup.contains(e.target)) return;
  if (popup.contains(e.target)) return;
  if (!bodyEl.contains(e.target)) { hidePopup(); hideHlPopup(); return; }
  if (colorMode) {
    const range = selectionToRange(window.getSelection());
    if (!range) return;
    suppressHlClick = true;
    hideHlPopup();
    applyAnnotation(range, colorMode);
    return;
  }
  hideHlPopup();
  onSelect();
});

// Clicking a highlighted span opens the recolor popup; clicking anywhere
// else closes it. The click right after a drag-highlight is swallowed.
document.addEventListener("click", e => {
  const target = e.target instanceof Element ? e.target : null;
  const span = target ? target.closest(".hl") : null;
  if (span) {
    if (suppressHlClick) { suppressHlClick = false; return; }
    openHlPopup(span);
    return;
  }
  suppressHlClick = false;
  if (!target || !hlPopup.contains(target)) hideHlPopup();
});

document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  setColorMode(null);
  hideHlPopup();
});

for (const b of document.querySelectorAll(".actions .swatch")) {
  b.addEventListener("click", () => setColorMode(b.dataset.color));
}

for (const b of hlPopup.querySelectorAll(".swatch")) {
  b.addEventListener("click", async () => {
    if (!hlTarget) return;
    const id = hlTarget.dataset.annotationId;
    try {
      const resp = await fetch(`/api/annotations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ color: b.dataset.color }),
      });
      if (!resp.ok) return;
      const ann = annotations.find(a => String(a.id) === String(id));
      if (ann) ann.color = b.dataset.color;
      renderBody();
      hideHlPopup();
    } catch (err) {
      console.error("Failed to update annotation:", err);
    }
  });
}

document.getElementById("hl-remove").addEventListener("click", async () => {
  if (!hlTarget) return;
  const id = hlTarget.dataset.annotationId;
  try {
    const resp = await fetch(`/api/annotations/${id}`, { method: "DELETE" });
    if (!resp.ok) return;
    annotations = annotations.filter(a => String(a.id) !== String(id));
    renderBody();
    hideHlPopup();
  } catch (err) {
    console.error("Failed to remove annotation:", err);
  }
});

document.getElementById("popup-save").addEventListener("click", save);
document.getElementById("popup-close").addEventListener("click", hidePopup);
document.getElementById("add-bookmark").addEventListener("click", addBookmark);
document.getElementById("mark-read").addEventListener("click", async e => {
  e.preventDefault();
  if (!articleId) return;
  await fetch(`/api/articles/${articleId}/read`, { method: "POST" });
  window.location.href = "/";
});

loadArticle();
checkHealth();
