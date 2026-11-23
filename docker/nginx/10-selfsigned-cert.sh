#!/bin/sh
# ถ้ายังไม่มีใบรับรอง HTTPS ในโฟลเดอร์ certs ให้สร้างใบรับรองทดสอบ (self-signed)
# ใช้งานจริง: วางไฟล์ server.crt และ server.key ของหน่วยงานแทน แล้ว restart nginx
set -eu

CERT_DIR=/etc/nginx/certs
NAME="${SERVER_NAME:-localhost}"

if [ ! -s "$CERT_DIR/server.crt" ] || [ ! -s "$CERT_DIR/server.key" ]; then
    mkdir -p "$CERT_DIR"
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
        -subj "/CN=${NAME}" \
        -addext "subjectAltName=DNS:${NAME},DNS:localhost,IP:127.0.0.1" \
        -keyout "$CERT_DIR/server.key" -out "$CERT_DIR/server.crt" 2>/dev/null
    chmod 600 "$CERT_DIR/server.key" || true  # บาง filesystem ของ Windows เปลี่ยนสิทธิ์ไม่ได้
    echo "[nginx] generated SELF-SIGNED test certificate for ${NAME} (not for production)"
fi
