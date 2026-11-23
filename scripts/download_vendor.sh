#!/bin/sh
# ดาวน์โหลด Bootstrap และฟอนต์ Sarabun (ใช้ตอน build Docker image)
# ใช้: sh download_vendor.sh <โฟลเดอร์ปลายทาง>
set -eu

DEST="${1:-static/vendor}"
BOOTSTRAP_VERSION="5.3.3"
PDFJS_VERSION="4.10.38"
mkdir -p "$DEST/bootstrap" "$DEST/sarabun" "$DEST/pdfjs"

fetch() {
    curl --fail --silent --show-error --location --retry 3 -o "$2" "$1"
    echo "OK   $2"
}

fetch "https://cdn.jsdelivr.net/npm/bootstrap@${BOOTSTRAP_VERSION}/dist/css/bootstrap.min.css" "$DEST/bootstrap/bootstrap.min.css"
fetch "https://cdn.jsdelivr.net/npm/bootstrap@${BOOTSTRAP_VERSION}/dist/js/bootstrap.bundle.min.js" "$DEST/bootstrap/bootstrap.bundle.min.js"

for weight in 400 500 600 700; do
    for subset in thai latin; do
        name="sarabun-${subset}-${weight}-normal.woff2"
        fetch "https://cdn.jsdelivr.net/npm/@fontsource/sarabun@5/files/${name}" "$DEST/sarabun/${name}"
    done
done

# PDF.js (ES module) บันทึกเป็น .js เพื่อให้ nginx ส่ง Content-Type เป็น JavaScript ซึ่ง module script บังคับ
fetch "https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.min.mjs" "$DEST/pdfjs/pdf.min.js"
fetch "https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.worker.min.mjs" "$DEST/pdfjs/pdf.worker.min.js"

# ฟอนต์ TTF สำหรับฝังข้อความเกษียนลงใน PDF (Google Fonts, ล็อก commit ไว้)
fetch "https://cdn.jsdelivr.net/gh/google/fonts@2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/sarabun/Sarabun-Regular.ttf" "$DEST/sarabun/Sarabun-Regular.ttf"
fetch "https://cdn.jsdelivr.net/gh/google/fonts@2796410152d4f9524b68ed46e69c1b60f8e0f7c3/ofl/sarabun/Sarabun-Bold.ttf" "$DEST/sarabun/Sarabun-Bold.ttf"
