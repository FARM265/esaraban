// ตัวเลือกผู้รับผิดชอบ: ค้นหาด้วยชื่อ และบอกจำนวนที่เลือก (ทำงานได้แม้ปิด JavaScript เพราะเป็น checkbox ธรรมดา)
document.querySelectorAll("[data-assignee-picker]").forEach((picker) => {
  const filter = picker.querySelector("[data-picker-filter]");
  const count = picker.querySelector("[data-picker-count]");
  const boxes = [...picker.querySelectorAll('input[name="assignees"]')];

  const updateCount = () => {
    const chosen = boxes.filter((b) => b.checked).map((b) => b.closest("label").querySelector("span").textContent);
    count.textContent = chosen.length ? `เลือกแล้ว ${chosen.length} คน: ${chosen.join(", ")}` : "ยังไม่ได้เลือก";
  };
  // ติ๊กหัวกลุ่ม = เลือก/ยกเลิกทุกคนในกลุ่มงานนั้น (เฉพาะคนที่แสดงอยู่ตามคำค้น)
  const groups = [...picker.querySelectorAll("[data-picker-group]")].map((group) => ({
    all: group.querySelector("[data-picker-all]"),
    members: [...group.querySelectorAll('input[name="assignees"]')],
    group,
  }));
  const syncGroups = () => {
    groups.forEach(({ all, members, group }) => {
      const shown = members.filter((b) => !b.closest("[data-picker-item]").hidden);
      const checked = shown.filter((b) => b.checked).length;
      all.checked = shown.length > 0 && checked === shown.length;
      all.indeterminate = checked > 0 && checked < shown.length;
      group.querySelector(".assignee-all-hint").textContent = all.checked ? "ยกเลิกทั้งกลุ่ม" : "เลือกทั้งกลุ่ม";
    });
  };
  groups.forEach(({ all, members, group }) => {
    all.hidden = false;
    group.querySelector(".assignee-all-hint").hidden = false;
    all.addEventListener("change", () => {
      members.filter((b) => !b.closest("[data-picker-item]").hidden).forEach((b) => { b.checked = all.checked; });
      updateCount();
      syncGroups();
    });
  });
  boxes.forEach((b) => b.addEventListener("change", () => { updateCount(); syncGroups(); }));

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
    syncGroups();
  });
  updateCount();
  syncGroups();
});
