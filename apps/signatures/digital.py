"""
ลายมือชื่อดิจิทัลด้วยใบรับรองทดสอบ (ไม่มีผลทางกฎหมาย)

- certificate_authority()   CA ทดสอบของระบบ สร้างครั้งแรกเมื่อมีการลงนามดิจิทัล
- credential_for(user)      ใบรับรองของผู้ใช้ ออกให้อัตโนมัติ (ต่ออายุอัตโนมัติเมื่อหมดอายุ)
- appearance_png(...)       ภาพที่มองเห็นบนเอกสาร: ภาพลายมือชื่อ + คำอธิบายว่าเป็นลายมือชื่อดิจิทัลทดสอบ
- verify_attachment(...)    ตรวจลายมือชื่อดิจิทัลทุกอันในไฟล์

กุญแจลับทุกดอกเข้ารหัสด้วย Fernet และเก็บใน private storage เหมือนไฟล์เอกสาร ไม่เคยส่งออกไปที่เบราว์เซอร์
"""
import datetime as dt
from io import BytesIO

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont, features

from apps.core.templatetags.thai_date import thai_datetime
from apps.documents import storage

from . import pdfsign, pki
from .models import SigningCertificate, TestCertificateAuthority

RENEW_BEFORE = dt.timedelta(days=7)


def enabled():
    return settings.ESARABAN_DIGITAL_SIGNING


def _save_key(key):
    return storage.save_encrypted(pki.key_to_pem(key))


def _load_key(storage_key, sha):
    return pki.key_from_pem(storage.read_decrypted(storage_key, sha))


def certificate_authority():
    authority = TestCertificateAuthority.objects.order_by("pk").first()
    if authority:
        return authority
    from apps.letters.models import Letterhead

    key, cert = pki.create_ca(Letterhead.current().org_name)
    storage_key, sha = _save_key(key)
    try:
        with transaction.atomic():
            return TestCertificateAuthority.objects.create(
                cert_pem=pki.cert_to_pem(cert).decode(), key_storage_key=storage_key, key_sha256=sha,
                fingerprint=pki.fingerprint(cert),
            )
    except IntegrityError:  # สร้างพร้อมกันสองคำขอ ใช้ของที่สร้างก่อน
        storage.remove_quietly(storage_key)
        return TestCertificateAuthority.objects.order_by("pk").first()


def ca_certificate(authority=None):
    return pki.cert_from_pem((authority or certificate_authority()).cert_pem.encode())


def trusted_roots():
    return [pki.cert_from_pem(a.cert_pem.encode()) for a in TestCertificateAuthority.objects.all()]


def active_credential(user):
    return SigningCertificate.objects.filter(user=user, is_active=True).select_related("authority").first()


def credential_for(user):
    """ใบรับรองที่ใช้ลงนามได้ตอนนี้ ถ้าไม่มีหรือใกล้หมดอายุ ออกใบใหม่ให้"""
    current = active_credential(user)
    if current and current.not_after - RENEW_BEFORE > timezone.now():
        return current
    authority = certificate_authority()
    ca_key = _load_key(authority.key_storage_key, authority.key_sha256)
    ca_cert = ca_certificate(authority)
    key, cert = pki.issue_user_certificate(
        ca_key, ca_cert, common_name=user.display_name_th or user.get_username(), email=user.email or "",
    )
    storage_key, sha = _save_key(key)
    try:
        with transaction.atomic():
            SigningCertificate.objects.filter(user=user, is_active=True).update(is_active=False)
            return SigningCertificate.objects.create(
                user=user, authority=authority, cert_pem=pki.cert_to_pem(cert).decode(),
                key_storage_key=storage_key, key_sha256=sha, fingerprint=pki.fingerprint(cert),
                common_name=pki.common_name(cert),
                not_before=cert.not_valid_before_utc, not_after=cert.not_valid_after_utc,
            )
    except Exception:
        storage.remove_quietly(storage_key)
        raise


def signing_material(credential):
    key = _load_key(credential.key_storage_key, credential.key_sha256)
    cert = pki.cert_from_pem(credential.cert_pem.encode())
    return key, cert, [ca_certificate(credential.authority)]


def appearance_png(signature_png, *, signer_name, moment):
    """ภาพลายมือชื่อด้านบน คำอธิบาย 3 บรรทัดด้านล่าง (สีน้ำเงินเข้ม) พื้นโปร่งใส"""
    sig = Image.open(BytesIO(signature_png)).convert("RGBA")
    width = 900
    sig = sig.resize((width, max(1, round(sig.height * width / sig.width))))
    lines = [
        f"ลงนามดิจิทัลโดย {signer_name}",
        thai_datetime(timezone.localtime(moment)),
        "ใบรับรองทดสอบ ไม่มีผลทางกฎหมาย",
    ]
    layout = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    size = 44
    font = ImageFont.truetype(str(settings.ESARABAN_TEXT_FONT), size=size, layout_engine=layout)
    while size > 16 and max(font.getlength(line) for line in lines) > width:
        size -= 2
        font = ImageFont.truetype(str(settings.ESARABAN_TEXT_FONT), size=size, layout_engine=layout)
    line_h = round(size * 1.35)
    canvas = Image.new("RGBA", (width, sig.height + line_h * len(lines) + 10), (0, 0, 0, 0))
    canvas.alpha_composite(sig, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.line((0, sig.height + 2, width, sig.height + 2), fill=(31, 58, 147, 180), width=2)
    for index, line in enumerate(lines):
        x = (width - font.getlength(line)) / 2
        draw.text((x, sig.height + 8 + index * line_h), line, font=font, fill=(31, 58, 147, 255))
    out = BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


def has_digital_signatures(pdf):
    return pdfsign.has_signatures(pdf)


def verify_bytes(pdf):
    return pdfsign.verify_pdf(pdf, trusted_roots())
