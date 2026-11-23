"""
ที่เก็บไฟล์เอกสารแบบเข้ารหัส

- ไฟล์ถูกเข้ารหัสด้วย Fernet (AES-128-CBC + HMAC-SHA256) ก่อนเขียนลงดิสก์
- ชื่อไฟล์บนดิสก์สุ่มใหม่ ไม่ใช้ชื่อไฟล์ที่ผู้ใช้อัปโหลด
- อ่านไฟล์ได้เฉพาะผ่าน view ที่ตรวจสิทธิ์แล้วเท่านั้น (ไม่มี URL ตรงไปยังไฟล์)

กุญแจมาจาก FILE_ENCRYPTION_KEY หรือสร้างจาก SECRET_KEY ถ้าไม่ได้ตั้ง
ถ้ากุญแจเปลี่ยน ไฟล์เดิมทั้งหมดจะเปิดไม่ได้ ต้องสำรองกุญแจไว้คู่กับข้อมูลสำรอง

ที่เก็บมี 2 แบบ (ESARABAN_STORAGE_BACKEND)
- "local" (ค่าเริ่มต้น): ดิสก์ของเครื่อง ที่ PRIVATE_STORAGE_ROOT
- "s3": ที่เก็บไฟล์แบบ S3 เช่น Supabase Storage ใช้เมื่อรันบนคลาวด์ที่ดิสก์ไม่ถาวร
  ไฟล์ถูกเข้ารหัสก่อนส่งออกจากระบบเสมอ ผู้ให้บริการที่เก็บไฟล์จึงอ่านเนื้อหาไม่ได้
  bucket ต้องเป็นแบบส่วนตัว (private) เท่านั้น
"""
import base64
import hashlib
import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone


def _fernet():
    raw = settings.FILE_ENCRYPTION_KEY or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(("files:" + raw).encode()).digest())
    return Fernet(key)


def _backend():
    return getattr(settings, "ESARABAN_STORAGE_BACKEND", "local")


_s3_client = None


def _s3():
    """client ของ boto3 สร้างครั้งเดียวต่อ process"""
    global _s3_client
    if _s3_client is None:
        import boto3
        from botocore.config import Config

        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3, "mode": "standard"},
                          connect_timeout=10, read_timeout=60),
        )
    return _s3_client


def _check_key(storage_key):
    if not storage_key.startswith("documents/") or ".." in storage_key or "\\" in storage_key:
        raise ValueError("storage key ไม่ถูกต้อง")
    return storage_key


def _root():
    return Path(settings.PRIVATE_STORAGE_ROOT).resolve()


def _path_for(storage_key):
    path = (_root() / storage_key).resolve()
    if _root() not in path.parents:
        raise ValueError("storage key อยู่นอกที่เก็บไฟล์")
    return path


def save_encrypted(data):
    """เข้ารหัสแล้วบันทึก คืนค่า (storage_key, sha256 ของไฟล์ต้นฉบับ)"""
    digest = hashlib.sha256(data).hexdigest()
    storage_key = f"documents/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}.bin"
    if _backend() == "s3":
        _s3().put_object(Bucket=settings.S3_BUCKET, Key=storage_key, Body=_fernet().encrypt(data),
                         ContentType="application/octet-stream")
        return storage_key, digest
    path = _path_for(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        fh.write(_fernet().encrypt(data))
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, settings.FILE_UPLOAD_PERMISSIONS or 0o640)
    tmp.replace(path)
    return storage_key, digest


def read_decrypted(storage_key, expected_sha256=None):
    if _backend() == "s3":
        response = _s3().get_object(Bucket=settings.S3_BUCKET, Key=_check_key(storage_key))
        data = _fernet().decrypt(response["Body"].read())
    else:
        with open(_path_for(storage_key), "rb") as fh:
            data = _fernet().decrypt(fh.read())
    if expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("ไฟล์ไม่ตรงกับ hash ที่บันทึกไว้ อาจถูกแก้ไขหรือเสียหาย")
    return data


def remove_quietly(storage_key):
    """ใช้ลบไฟล์ที่เพิ่งเขียนเมื่อการบันทึกฐานข้อมูลล้มเหลวเท่านั้น"""
    try:
        if _backend() == "s3":
            _s3().delete_object(Bucket=settings.S3_BUCKET, Key=_check_key(storage_key))
        else:
            _path_for(storage_key).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001  ลบไม่สำเร็จไม่ควรบังข้อผิดพลาดเดิม
        pass


def probe():
    """ตรวจว่าเขียน อ่าน และลบไฟล์ในที่เก็บได้ (ใช้ในหน้าสถานะระบบ) คืนข้อความอธิบายที่เก็บ"""
    key, digest = save_encrypted(b"esaraban-probe")
    try:
        if read_decrypted(key, digest) != b"esaraban-probe":
            raise ValueError("อ่านกลับได้ไม่ตรงกับที่เขียน")
    finally:
        remove_quietly(key)
    if _backend() == "s3":
        return f"S3 bucket {settings.S3_BUCKET}"
    return str(_root())
