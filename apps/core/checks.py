"""ตรวจความพร้อมของระบบ ใช้ในหน้าสถานะระบบ ทุกข้อเป็นการตรวจจริง ไม่ใช่ค่าคงที่"""
import os
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.contrib.staticfiles import finders
from django.db import connection

VENDOR_FILES = [
    "vendor/bootstrap/bootstrap.min.css",
    "vendor/bootstrap/bootstrap.bundle.min.js",
    "vendor/sarabun/sarabun-thai-400-normal.woff2",
    "vendor/sarabun/sarabun-thai-700-normal.woff2",
    "vendor/pdfjs/pdf.min.js",
    "vendor/pdfjs/pdf.worker.min.js",
    "vendor/sarabun/Sarabun-Regular.ttf",
    "vendor/sarabun/Sarabun-Bold.ttf",
]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_database():
    try:
        with connection.cursor() as cur:
            cur.execute("SHOW server_version")
            version = cur.fetchone()[0]
            cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'")
            has_trgm = cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001 แสดงข้อความผิดพลาดให้ผู้ดูแลเห็น
        return [CheckResult("เชื่อมต่อ PostgreSQL", False, str(exc).strip())]
    return [
        CheckResult("เชื่อมต่อ PostgreSQL", True, f"เวอร์ชัน {version}"),
        CheckResult(
            "ส่วนขยาย pg_trgm (ค้นหาภาษาไทย)",
            has_trgm,
            "พร้อมใช้งาน" if has_trgm else "ไม่พบ ต้องติดตั้งก่อนขั้นตอนที่ 8",
        ),
    ]


def check_vendor_files():
    missing = [path for path in VENDOR_FILES if not finders.find(path)]
    if missing:
        return CheckResult(
            "Bootstrap ฟอนต์ Sarabun และ PDF.js",
            False,
            "ไม่พบ " + ", ".join(missing) + " ให้รัน scripts\\download_vendor.ps1",
        )
    return CheckResult("Bootstrap ฟอนต์ Sarabun และ PDF.js", True, "พบครบทุกไฟล์")


def check_private_storage():
    if settings.ESARABAN_STORAGE_BACKEND == "s3":
        from apps.documents import storage

        try:
            where = storage.probe()
        except Exception as exc:  # noqa: BLE001
            return CheckResult("ที่เก็บไฟล์เอกสาร", False, f"เชื่อมต่อที่เก็บไฟล์ S3 ไม่ได้: {type(exc).__name__}")
        return CheckResult("ที่เก็บไฟล์เอกสาร", True, f"เขียนและอ่านได้ที่ {where} (เข้ารหัสก่อนส่งออก)")
    root = settings.PRIVATE_STORAGE_ROOT
    static_dirs = [str(d) for d in settings.STATICFILES_DIRS] + [str(settings.STATIC_ROOT)]
    if any(str(root).startswith(d) for d in static_dirs):
        return CheckResult("ที่เก็บไฟล์เอกสาร", False, "ห้ามอยู่ในโฟลเดอร์ static")
    try:
        os.makedirs(root, exist_ok=True)
        probe = root / f".write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        return CheckResult("ที่เก็บไฟล์เอกสาร", False, f"เขียนไม่ได้: {exc}")
    return CheckResult("ที่เก็บไฟล์เอกสาร", True, f"เขียนได้ที่ {root}")


def check_secret_key():
    weak = settings.SECRET_KEY in ("", "change-me") or len(settings.SECRET_KEY) < 40
    return CheckResult(
        "SECRET_KEY",
        not weak,
        "ยาวพอและไม่ใช่ค่าตัวอย่าง" if not weak else "ยังเป็นค่าตัวอย่างหรือสั้นเกินไป",
    )


def check_thai_shaping():
    from PIL import features

    ok = features.check("raqm")
    return CheckResult(
        "การจัดวางอักษรไทยในไฟล์ PDF (raqm)",
        ok,
        "พร้อมใช้งาน" if ok else "ไม่พร้อม ข้อความสั่งการ/เกษียนที่ฝังลงไฟล์อาจวางวรรณยุกต์ไม่ถูกตำแหน่ง ให้ติดตั้ง libfribidi",
    )


def check_thai_wordbreak():
    from apps.letters import thaibreak

    ok = thaibreak.available()
    return CheckResult(
        "การตัดคำภาษาไทย (libthai)",
        ok,
        "พร้อมใช้งาน" if ok else "ไม่พร้อม หนังสือจากแม่แบบจะขึ้นบรรทัดใหม่ได้เฉพาะที่ช่องว่าง ให้ติดตั้ง libthai0",
    )


def check_db_role():
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user")
            user, superuser = cursor.fetchone()
    except Exception:  # ฐานข้อมูลไม่พร้อม แจ้งไว้แล้วในข้อตรวจฐานข้อมูล
        return CheckResult("ผู้ใช้ฐานข้อมูลขณะทำงาน", False, "ตรวจไม่ได้")
    return CheckResult(
        "ผู้ใช้ฐานข้อมูลขณะทำงาน",
        not superuser,
        f"{user} (จำกัดสิทธิ์)" if not superuser
        else f"{user} เป็น superuser ใช้ได้ในช่วงทดลอง สำหรับใช้งานจริงให้ตั้ง POSTGRES_APP_USER",
    )


def run_all():
    return [
        *check_database(), check_vendor_files(), check_thai_shaping(), check_thai_wordbreak(),
        check_private_storage(), check_secret_key(), check_db_role(),
    ]
