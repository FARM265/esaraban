// ฟอร์มสร้างหนังสือ: แสดงเฉพาะช่องที่ใช้กับแม่แบบที่เลือก (ช่องที่ซ่อน เซิร์ฟเวอร์ไม่บันทึก)
const form = document.querySelector('[data-role="letter-form"]');
if (form) {
  const radios = form.querySelectorAll('input[name="kind"]');
  const update = () => {
    const kind = [...radios].find((r) => r.checked)?.value;
    form.querySelectorAll("[data-kinds]").forEach((box) => {
      box.hidden = Boolean(kind) && !box.dataset.kinds.split(" ").includes(kind);
    });
    form.querySelectorAll(".kind-card").forEach((card) => {
      card.classList.toggle("active", card.querySelector("input")?.checked);
    });
  };
  radios.forEach((r) => r.addEventListener("change", update));
  update();
}
