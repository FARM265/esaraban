// แสดงช่อง "ชื่อหมวดใหม่" เฉพาะเมื่อเลือก "+ สร้างหมวดใหม่" (ถ้าปิด JavaScript ช่องนี้แสดงตลอด)
document.querySelectorAll("[data-new-folder]").forEach((box) => {
  const select = box.closest("form").querySelector('select[name="folder"]');
  const input = box.querySelector("input");
  const sync = () => {
    const isNew = select.value === "__new__";
    box.hidden = !isNew;
    input.required = isNew;
    if (isNew && document.activeElement === select) input.focus();
  };
  select.addEventListener("change", sync);
  sync();
});
