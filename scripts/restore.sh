#!/bin/sh
# กู้คืนจากชุดสำรอง (เขียนทับข้อมูลปัจจุบันทั้งหมด)
#   sh scripts/restore.sh backups/20261120-230000
#
# ก่อนกู้คืน: .env.docker ต้องเป็นไฟล์เดิม (SECRET_KEY เดิม) มิฉะนั้นจะเปิดไฟล์เอกสารที่กู้คืนไม่ได้
# ขั้นตอน: ตรวจ checksum -> หยุดระบบ -> กู้ฐานข้อมูล -> กู้ไฟล์เอกสาร -> เปิดระบบ
set -eu

DIR="${1:-}"
COMPOSE="docker compose --env-file .env.docker"
if [ -z "$DIR" ] || [ ! -f "$DIR/db.dump" ] || [ ! -f "$DIR/private_storage.tar.gz" ]; then
    echo "วิธีใช้: sh scripts/restore.sh backups/<วันที่-เวลา>" >&2
    exit 2
fi

echo "[1/5] ตรวจ checksum"
( cd "$DIR" && sha256sum -c SHA256SUMS )

echo "ข้อมูลปัจจุบันทั้งหมดจะถูกแทนที่ด้วยชุดสำรอง $DIR"
printf "พิมพ์ RESTORE เพื่อยืนยัน: "
read -r answer
[ "$answer" = "RESTORE" ] || { echo "ยกเลิก"; exit 1; }

echo "[2/5] หยุดระบบ (ฐานข้อมูลยังทำงาน)"
$COMPOSE stop nginx web
$COMPOSE up -d db

echo "[3/5] กู้คืนฐานข้อมูล"
$COMPOSE cp "$DIR/db.dump" db:/tmp/restore.dump
$COMPOSE exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges --single-transaction --exit-on-error /tmp/restore.dump; status=$?; rm -f /tmp/restore.dump; exit $status'

echo "[4/5] กู้คืนไฟล์เอกสาร"
$COMPOSE run --rm --no-deps -v "$(cd "$DIR" && pwd):/restore:ro" --entrypoint sh web \
    -c 'find /app/private_storage -mindepth 1 -delete && tar -C /app -xzf /restore/private_storage.tar.gz'

echo "[5/5] เปิดระบบ (entrypoint จะ migrate และตั้งสิทธิ์ผู้ใช้ฐานข้อมูลให้)"
$COMPOSE up -d
echo "กู้คืนเสร็จ ให้ผู้ดูแลระบบเข้าเมนู Audit Log กด \"ตรวจความครบถ้วน\" และลองเปิดเอกสารสักฉบับ"
