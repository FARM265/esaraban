FROM nginx:1.27-alpine

# openssl สำหรับสร้างใบรับรองทดสอบ เมื่อยังไม่มีใบรับรองจริงของหน่วยงาน
# nginx ต้องอยู่กลุ่มเดียวกับแอป (gid 1000) เพื่ออ่านไฟล์ CSS/JS ที่ collectstatic สร้างด้วยสิทธิ์ 640
RUN apk add --no-cache openssl \
    && addgroup -g 1000 app \
    && addgroup nginx app

COPY 10-selfsigned-cert.sh /docker-entrypoint.d/10-selfsigned-cert.sh
COPY default.conf.template /etc/nginx/templates/default.conf.template
RUN sed -i 's/\r$//' /docker-entrypoint.d/10-selfsigned-cert.sh \
    && chmod 755 /docker-entrypoint.d/10-selfsigned-cert.sh
