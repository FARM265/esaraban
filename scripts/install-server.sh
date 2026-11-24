#!/bin/bash
# ติดตั้งหรือปรับปรุงระบบ E-Saraban บน server Linux (Ubuntu 22.04/24.04 เช่น VM ของ Google Cloud) ด้วยคำสั่งเดียว
#   sudo bash esaraban/scripts/install-server.sh
# รันซ้ำได้: ครั้งต่อไปใช้ปรับปรุงเป็นโค้ดรุ่นใหม่ โดยไม่แตะข้อมูล .env.docker ชุดสำรอง และใบรับรอง
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "กรุณารันด้วย sudo: sudo bash $0"
    exit 1
fi

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/esaraban
OWNER="${SUDO_USER:-root}"
COMPOSE="docker compose --env-file .env.docker"

echo "== ติดตั้ง E-Saraban ที่ $APP =="

# ---------------------------------------------------------------- 1) วางโค้ด
mkdir -p "$APP"
if [ "$SRC" != "$APP" ]; then
    # คัดลอกโค้ดใหม่ทับ แต่ไม่แตะค่าลับ ชุดสำรอง และใบรับรองที่มีอยู่บน server
    (cd "$SRC" && tar --exclude=./.env.docker --exclude='./.env.docker.bak*' --exclude=./.env.cloud \
        --exclude=./backups --exclude=./docker/certs -cf - .) | (cd "$APP" && tar -xf -)
fi
cd "$APP"
find "$APP/scripts" "$APP/docker" -name '*.sh' -exec sed -i 's/\r$//' {} +
echo "[1/7] วางโค้ดที่ $APP แล้ว"

# ---------------------------------------------------------------- 2) Docker และ swap
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q docker.io docker-compose-v2
fi
systemctl enable --now docker >/dev/null
if ! swapon --show | grep -q .; then
    # กัน RAM ไม่พอตอน build และตอนอ่านภาพสแกน
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo "[2/7] Docker พร้อม"

# ---------------------------------------------------------------- 3) IP ภายนอก
IP=$(curl -s -m 3 -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" || true)
if ! echo "$IP" | grep -Eq '^[0-9]+(\.[0-9]+){3}$'; then
    IP=$(curl -s -m 5 https://api.ipify.org || true)
fi
if ! echo "$IP" | grep -Eq '^[0-9]+(\.[0-9]+){3}$'; then
    read -rp "ใส่ IP ภายนอกของเครื่องนี้: " IP
fi
echo "[3/7] IP ภายนอก: $IP"

# ---------------------------------------------------------------- 4) ค่าตั้งระบบและรหัสลับ
if [ ! -f .env.docker ]; then
    token() { python3 -c "import secrets; print(secrets.token_urlsafe(50))"; }
    hexpw() { python3 -c "import secrets; print(secrets.token_hex(24))"; }
    read -rp "รหัสหนังสือของหน่วยงาน เช่น ปช 0099 (กด Enter เพื่อใส่ทีหลัง): " ORG || true
    cat > .env.docker <<EOT
# สร้างโดย scripts/install-server.sh เมื่อ $(date '+%Y-%m-%d %H:%M')
# สำคัญ: สำรองไฟล์นี้เก็บแยกไว้ ถ้าหาย ไฟล์เอกสารที่สำรองไว้จะเปิดไม่ได้ และห้ามเปลี่ยน SECRET_KEY
SERVER_NAME=$IP
SECRET_KEY=$(token)
ALLOWED_HOSTS=$IP,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://$IP
POSTGRES_DB=esaraban
POSTGRES_USER=esaraban_app
POSTGRES_PASSWORD=$(hexpw)
POSTGRES_APP_USER=esaraban_rt
POSTGRES_APP_PASSWORD=$(hexpw)
ORG_CODE=${ORG:-ปช XXXX}
PRIVATE_STORAGE_ROOT=private_storage
# ใบรับรองทดลอง (self-signed) จึงปิด HSTS ไว้ เปลี่ยนเป็น 31536000 เมื่อมีโดเมนและใบรับรองจริง
SECURE_HSTS_SECONDS=0
# ยืนยันตัวตน 2 ขั้นด้วยแอป Authenticator ปิดไว้ (เข้าด้วยรหัสผ่านอย่างเดียว)
# ถ้าต้องการเปิด ตั้ง ESARABAN_LOGIN_REQUIRE_MFA=True ก่อน แล้วจึงตั้ง ESARABAN_SIGN_REQUIRE_OTP=True ได้
ESARABAN_LOGIN_REQUIRE_MFA=False
EOT
    chmod 600 .env.docker
    FIRST_INSTALL=1
    echo "[4/7] สร้าง .env.docker พร้อมรหัสลับใหม่แล้ว"
else
    sed -i "s|^SERVER_NAME=.*|SERVER_NAME=$IP|; s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=$IP,localhost,127.0.0.1|; s|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=https://$IP|" .env.docker
    FIRST_INSTALL=0
    echo "[4/7] ใช้ .env.docker เดิม (ปรับ IP ให้ตรงแล้ว)"
fi

# ---------------------------------------------------------------- 5) Firewall
if command -v ufw >/dev/null 2>&1; then
    ufw allow OpenSSH >/dev/null
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
    ufw --force enable >/dev/null
fi
echo "[5/7] Firewall เปิดเฉพาะ SSH, 80, 443"

# ---------------------------------------------------------------- 6) build และเริ่มระบบ
echo "[6/7] กำลัง build และเริ่มระบบ (ครั้งแรกประมาณ 10-15 นาที)..."
$COMPOSE up -d --build
for i in $(seq 1 60); do
    state=$(docker inspect -f '{{.State.Health.Status}}' "$($COMPOSE ps -q web)" 2>/dev/null || echo starting)
    [ "$state" = "healthy" ] && break
    sleep 10
done
if [ "$state" != "healthy" ]; then
    echo "ระบบยังไม่พร้อม ดูสาเหตุ: cd $APP && $COMPOSE logs web --tail 80"
    exit 1
fi

# ---------------------------------------------------------------- 7) สำรองข้อมูลทุกคืน
mkdir -p backups
cat > /etc/cron.d/esaraban-backup <<EOT
# สำรองฐานข้อมูลและไฟล์เอกสาร E-Saraban ทุกคืน 02:30 (เวลาเครื่อง) เก็บ 30 วัน
30 2 * * * root cd $APP && sh scripts/backup.sh >> backups/backup.log 2>&1
EOT
echo "[7/7] ตั้งสำรองข้อมูลทุกคืนแล้ว"

# ผู้ดูแลระบบคนแรก
has_admin=$($COMPOSE exec -T web python manage.py shell -c \
    "from django.contrib.auth import get_user_model as g; print(g().objects.filter(is_superuser=True).exists())" 2>/dev/null | tail -1)
if [ "$has_admin" != "True" ]; then
    echo ""
    echo "== สร้างผู้ดูแลระบบคนแรก (ชื่อผู้ใช้ อีเมล และรหัสผ่าน) =="
    $COMPOSE exec web python manage.py createsuperuser
fi

# สำเนาค่าลับให้ดาวน์โหลดไปเก็บ (เฉพาะครั้งแรก)
if [ "$FIRST_INSTALL" = "1" ] && [ "$OWNER" != "root" ]; then
    HOME_DIR=$(getent passwd "$OWNER" | cut -d: -f6)
    cp .env.docker "$HOME_DIR/esaraban-secrets-KEEP-SAFE.txt"
    chown "$OWNER" "$HOME_DIR/esaraban-secrets-KEEP-SAFE.txt"
    chmod 600 "$HOME_DIR/esaraban-secrets-KEEP-SAFE.txt"
fi

echo ""
echo "======================================================================"
echo " เสร็จแล้ว เปิดระบบที่:  https://$IP"
echo " (ครั้งแรกเบราว์เซอร์จะเตือนเรื่องใบรับรอง กด 'ขั้นสูง' แล้ว 'ดำเนินการต่อ')"
if [ "$FIRST_INSTALL" = "1" ] && [ "$OWNER" != "root" ]; then
    echo ""
    echo " สำคัญ: ดาวน์โหลดไฟล์ค่าลับไปเก็บในที่ปลอดภัย แล้วลบออกจาก server"
    echo "   1) ปุ่ม Download file ด้านบนหน้าต่างนี้ ใส่:  $HOME_DIR/esaraban-secrets-KEEP-SAFE.txt"
    echo "   2) ดาวน์โหลดเสร็จแล้วพิมพ์:  rm ~/esaraban-secrets-KEEP-SAFE.txt"
fi
echo "======================================================================"
