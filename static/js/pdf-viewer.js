// ตัวแสดง PDF ด้วย PDF.js พร้อมปักหมุดความเห็น สั่งการ/เกษียน และวางลายเซ็น (รวมเป็นไฟล์ฉบับใหม่ไฟล์เดียว)
// ข้อความของผู้ใช้ใส่ด้วย textContent เท่านั้น (ไม่ใช้ innerHTML) เพื่อกัน XSS
const app = document.getElementById("pdf-app");
const cfg = app.dataset;
const pdfjsLib = await import(cfg.pdfjsUrl);

const $ = (selector) => app.querySelector(selector);
const pagesBox = $('[data-role="pages"]');
const statusEl = $('[data-role="status"]');
const zoomLabel = $('[data-role="zoom-label"]');
const pageCountEl = $('[data-role="page-count"]');
const pinBtn = $('[data-action="toggle-pin"]');
const signBtn = $('[data-action="toggle-sign"]');
const noteForm = $('[data-role="note-form"]');
const noteText = noteForm.querySelector("textarea");
const noteWhere = $('[data-role="note-where"]');
const noteError = $('[data-role="note-error"]');
const noteList = $('[data-role="note-list"]');
const finalPanel = $('[data-role="final-panel"]');
const finalForm = $('[data-role="final-form"]');
const finalError = $('[data-role="final-error"]');
const finalButton = $('[data-role="final-button"]');
const codeBox = $('[data-role="code-box"]');
const signWhere = $('[data-role="sign-where"]');
const signControls = $('[data-role="sign-controls"]');
const signSize = $('[data-role="sign-size"]');
const textBtn = $('[data-action="toggle-text"]');
const inkToolbar = $('[data-role="ink-toolbar"]');
const textCount = $('[data-role="text-count"]');
const canAnnotate = cfg.canAnnotate === "1";
const INK_SIZE_RATIO = { S: 12 / 595, M: 16 / 595, L: 22 / 595 }; // ตรงกับ INK_SIZES ฝั่งเซิร์ฟเวอร์

pdfjsLib.GlobalWorkerOptions.workerSrc = cfg.workerUrl;

let pdf = null;
let scale = 1;
let mode = null; // null | "pin" | "sign" | "text"
let pending = null; // ความเห็นที่กำลังเพิ่ม {page, x, y}
let notes = [];
let signature = null; // {page, x, y, w} สัดส่วนของหน้า มุมซ้ายบนของภาพ
let signAspect = null; // ความสูง/ความกว้าง ของภาพลายเซ็น
let ink = { color: "blue", hex: "#1F3A93", size: "M" };
let editor = null; // ช่องพิมพ์ข้อความสั่งการ/เกษียนที่เปิดอยู่ {page, x, y, node, actions}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

async function api(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": cfg.csrf },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "เกิดข้อผิดพลาด กรุณาลองใหม่");
  return data;
}

function pageWrap(n) {
  return pagesBox.querySelector(`.pdf-page[data-page="${n}"]`);
}

// ---------------------------------------------------------------- render pages
async function renderPages() {
  pagesBox.replaceChildren();
  const available = pagesBox.clientWidth - 32;
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    const base = page.getViewport({ scale: 1 });
    const fit = Math.min(available / base.width, 2);
    const viewport = page.getViewport({ scale: fit * scale });
    const ratio = window.devicePixelRatio || 1;

    const wrap = el("div", "pdf-page");
    wrap.dataset.page = String(n);
    wrap.style.width = `${viewport.width}px`;
    wrap.style.height = `${viewport.height}px`;
    wrap.setAttribute("aria-label", `หน้า ${n}`);

    const canvas = el("canvas");
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    wrap.append(canvas, el("div", "pdf-page-no", `หน้า ${n}`));
    pagesBox.append(wrap);

    await page.render({
      canvasContext: canvas.getContext("2d"),
      viewport,
      transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null,
    }).promise;
    wrap.addEventListener("click", (event) => onPageClick(event, wrap, n));
  }
  editor = null;
  drawPins();
  drawTexts();
  drawSignature();
}

function relativePoint(event, wrap) {
  const rect = wrap.getBoundingClientRect();
  return {
    x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
    y: clamp((event.clientY - rect.top) / rect.height, 0, 1),
  };
}

function onPageClick(event, wrap, page) {
  if (event.target.closest(".pin, .sig-preview, .ink-text, .ink-editor, .ink-editor-actions")) return;
  if (mode === "text") {
    openEditor(page, relativePoint(event, wrap));
  } else if (mode === "pin") {
    const p = relativePoint(event, wrap);
    pending = { page, ...p };
    noteWhere.textContent = `ความเห็นใหม่ หน้า ${page}`;
    noteError.textContent = "";
    noteText.value = "";
    noteForm.hidden = false;
    noteText.focus();
    drawPins();
  } else if (mode === "sign") {
    const p = relativePoint(event, wrap);
    const w = Number(signSize.value) / 100;
    const h = signHeight(wrap, w);
    placeSignature(page, p.x - w / 2, p.y - h / 2, w);
  }
}

// ---------------------------------------------------------------- signature placement
function signHeight(wrap, w) {
  // ความสูงของภาพเป็นสัดส่วนความสูงหน้า (ภาพคงอัตราส่วนเดิม)
  return (w * wrap.clientWidth * signAspect) / wrap.clientHeight;
}

function placeSignature(page, x, y, w) {
  const wrap = pageWrap(page);
  if (!wrap) return;
  const h = signHeight(wrap, w);
  signature = { page, w, x: clamp(x, 0, 1 - w), y: clamp(y, 0, Math.max(0, 1 - h)) };
  updateFinal();
  drawSignature();
}

function placeDefaultSignature() {
  // หนังสือจากแม่แบบ: วางลายเซ็นตรงที่ว่างเหนือชื่อผู้ลงนาม (ผู้ใช้ลากย้ายได้ตามปกติ)
  const [page, x, y, w] = cfg.signDefault.split(",").map(Number);
  if (!pageWrap(page) || [x, y, w].some(Number.isNaN)) return;
  if (signSize) signSize.value = String(Math.round(w * 100));
  placeSignature(page, x, y, w);
  pageWrap(page).querySelector(".sig-preview")?.scrollIntoView({ block: "center" });
}

function removeSignature() {
  signature = null;
  drawSignature();
  updateFinal();
}

// ---------------------------------------------------------------- ปุ่มเดียว: สร้างไฟล์ฉบับใหม่ (สั่งการ/เกษียน และ/หรือ ลงนาม)
function updateFinal() {
  if (!finalForm) return;
  const f = finalForm.elements;
  for (const k of ["page", "x", "y", "w"]) f[k].value = "";
  if (signature) {
    f.page.value = signature.page;
    f.x.value = signature.x.toFixed(4);
    f.y.value = signature.y.toFixed(4);
    f.w.value = signature.w.toFixed(4);
  }
  if (signWhere && cfg.signatureUrl) {
    signWhere.textContent = signature
      ? `วางแล้ว หน้า ${signature.page} · ลากภาพเพื่อเลื่อนได้`
      : 'ยังไม่ได้วาง กด "วางลายเซ็น" แล้วคลิกตรงจุดที่จะลงนาม';
  }
  if (signControls) signControls.hidden = !signature;
  if (codeBox) codeBox.hidden = !signature;
  const count = texts().length;
  if (textCount) textCount.textContent = count ? `มี ${count} รายการบนไฟล์นี้` : "ยังไม่มีข้อความสั่งการ/เกษียน";
  const parts = [];
  if (count) parts.push("สั่งการ/เกษียน");
  if (signature) {
    const kind = document.querySelector('[data-role="sig-kind"]:checked')?.value;
    parts.push(kind === "digital" ? "ลงนามดิจิทัล" : "ลงนาม");
  }
  finalButton.disabled = parts.length === 0;
  finalButton.textContent = parts.length ? `สร้างไฟล์ฉบับใหม่ (${parts.join(" + ")})` : "สร้างไฟล์ฉบับใหม่";
  delete finalButton.dataset.confirm;
  finalError.textContent = "";
}

function drawSignature() {
  pagesBox.querySelectorAll(".sig-preview").forEach((n) => n.remove());
  if (!signature || !cfg.signatureUrl) return;
  const wrap = pageWrap(signature.page);
  if (!wrap) return;
  const box = el("div", "sig-preview");
  box.tabIndex = 0;
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", "ตำแหน่งลายเซ็น ลากเพื่อย้าย หรือกดลูกศรบนแป้นพิมพ์");
  box.style.left = `${signature.x * 100}%`;
  box.style.top = `${signature.y * 100}%`;
  box.style.width = `${signature.w * 100}%`;
  const img = el("img");
  img.src = cfg.signatureUrl;
  img.alt = "";
  img.draggable = false;
  box.append(img);
  wrap.append(box);

  box.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    box.setPointerCapture(event.pointerId);
    const rect = wrap.getBoundingClientRect();
    const start = { px: event.clientX, py: event.clientY, x: signature.x, y: signature.y };
    const move = (e) => {
      const nx = start.x + (e.clientX - start.px) / rect.width;
      const ny = start.y + (e.clientY - start.py) / rect.height;
      const h = signHeight(wrap, signature.w);
      signature.x = clamp(nx, 0, 1 - signature.w);
      signature.y = clamp(ny, 0, Math.max(0, 1 - h));
      box.style.left = `${signature.x * 100}%`;
      box.style.top = `${signature.y * 100}%`;
      updateFinal();
    };
    const up = () => {
      box.removeEventListener("pointermove", move);
      box.removeEventListener("pointerup", up);
    };
    box.addEventListener("pointermove", move);
    box.addEventListener("pointerup", up);
  });
  box.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 0.05 : 0.01;
    const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
    if (!delta) return;
    event.preventDefault();
    placeSignature(signature.page, signature.x + delta[0], signature.y + delta[1], signature.w);
    pageWrap(signature.page)?.querySelector(".sig-preview")?.focus();
  });
}

if (signSize) {
  signSize.addEventListener("input", () => {
    if (signature) placeSignature(signature.page, signature.x, signature.y, Number(signSize.value) / 100);
  });
}

$('[data-action="remove-sign"]')?.addEventListener("click", removeSignature);
document.querySelectorAll('[data-role="sig-kind"]').forEach((radio) => radio.addEventListener("change", updateFinal));

if (finalForm) {
  finalForm.addEventListener("submit", (event) => {
    if (signature && finalForm.elements.code) {
      // ลงนามแบบต้องใช้รหัสจากแอป: รหัสคือการยืนยัน
      const code = finalForm.elements.code.value.trim();
      if (!/^\d{6}$/.test(code)) {
        event.preventDefault();
        finalError.textContent = "กรุณากรอกรหัส 6 หลักจากแอปเพื่อยืนยันการลงนาม";
        finalForm.elements.code.focus();
      }
    } else if (finalButton.dataset.confirm !== "1") {
      // ไม่ใช้รหัส: กดซ้ำอีกครั้งเพื่อยืนยัน กันการกดพลาด
      event.preventDefault();
      finalButton.dataset.confirm = "1";
      finalButton.textContent = signature ? "กดอีกครั้งเพื่อยืนยันการลงนาม" : "กดอีกครั้งเพื่อยืนยันสร้างไฟล์";
    }
  });
  finalForm.elements.code?.addEventListener("input", () => { finalError.textContent = ""; });
}

async function loadSignatureImage() {
  if (!cfg.signatureUrl) return;
  try {
    const img = new Image();
    img.src = cfg.signatureUrl;
    await img.decode();
    signAspect = img.naturalHeight / img.naturalWidth;
  } catch {
    // โหลดภาพลายเซ็นไม่ได้ ให้ยังดูเอกสารได้ตามปกติ แต่ปิดการลงนามไว้
    cfg.signatureUrl = "";
    signBtn?.remove();
    codeBox?.remove();
    if (signWhere) signWhere.textContent = "โหลดภาพลายมือชื่อไม่สำเร็จ กรุณาอัปโหลดภาพใหม่ที่เมนู ลายมือชื่อของฉัน";
  }
}

// ---------------------------------------------------------------- ข้อความสั่งการ/เกษียน
const texts = () => notes.filter((n) => n.kind === "TEXT");

function fontPx(wrap, ratio) {
  return ratio * wrap.clientWidth;
}

function closeEditor() {
  if (!editor) return;
  editor.node.remove();
  editor.actions.remove();
  editor = null;
}

function openEditor(page, point) {
  closeEditor();
  const wrap = pageWrap(page);
  const size = fontPx(wrap, INK_SIZE_RATIO[ink.size]);
  const node = el("textarea", "ink-editor");
  node.wrap = "off";
  node.rows = 1;
  node.setAttribute("aria-label", "พิมพ์ข้อความสั่งการ/เกษียน");
  node.style.left = `${point.x * 100}%`;
  node.style.top = `${point.y * 100}%`;
  node.style.fontSize = `${size}px`;
  node.style.color = ink.hex;
  const actions = el("div", "ink-editor-actions");
  const save = el("button", "btn btn-navy", "บันทึก");
  const cancel = el("button", "btn btn-outline-secondary bg-white", "ยกเลิก");
  save.type = cancel.type = "button";
  actions.append(save, cancel);
  wrap.append(node, actions);
  editor = { page, x: point.x, y: point.y, node, actions, color: ink.color, size: ink.size };

  const fit = () => {
    node.style.height = "auto";
    node.style.width = "auto";
    node.style.width = `${Math.max(node.scrollWidth + 4, size * 4)}px`;
    node.style.height = `${node.scrollHeight}px`;
    actions.style.left = node.style.left;
    actions.style.top = `calc(${node.style.top} + ${node.scrollHeight + 8}px)`;
  };
  node.addEventListener("input", fit);
  node.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeEditor();
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) saveEditor();
  });
  save.addEventListener("click", saveEditor);
  cancel.addEventListener("click", closeEditor);
  fit();
  node.focus();
}

async function saveEditor() {
  if (!editor) return;
  const content = editor.node.value.replace(/\s+$/, "");
  if (!content.trim()) { closeEditor(); return; }
  try {
    const data = await api(cfg.annotationsUrl, {
      method: "POST",
      body: JSON.stringify({ kind: "TEXT", page: editor.page, x: editor.x, y: editor.y, content, color: editor.color, size: editor.size }),
    });
    notes.push(data.annotation);
    closeEditor();
    drawTexts();
  } catch (err) {
    editor.actions.querySelector(".btn-navy").textContent = err.message;
  }
}

function drawTexts() {
  pagesBox.querySelectorAll(".ink-text").forEach((n) => n.remove());
  for (const note of texts()) {
    const wrap = pageWrap(note.page);
    if (!wrap) continue;
    const node = el("div", note.can_delete ? "ink-text mine" : "ink-text");
    node.style.left = `${note.x * 100}%`;
    node.style.top = `${note.y * 100}%`;
    node.style.fontSize = `${fontPx(wrap, note.size_ratio)}px`;
    node.style.color = note.color;
    node.append(document.createTextNode(note.content));
    node.title = `${note.author} · ${note.created_at}`;
    if (note.can_delete) {
      node.tabIndex = 0;
      const del = el("button", "ink-del", "×");
      del.type = "button";
      del.setAttribute("aria-label", "ลบข้อความนี้");
      del.addEventListener("click", (event) => { event.stopPropagation(); removeNote(note, del); });
      node.append(del);
      enableTextDrag(node, wrap, note);
    }
    wrap.append(node);
  }
  updateFinal();
}

function enableTextDrag(node, wrap, note) {
  node.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".ink-del")) return;
    event.preventDefault();
    node.setPointerCapture(event.pointerId);
    const rect = wrap.getBoundingClientRect();
    const start = { px: event.clientX, py: event.clientY, x: note.x, y: note.y };
    let moved = false;
    const move = (e) => {
      moved = true;
      note.x = clamp(start.x + (e.clientX - start.px) / rect.width, 0, 0.98);
      note.y = clamp(start.y + (e.clientY - start.py) / rect.height, 0, 0.98);
      node.style.left = `${note.x * 100}%`;
      node.style.top = `${note.y * 100}%`;
    };
    const up = async () => {
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerup", up);
      if (!moved) return;
      try {
        await api(cfg.moveUrlTemplate.replace("/0/", `/${note.id}/`), { method: "POST", body: JSON.stringify({ x: note.x, y: note.y }) });
      } catch (err) {
        note.x = start.x; note.y = start.y;
        drawTexts();
      }
    };
    node.addEventListener("pointermove", move);
    node.addEventListener("pointerup", up);
  });
}

if (inkToolbar) {
  inkToolbar.querySelectorAll(".ink-swatch").forEach((btn) => btn.addEventListener("click", () => {
    ink.color = btn.dataset.color;
    ink.hex = btn.dataset.hex;
    inkToolbar.querySelectorAll(".ink-swatch").forEach((b) => { b.classList.toggle("active", b === btn); b.setAttribute("aria-checked", b === btn ? "true" : "false"); });
    if (editor) { editor.color = ink.color; editor.node.style.color = ink.hex; }
  }));
  inkToolbar.querySelectorAll(".ink-size").forEach((btn) => btn.addEventListener("click", () => {
    ink.size = btn.dataset.size;
    inkToolbar.querySelectorAll(".ink-size").forEach((b) => { b.classList.toggle("active", b === btn); b.setAttribute("aria-checked", b === btn ? "true" : "false"); });
    if (editor) {
      editor.size = ink.size;
      editor.node.style.fontSize = `${fontPx(pageWrap(editor.page), INK_SIZE_RATIO[ink.size])}px`;
      editor.node.dispatchEvent(new Event("input"));
    }
  }));
}

// ---------------------------------------------------------------- pins and list
function drawPins() {
  pagesBox.querySelectorAll(".pin").forEach((p) => p.remove());
  const pinNotes = notes.filter((n) => n.kind !== "TEXT");
  const items = pending ? [...pinNotes, { ...pending, id: "new" }] : pinNotes;
  items.forEach((note, index) => {
    const wrap = pageWrap(note.page);
    if (!wrap) return;
    const isNew = note.id === "new";
    const pin = el("button", isNew ? "pin pin-new" : "pin", isNew ? "+" : String(index + 1));
    pin.type = "button";
    pin.style.left = `${note.x * 100}%`;
    pin.style.top = `${note.y * 100}%`;
    pin.setAttribute("aria-label", isNew ? "ตำแหน่งความเห็นใหม่" : `ความเห็นที่ ${index + 1}`);
    if (!isNew) {
      pin.addEventListener("click", () => {
        const item = noteList.querySelector(`[data-id="${note.id}"]`);
        if (item) { item.scrollIntoView({ block: "nearest" }); item.focus(); }
      });
    }
    wrap.append(pin);
  });
}

function drawList() {
  noteList.replaceChildren();
  const pinNotes = notes.filter((n) => n.kind !== "TEXT");
  pinNotes.forEach((note, index) => {
    const li = el("li", "note-item");
    li.dataset.id = String(note.id);
    li.tabIndex = -1;
    const head = el("div", "note-head");
    head.append(el("span", "note-num", String(index + 1)), el("strong", "", note.author));
    li.append(head, el("div", "small text-secondary", `หน้า ${note.page} · ${note.created_at}`), el("div", "note-body", note.content));
    const goto = el("button", "btn btn-link btn-sm p-0 me-3", "ไปที่ตำแหน่ง");
    goto.type = "button";
    goto.addEventListener("click", () => pageWrap(note.page)?.scrollIntoView({ behavior: "smooth", block: "start" }));
    li.append(goto);
    if (note.can_delete) {
      const del = el("button", "btn btn-link btn-sm p-0 text-danger", "ลบ");
      del.type = "button";
      del.addEventListener("click", () => removeNote(note, del));
      li.append(del);
    }
    noteList.append(li);
  });
  if (!pinNotes.length) noteList.append(el("li", "small text-secondary", "ยังไม่มีความเห็น"));
}

async function loadNotes() {
  notes = (await api(cfg.annotationsUrl)).annotations;
  drawList();
  drawPins();
  drawTexts();
}

async function removeNote(note, button) {
  if (button.dataset.confirm !== "1") {
    button.dataset.confirm = "1";
    button.textContent = "ยืนยันลบ";
    return;
  }
  try {
    await api(cfg.deleteUrlTemplate.replace("/0/", `/${note.id}/`), { method: "POST", body: "{}" });
    notes = notes.filter((n) => n.id !== note.id);
    drawList();
    drawPins();
    drawTexts();
  } catch (err) {
    button.textContent = err.message;
  }
}

noteForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  noteError.textContent = "";
  const content = noteText.value.trim();
  if (!content) { noteError.textContent = "กรุณาพิมพ์ความเห็น"; noteText.focus(); return; }
  try {
    const data = await api(cfg.annotationsUrl, { method: "POST", body: JSON.stringify({ ...pending, content, kind: "NOTE" }) });
    notes.push(data.annotation);
    pending = null;
    noteForm.hidden = true;
    drawList();
    drawPins();
  } catch (err) {
    noteError.textContent = err.message;
  }
});
noteText.addEventListener("input", () => { noteError.textContent = ""; });
$('[data-action="cancel-note"]').addEventListener("click", () => {
  pending = null;
  noteForm.hidden = true;
  drawPins();
});

// ---------------------------------------------------------------- toolbar
function setMode(next) {
  mode = mode === next ? null : next;
  if (mode !== "text") closeEditor();
  for (const [btn, name] of [[pinBtn, "pin"], [signBtn, "sign"], [textBtn, "text"]]) {
    if (!btn) continue;
    btn.setAttribute("aria-pressed", mode === name ? "true" : "false");
    btn.classList.toggle("active", mode === name);
  }
  pagesBox.classList.toggle("pin-mode", mode === "pin" || mode === "sign");
  pagesBox.classList.toggle("text-mode", mode === "text");
  if (inkToolbar) inkToolbar.hidden = mode !== "text";
  if (mode === "sign" && !signature && cfg.signDefault) placeDefaultSignature();
  if (mode === "sign" && finalPanel) finalPanel.scrollIntoView({ block: "nearest" });
}
if (pinBtn && canAnnotate) pinBtn.addEventListener("click", () => setMode("pin"));
if (signBtn) signBtn.addEventListener("click", () => setMode("sign"));
if (textBtn) textBtn.addEventListener("click", () => setMode("text"));

async function zoom(delta) {
  scale = clamp(scale + delta, 0.5, 2.5);
  zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  await renderPages();
}
$('[data-action="zoom-in"]').addEventListener("click", () => zoom(0.25));
$('[data-action="zoom-out"]').addEventListener("click", () => zoom(-0.25));

// ---------------------------------------------------------------- start
try {
  await loadSignatureImage();
  pdf = await pdfjsLib.getDocument({ url: cfg.fileUrl, isEvalSupported: false, enableXfa: false, withCredentials: true }).promise;
  pageCountEl.textContent = `${pdf.numPages} หน้า`;
  statusEl?.remove();
  await renderPages();
  await loadNotes();
  if (cfg.startSign === "1" && cfg.signatureUrl) setMode("sign");
} catch (err) {
  statusEl.textContent = `เปิดเอกสารไม่สำเร็จ: ${err.message}`;
  statusEl.classList.add("text-danger");
}
