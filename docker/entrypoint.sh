#!/bin/sh
# เตรียมระบบก่อนเริ่ม gunicorn: รอฐานข้อมูล, migrate, collectstatic
set -eu

echo "[entrypoint] waiting for database..."
python - <<'EOF'
import os, sys, time
import psycopg

if os.environ.get("DATABASE_URL"):
    # ฐานข้อมูลบนคลาวด์ (เช่น Supabase) ให้มาเป็น connection string
    connect = lambda: psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
else:
    params = dict(
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        connect_timeout=3,
    )
    connect = lambda: psycopg.connect(**params)
for attempt in range(30):
    try:
        connect().close()
        print("[entrypoint] database is ready")
        sys.exit(0)
    except psycopg.OperationalError:
        time.sleep(2)
print("[entrypoint] database not reachable after 60s", file=sys.stderr)
sys.exit(1)
EOF

# ขั้นตอนที่แก้โครงสร้างฐานข้อมูลใช้ผู้ใช้เจ้าของฐานข้อมูล (POSTGRES_USER)
DJANGO_DB_OWNER=1 python manage.py migrate --noinput
# ถ้าตั้ง POSTGRES_APP_USER: สร้าง/ปรับสิทธิ์ผู้ใช้แบบจำกัดสิทธิ์ ที่ระบบใช้ขณะทำงาน
DJANGO_DB_OWNER=1 python manage.py setup_app_role
# บนคลาวด์ที่ไม่มีหน้าต่างคำสั่ง (เช่น Render แผนฟรี): สร้างผู้ดูแลระบบคนแรกจาก DJANGO_SUPERUSER_* ถ้ายังไม่มี
# สร้างเสร็จแล้วควรลบ DJANGO_SUPERUSER_PASSWORD ออกจากการตั้งค่า
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    if DJANGO_DB_OWNER=1 python manage.py createsuperuser --noinput >/dev/null 2>&1; then
        echo "[entrypoint] created first admin: ${DJANGO_SUPERUSER_USERNAME}"
    else
        echo "[entrypoint] admin ${DJANGO_SUPERUSER_USERNAME} already exists (skip)"
    fi
fi
python manage.py collectstatic --noinput --verbosity 0
python manage.py check --deploy --fail-level ERROR

exec "$@"
