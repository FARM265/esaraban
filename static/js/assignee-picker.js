// ตัวเลือกผู้รับผิดชอบ: ค้นหาด้วยชื่อ และบอกจำนวนที่เลือก (ทำงานได้แม้ปิด JavaScript เพราะเป็น checkbox ธรรมดา)
document.querySelectorAll("[data-assignee-picker]").forEach((picker) => {
  const filter = picker.querySelector("[data-picker-filter]");
  const count = picker.querySelector("[data-picker-count]");
  const boxes = [...picker.querySelectorAll('input[type="checkbox"]')];

  const updateCount = () => {
    const chosen = boxes.filter((b) => b.checked).map((b) => b.closest("label").querySelector("span").textContent);
    count.textContent = chosen.length ? `เลือกแล้ว ${chosen.length} คน: ${chosen.join(", ")}` : "ยังไม่ได้เลือก";
  };
  boxes.forEach((b) => b.addEventListener("change", updateCount));

  filter?.addEventListener("input", () => {
    const q = filter.value.trim().toLowerCase();
    picker.querySelectorAll("[data-picker-group]").forEach((group) => {
      let shown = 0;
      group.querySelectorAll("[data-picker-item]").forEach((item) => {
        const match = !q || item.dataset.name.toLowerCase().includes(q);
        item.hidden = !match;
        if (match) shown += 1;
      });
      group.hidden = shown === 0;
    });
  });
  updateCount();
});
