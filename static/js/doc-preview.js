// ตัวอย่างไฟล์ในหน้าเอกสาร: แสดงไฟล์ล่าสุดทันที และสลับไฟล์ได้โดยไม่ออกจากหน้า (อ่านอย่างเดียว)
const box = document.getElementById("doc-preview");
const cfg = box.dataset;
const pagesBox = box.querySelector('[data-role="pages"]');
const nameEl = box.querySelector('[data-role="name"]');
const pagesLabel = box.querySelector('[data-role="pages-label"]');
const fullLink = box.querySelector('[data-role="full"]');
const calendarLink = box.querySelector('[data-role="calendar"]');

let pdfjsLib = null;
let pdf = null;
let task = null;
let scale = 1;
let token = 0; // รอบการวาด
let loadId = 0; // รอบการโหลดไฟล์

function status(text) {
  const p = document.createElement("p");
  p.className = "text-secondary p-4 mb-0";
  p.textContent = text;
  pagesBox.replaceChildren(p);
}

async function render() {
  const mine = ++token;
  const available = Math.max(pagesBox.clientWidth - 24, 200);
  pagesBox.replaceChildren();
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    if (mine !== token) return; // มีการสลับไฟล์หรือซูมระหว่างวาด
    const base = page.getViewport({ scale: 1 });
    const viewport = page.getViewport({ scale: Math.min(available / base.width, 2) * scale });
    const ratio = window.devicePixelRatio || 1;
    const canvas = document.createElement("canvas");
    canvas.className = "doc-preview-page";
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `หน้า ${n}`);
    pagesBox.append(canvas);
    await page.render({
      canvasContext: canvas.getContext("2d"),
      viewport,
      transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null,
    }).promise;
  }
}

async function load(url) {
  const mine = ++loadId;
  token++;
  status("กำลังโหลดไฟล์…");
  pagesLabel.textContent = "";
  try {
    if (!pdfjsLib) {
      pdfjsLib = await import(cfg.pdfjsUrl);
      pdfjsLib.GlobalWorkerOptions.workerSrc = cfg.workerUrl;
    }
    if (task) task.destroy(); // ปล่อยไฟล์เดิมออกจากหน่วยความจำ
    pdf = null;
    task = pdfjsLib.getDocument({ url, isEvalSupported: false, enableXfa: false, withCredentials: true });
    pdf = await task.promise;
    pagesLabel.textContent = `${pdf.numPages} หน้า`;
    scale = 1;
    pagesBox.scrollTop = 0;
    await render();
  } catch (err) {
    if (mine !== loadId) return; // ผู้ใช้สลับไปไฟล์อื่นแล้ว
    status("แสดงตัวอย่างไม่ได้ กด \"เปิดเต็มจอ\" หรือดาวน์โหลดไฟล์แทน");
  }
}

box.querySelector('[data-action="zoom-in"]').addEventListener("click", () => {
  if (!pdf) return;
  scale = Math.min(scale + 0.25, 2.5);
  render();
});
box.querySelector('[data-action="zoom-out"]').addEventListener("click", () => {
  if (!pdf) return;
  scale = Math.max(scale - 0.25, 0.5);
  render();
});

document.querySelectorAll('[data-action="show-file"]').forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll('[data-action="show-file"]').forEach((b) => {
      const on = b === btn;
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.textContent = on ? "กำลังแสดง" : "แสดง";
      b.closest("[data-file-row]").classList.toggle("is-shown", on);
    });
    nameEl.textContent = btn.dataset.name;
    fullLink.href = btn.dataset.viewerUrl;
    if (calendarLink) calendarLink.href = btn.dataset.calendarUrl;
    box.scrollIntoView({ behavior: "smooth", block: "start" });
    load(btn.dataset.fileUrl);
  });
});

let resizeTimer = null;
new ResizeObserver(() => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (pdf) render(); }, 200);
}).observe(pagesBox);

load(cfg.fileUrl);
