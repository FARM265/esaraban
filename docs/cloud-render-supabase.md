# ย้ายระบบขึ้นคลาวด์: Render + Supabase

ระบบทำงานบนอินเทอร์เน็ตโดยไม่ต้องเปิดคอมพิวเตอร์ทิ้งไว้

| ส่วน | ผู้ให้บริการ | หน้าที่ |
|---|---|---|
| ตัวเว็บ | Render | รันระบบจาก Dockerfile ได้ชื่อเว็บ `https://xxx.onrender.com` พร้อมใบรับรอง HTTPS จริง |
| ฐานข้อมูล | Supabase (PostgreSQL) | ทะเบียน ผู้ใช้ เส้นทางการเสนอ Audit Log |
| ไฟล์เอกสาร | Supabase Storage | ไฟล์ PDF ลายมือชื่อ ตรา (เข้ารหัสก่อนส่งขึ้นเสมอ Supabase อ่านเนื้อหาไม่ได้) |
| โค้ด | GitHub (แบบส่วนตัว) | Render ดึงโค้ดจากที่นี่ไป build |

> **ก่อนเริ่ม ให้ผู้บังคับบัญชารับทราบ:** ข้อมูลหนังสือจะเก็บที่ศูนย์ข้อมูลของบริษัทต่างประเทศ (เลือกภูมิภาคสิงคโปร์)
> และระบบเปิดบนอินเทอร์เน็ต ใครก็เปิดหน้าเข้าสู่ระบบได้ (ต้องมีชื่อผู้ใช้และรหัสผ่านจึงเข้าได้ ระบบล็อกเมื่อใส่ผิดหลายครั้ง)
>
> **แผนฟรีมีข้อจำกัด:** เว็บหลับเมื่อไม่มีคนใช้ 15 นาที (คนแรกที่เปิดรอประมาณ 1 นาที), RAM 512 MB,
> Supabase ฟรีพักโปรเจกต์ถ้าไม่มีใครใช้ 1 สัปดาห์, ฐานข้อมูล 500 MB และไฟล์ 1 GB
> ผู้ให้บริการระบุว่าแผนฟรีไม่เหมาะกับงานจริงและเปลี่ยนเงื่อนไขได้ เมื่อใช้งานจริงจังควรเปลี่ยนเป็นแผนเสียเงิน

ข้อมูลในเครื่องปัจจุบันเป็นข้อมูลทดลอง ระบบบนคลาวด์จะเริ่มจากฐานข้อมูลว่าง

---

## ขั้นที่ 1: Supabase (ฐานข้อมูลและที่เก็บไฟล์)

1. สมัครที่ https://supabase.com แล้วกด **New project**
   - Name: `esaraban`
   - Database Password: กด Generate แล้ว**คัดลอกเก็บไว้**
   - Region: **Southeast Asia (Singapore)**
2. รอโปรเจกต์สร้างเสร็จ แล้วกดปุ่ม **Connect** ด้านบน
   - เลือกแบบ **Session pooler** (รองรับ IPv4 ซึ่ง Render ต้องใช้)
   - คัดลอก connection string รูปแบบ `postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-...pooler.supabase.com:5432/postgres`
   - แทน `[YOUR-PASSWORD]` ด้วยรหัสผ่านจากข้อ 1 แล้วต่อท้ายด้วย `?sslmode=require`
   - เก็บไว้เป็นค่า **DATABASE_URL**
3. เมนู **Storage** กด **New bucket**
   - Name: `esaraban-files`
   - **ห้ามเปิด Public bucket** (ต้องเป็นแบบส่วนตัว)
4. เมนู **Storage > Settings** (หรือ Project Settings > Storage) ส่วน **S3 Connection**
   - คัดลอก **Endpoint** เก็บเป็น **S3_ENDPOINT_URL**
   - คัดลอก **Region** เก็บเป็น **S3_REGION**
   - ส่วน **S3 Access Keys** กด **New access key** คัดลอก **Access key ID** และ **Secret access key**
     (Secret แสดงครั้งเดียว) เก็บเป็น **S3_ACCESS_KEY_ID** และ **S3_SECRET_ACCESS_KEY**

## ขั้นที่ 2: โค้ดบน GitHub

โค้ดอยู่ที่ https://github.com/FARM265/esaraban แล้ว (ไม่มีไฟล์ค่าลับ) Render จะดึงจากที่นี่ไป build
เมื่อแก้โค้ดและส่งขึ้น GitHub แล้ว Render จะ build รุ่นใหม่ให้เอง

## ขั้นที่ 3: Render (ตัวเว็บ)

1. สมัครที่ https://render.com ด้วยบัญชี GitHub
2. กด **New > Blueprint** แล้วกด **Configure account / Connect GitHub** อนุญาตให้ Render เห็น repository `FARM265/esaraban`
   เลือก repository นี้ Render จะอ่านไฟล์ `render.yaml` และถามค่าต่อไปนี้

   | ค่า | ใส่ |
   |---|---|
   | DATABASE_URL | จากขั้นที่ 1 ข้อ 2 |
   | S3_ENDPOINT_URL, S3_REGION, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY | จากขั้นที่ 1 ข้อ 4 |
   | DJANGO_SUPERUSER_USERNAME | ชื่อผู้ดูแลระบบคนแรก เช่น `admin1` |
   | DJANGO_SUPERUSER_EMAIL | อีเมลผู้ดูแลระบบ |
   | DJANGO_SUPERUSER_PASSWORD | รหัสผ่านชั่วคราวที่ยาวและเดายาก |
   | ORG_CODE | รหัสหนังสือของหน่วยงาน |

3. กด **Apply** รอ build ประมาณ 10–15 นาที (ครั้งแรกนาน เพราะติดตั้งโปรแกรมอ่านภาพภาษาไทย)
4. **สำคัญที่สุด:** เปิด service `esaraban` > **Environment** คัดลอกค่า **SECRET_KEY** ที่ Render สร้างให้
   ไปเก็บในที่ปลอดภัย (เช่น พิมพ์ใส่ซองปิดผนึกเก็บในตู้นิรภัย) **ถ้า SECRET_KEY หาย ไฟล์เอกสารทั้งหมดจะเปิดไม่ได้อีกเลย
   และห้ามแก้ค่านี้หลังเริ่มใช้งาน**

## ขั้นที่ 4: เข้าใช้ครั้งแรก

1. เปิดที่อยู่ที่ Render แสดง (เช่น `https://esaraban.onrender.com`) เข้าสู่ระบบด้วยผู้ดูแลระบบจากขั้นที่ 3
2. กลับไป Render > Environment **ลบ DJANGO_SUPERUSER_PASSWORD ออก** แล้วกด Save
3. เมนู **สถานะระบบ**
   - "ที่เก็บไฟล์เอกสาร" ต้องผ่าน และแสดงว่าเป็น S3 bucket `esaraban-files`
   - "IP ของท่านที่ระบบเห็น" ต้องตรงกับ IP จริงของเครื่อง (ดูได้จากเว็บค้นหา "what is my ip")
     ถ้าไม่ตรง ให้แก้ `PROXY_XFF_HOPS` ใน Render เป็น `1` แล้วลองใหม่ (IP ใช้ในบันทึกตรวจสอบและการล็อกเมื่อใส่รหัสผิด)
4. ตั้งค่าสำนักงานตาม [คู่มือติดตั้ง](install.md) ข้อ 4 (กลุ่มงาน ผู้ใช้ ทะเบียน หัวหนังสือ เส้นทางการเสนอ)
5. การยืนยันตัวตน 2 ขั้น (รหัส 6 หลักจากแอป Authenticator) ปิดไว้เป็นค่าเริ่มต้น ถ้าต้องการเปิด
   ตั้ง `ESARABAN_LOGIN_REQUIRE_MFA=True` ใน Render (ผู้ใช้ทุกคนจะต้องสแกน QR ตั้งค่าในการเข้าครั้งถัดไป)
   และ `ESARABAN_SIGN_REQUIRE_OTP=True` ถ้าต้องการให้ใส่รหัสก่อนลงนามด้วย แนะนำให้เปิดเมื่อมีข้อมูลสำคัญ
   เพราะระบบเปิดบนอินเทอร์เน็ต ถ้ารหัสผ่านรั่ว ใครก็เข้าได้

## การปรับปรุงระบบรุ่นใหม่

เมื่อโค้ดรุ่นใหม่ถูกส่งขึ้น GitHub (branch `main`) Render จะ build และเปลี่ยนเป็นรุ่นใหม่ให้เอง
(ประมาณ 10 นาที ระหว่างนั้นรุ่นเดิมยังใช้งานได้)

## สำรองข้อมูล

Supabase แผนฟรีไม่มีการสำรองอัตโนมัติที่เรียกคืนเองได้ จึงต้องสำรองลงเครื่องของสำนักงานเป็นประจำ (ต้องมี Docker Desktop)

1. สร้างไฟล์ `C:\Projects\esaraban\.env.cloud` (ไฟล์นี้ไม่ถูกส่งขึ้น GitHub) ใส่
   ```
   DATABASE_URL=...
   S3_ENDPOINT_URL=...
   S3_REGION=...
   S3_BUCKET=esaraban-files
   S3_ACCESS_KEY_ID=...
   S3_SECRET_ACCESS_KEY=...
   ```
2. รันสัปดาห์ละครั้งหรือบ่อยกว่า
   ```
   powershell -ExecutionPolicy Bypass -File scripts\cloud-backup.ps1
   ```
   ได้โฟลเดอร์ `backups\cloud-วันเวลา` ที่มี `db.dump` ไฟล์เอกสาร และ `SHA256SUMS`
3. คัดลอกโฟลเดอร์นั้นไปเก็บอีกที่หนึ่ง และเก็บ SECRET_KEY แยกไว้ (ไม่ใช่ในโฟลเดอร์เดียวกัน)

### กู้คืน (เมื่อข้อมูลบนคลาวด์เสียหาย)

ให้ผู้พัฒนาหรือผู้ดูแลที่คุ้นเคยทำ: สร้างโปรเจกต์ Supabase ใหม่ แล้ว
`pg_restore --no-owner --no-privileges -d <DATABASE_URL ใหม่> db.dump` และอัปโหลดโฟลเดอร์ `files/documents`
กลับเข้า bucket ด้วย `aws s3 sync` จากนั้นแก้ DATABASE_URL และค่า S3 ใน Render โดยใช้ **SECRET_KEY เดิม**

## ย้อนกลับไปใช้บนเครื่องในสำนักงาน

ระบบยังรันแบบเดิมด้วย `docker compose` ได้ทุกอย่าง ค่าคลาวด์ทั้งหมดอยู่ใน Render เท่านั้น ไม่กระทบไฟล์ `.env.docker`
