# ---------- ขั้นที่ 1: ดาวน์โหลด Bootstrap และฟอนต์ Sarabun ----------
FROM python:3.12-slim AS vendor
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/download_vendor.sh /tmp/download_vendor.sh
RUN sed -i 's/\r$//' /tmp/download_vendor.sh && sh /tmp/download_vendor.sh /vendor

# ---------- ขั้นที่ 2: image ของแอป ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# ผู้ใช้ uid/gid 1000 ไม่ใช่ root; nginx อยู่ในกลุ่มเดียวกันเพื่ออ่านไฟล์ CSS/JS ได้
# libfribidi ทำให้ Pillow จัดตำแหน่งสระและวรรณยุกต์ไทยได้ถูกต้องเมื่อเขียนข้อความลง PDF
# libthai ใช้ตัดคำภาษาไทยเพื่อขึ้นบรรทัดใหม่ในหนังสือที่สร้างจากแม่แบบ
# tesseract (ภาษาไทย) และ poppler-utils (pdftotext) อ่านวันนัดหมายจากหนังสือ เพื่อลงปฏิทิน
RUN apt-get update \
    && apt-get install -y --no-install-recommends libfribidi0 libthai0 tesseract-ocr tesseract-ocr-tha poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
COPY --from=vendor --chown=app:app /vendor ./static/vendor
# กันกรณีแตกไฟล์บน Windows แล้วได้ CRLF ซึ่งทำให้สคริปต์ shell รันไม่ได้
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod 755 docker/entrypoint.sh \
    && mkdir -p private_storage staticfiles && chown app:app private_storage staticfiles

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
# PORT และ WEB_CONCURRENCY ปรับได้จาก environment (บน Render แผนเล็กใช้ 2 worker เพื่อประหยัด RAM)
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --timeout 120 --access-logfile -"]
