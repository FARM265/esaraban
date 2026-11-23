#!/bin/sh
# สำรองฐานข้อมูลและไฟล์เอกสาร (รันบน server ที่โฟลเดอร์โปรเจกต์)
#   sh scripts/backup.sh
# ตั้งให้รันทุกคืนด้วย cron แล้วคัดลอกโฟลเดอร์ backups ไปเก็บนอกเครื่องด้วย (ดู docs/backup-restore.md)
#
# สำคัญ: ไฟล์เอกสารที่สำรองถูกเข้ารหัสด้วยกุญแจจาก SECRET_KEY ถ้าไฟล์ .env.docker หาย จะกู้คืนเอกสารไม่ได้
# ต้องเก็บ .env.docker แยกไว้ในที่ปลอดภัย (ไม่ใส่ไว้ในโฟลเดอร์เดียวกับชุดสำรอง)
set -eu

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="backups/$STAMP"
KEEP_DAYS="${KEEP_DAYS:-30}"
COMPOSE="docker compose --env-file .env.docker"
mkdir -p "$OUT"

echo "[1/4] สำรองฐานข้อมูล"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/esaraban.dump && pg_restore --list /tmp/esaraban.dump >/dev/null'
$COMPOSE cp db:/tmp/esaraban.dump "$OUT/db.dump"
$COMPOSE exec -T db rm -f /tmp/esaraban.dump

echo "[2/4] สำรองไฟล์เอกสาร (เข้ารหัสอยู่แล้ว)"
$COMPOSE exec -T web sh -c 'tar -C /app -czf /tmp/private_storage.tar.gz private_storage && tar -tzf /tmp/private_storage.tar.gz >/dev/null'
$COMPOSE cp web:/tmp/private_storage.tar.gz "$OUT/private_storage.tar.gz"
$COMPOSE exec -T web rm -f /tmp/private_storage.tar.gz

echo "[3/4] บันทึก checksum"
( cd "$OUT" && sha256sum db.dump private_storage.tar.gz > SHA256SUMS && test -s db.dump && test -s private_storage.tar.gz )

echo "[4/4] ลบชุดสำรองที่เก่ากว่า $KEEP_DAYS วัน"
find backups -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +

echo "สำรองเสร็จ: $OUT"
echo "เตือน: ตรวจว่าเก็บสำเนา .env.docker ไว้แยกในที่ปลอดภัยแล้ว (ไม่มีไฟล์นี้จะเปิดเอกสารที่สำรองไว้ไม่ได้)"
