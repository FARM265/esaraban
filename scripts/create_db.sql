-- สร้างผู้ใช้และฐานข้อมูลสำหรับเครื่องพัฒนา
-- รันด้วย psql โดยส่งรหัสผ่านผ่านตัวแปร (ดู README หัวข้อ "สร้างฐานข้อมูล"):
--   psql -U postgres -v app_password=รหัสผ่าน -f scripts/create_db.sql

CREATE ROLE esaraban_app LOGIN PASSWORD :'app_password';

-- CREATEDB จำเป็นเฉพาะเครื่องพัฒนา เพื่อให้ "python manage.py test" สร้างฐานข้อมูลทดสอบได้
-- บน server จริงห้ามให้สิทธิ์นี้
ALTER ROLE esaraban_app CREATEDB;

CREATE DATABASE esaraban
    OWNER esaraban_app
    ENCODING 'UTF8'
    LC_COLLATE 'C'
    LC_CTYPE 'C'
    TEMPLATE template0;
-- ใช้ locale 'C' เพราะ Windows ภาษาไทยมักตั้ง locale เป็น codepage 874
-- ซึ่งใช้คู่กับ UTF8 ไม่ได้ ระบบจะจัดเรียงภาษาไทยตามลำดับ Unicode
