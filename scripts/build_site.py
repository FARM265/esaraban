"""
สร้างเว็บแนะนำโครงการสำหรับ GitHub Pages (github.io)
- หน้าแรกจาก site/ (index.html, style.css, img/)
- คู่มือจาก docs/*.md แปลงเป็น HTML ที่ _site/docs/
ใช้ใน .github/workflows/pages.yml หรือรันเองได้: python scripts/build_site.py
"""
import html
import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
REPO = "https://github.com/FARM265/esaraban"

# ลำดับคู่มือในเมนู
ORDER = ["user-guide", "install", "office-lan", "google-cloud", "cloud-render-supabase", "backup-restore", "security-checklist"]

PAGE = """<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · E-Saraban</title>
<link rel="icon" type="image/png" href="../img/favicon.png">
<link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../style.css">
</head>
<body>
<header class="topbar"><div class="wrap">
<img src="../img/nacc-emblem.png" alt="ตราสำนักงาน ป.ป.ช." width="27" height="40">
<a class="name" href="../">E-Saraban</a>
<nav aria-label="เมนูหลัก"><a href="../">หน้าแรก</a><a href="./">คู่มือ</a><a href="{repo}">GitHub</a></nav>
</div></header>
<main class="wrap doc-layout">
<nav class="doc-nav" aria-label="คู่มือ"><p>คู่มือ</p><ul>{nav}</ul></nav>
<article class="doc">{body}</article>
</main>
<footer class="credit"><p>&copy; 2569 นายธนาธิป แสงขาร นักศึกษาสหกิจศึกษา มหาวิทยาลัยเชียงใหม่</p><p>ณ สำนักงาน ป.ป.ช. ประจำจังหวัดเชียงใหม่</p></footer>
</body>
</html>
"""


def title_of(text, fallback):
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


def convert(text):
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    # ลิงก์ระหว่างคู่มือ .md -> .html, ลิงก์ไปไฟล์ในโค้ด -> GitHub
    body = re.sub(r'href="([a-z0-9\-]+)\.md(#[^"]*)?"', lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', body)
    body = re.sub(r'href="\.\./([^"]+)"', lambda m: f'href="{REPO}/blob/main/{m.group(1)}"', body)
    return body


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "site", OUT)
    (OUT / ".nojekyll").write_text("")
    docs_out = OUT / "docs"
    docs_out.mkdir()

    sources = {p.stem: p for p in (ROOT / "docs").glob("*.md")}
    names = [n for n in ORDER if n in sources] + sorted(n for n in sources if n not in ORDER)
    pages = {n: sources[n].read_text(encoding="utf-8") for n in names}
    titles = {n: title_of(pages[n], n) for n in names}

    def nav(active):
        return "".join(
            f'<li><a href="{n}.html"{" class=\"active\" aria-current=\"page\"" if n == active else ""}>{html.escape(titles[n])}</a></li>'
            for n in names
        )

    for n in names:
        (docs_out / f"{n}.html").write_text(
            PAGE.format(title=html.escape(titles[n]), nav=nav(n), body=convert(pages[n]), repo=REPO), encoding="utf-8"
        )
    listing = "".join(f'<li><a href="{n}.html">{html.escape(titles[n])}</a></li>' for n in names)
    index_body = f"<h1>คู่มือ E-Saraban</h1><p>คู่มือภาษาไทยสำหรับผู้ใช้ ผู้ดูแลระบบ และการติดตั้ง</p><ul>{listing}</ul>"
    (docs_out / "index.html").write_text(
        PAGE.format(title="คู่มือ", nav=nav(None), body=index_body, repo=REPO), encoding="utf-8"
    )
    print(f"สร้างเว็บที่ {OUT} ({len(names)} คู่มือ)")


if __name__ == "__main__":
    build()
