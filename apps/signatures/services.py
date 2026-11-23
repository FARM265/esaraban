import hashlib
from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from apps.accounts import security
from apps.accounts.permissions import has_capability
from apps.documents import access, storage
from apps.documents.models import LOCKED_STATUSES, Attachment, Document, DocumentEvent, DocumentStatus
from apps.documents.services import log_event

from . import stamping
from .models import DocumentSignature, SignatureImage, SignatureType

def active_signature_image(user):
    return SignatureImage.objects.filter(user=user, is_active=True).first()


@transaction.atomic
def upload_signature_image(user, data):
    try:
        png, width, height = stamping.clean_signature_image(data)
    except stamping.StampError as exc:
        raise ValidationError(str(exc)) from exc
    key, digest = storage.save_encrypted(png)
    SignatureImage.objects.filter(user=user, is_active=True).update(is_active=False)
    return SignatureImage.objects.create(user=user, storage_key=key, sha256=digest, width=width, height=height)


def read_signature_png(image):
    return storage.read_decrypted(image.storage_key, image.sha256)


def can_sign(user, document):
    return (
        document.status not in LOCKED_STATUSES
        and access.can_view(user, document)
        and has_capability(user, "sign_documents", document.owner_department)
    )


def create_final_copy(*, attachment, user, signature=None, otp_code="", ip=None):
    """
    สร้างไฟล์ฉบับใหม่ 1 ไฟล์ ที่ฝังข้อความสั่งการ/เกษียนบนไฟล์นี้ และ/หรือ ลายมือชื่อของผู้ใช้
    ทำอย่างใดอย่างหนึ่งหรือทั้งสองอย่างก็ได้ ไฟล์เดิมยังอยู่ครบ
    signature = {"page", "x", "y", "w", "digital": bool} (สัดส่วนของหน้า) หรือ None ถ้าไม่ลงนาม

    digital=False  วางภาพลายมือชื่อลงในเนื้อหาหน้า (ไม่ใช่ Digital Signature)
    digital=True   ลงลายมือชื่อดิจิทัลด้วยใบรับรองทดสอบ ภาพที่มองเห็นอยู่ในช่องลายมือชื่อ
                   ไฟล์ที่มีลายมือชื่อดิจิทัลแล้ว เพิ่มได้เฉพาะลายมือชื่อดิจิทัล (ต่อท้ายไฟล์) เพื่อไม่ให้ลายมือชื่อเดิมเสีย
    """
    from apps.annotations import services as endorsing

    from . import digital, pdfsign

    document = attachment.document
    texts = list(endorsing.active_texts(attachment))
    if signature is None and not texts:
        raise ValidationError("ยังไม่มีข้อความสั่งการ/เกษียนหรือลายเซ็นที่จะบันทึกลงไฟล์")
    if texts and not endorsing.can_endorse(user, document):
        raise PermissionDenied
    is_digital = bool(signature and signature.get("digital"))
    if is_digital and not digital.enabled():
        raise ValidationError("ระบบปิดการลงนามแบบดิจิทัลไว้")
    image = None
    if signature is not None:
        if not can_sign(user, document):
            raise PermissionDenied
        image = active_signature_image(user)
        if image is None:
            raise ValidationError("ท่านยังไม่ได้อัปโหลดภาพลายมือชื่อ")
        if not stamping.MIN_WIDTH_RATIO <= signature["w"] <= stamping.MAX_WIDTH_RATIO:
            raise ValidationError("ขนาดลายเซ็นไม่ถูกต้อง")

    source = storage.read_decrypted(attachment.storage_key, attachment.sha256)
    if digital.has_digital_signatures(source) and (texts or (image is not None and not is_digital)):
        raise ValidationError(
            "ไฟล์นี้มีลายมือชื่อดิจิทัลแล้ว การเขียนข้อความหรือวางภาพลงเนื้อหาจะทำให้ลายมือชื่อเดิมใช้ไม่ได้ "
            "เพิ่มได้เฉพาะลายมือชื่อดิจิทัล (ลบข้อความสั่งการ/เกษียนบนไฟล์นี้ก่อน)"
        )
    if image is not None and settings.ESARABAN_SIGN_REQUIRE_OTP and not security.verify_user_totp(user, otp_code):
        # ยืนยันตัวตนอีกครั้งก่อนลงนาม (เปิดด้วย ESARABAN_SIGN_REQUIRE_OTP)
        raise ValidationError("รหัสยืนยัน 6 หลักไม่ถูกต้อง จึงยังไม่ได้สร้างไฟล์")

    credential = None
    moment = timezone.now()
    try:
        stamps = endorsing.text_stamps(texts, source)
        if image is not None and not is_digital:
            stamps.append({
                "page": signature["page"], "x": signature["x"], "y": signature["y"],
                "png": read_signature_png(image), "width_ratio": signature["w"],
            })
        result = stamping.stamp_images(source, stamps) if stamps else source
        if is_digital:
            credential = digital.credential_for(user)
            key, cert, chain = digital.signing_material(credential)
            result = pdfsign.sign_pdf(
                result, key=key, cert=cert, chain=chain, signer_name=credential.common_name, moment=moment,
                reason=f"ลงนามหนังสือ: {document.subject}"[:200], location=document.owner_department.name_th
                if document.owner_department else "",
                appearance={
                    "page": signature["page"], "x": signature["x"], "y": signature["y"], "w": signature["w"],
                    "png": digital.appearance_png(read_signature_png(image), signer_name=user.display_name_th,
                                                  moment=moment),
                },
            )
    except (stamping.StampError, pdfsign.SignError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc

    signer_label = f"ลงนามดิจิทัล {user.display_name_th}" if is_digital else f"ลงนาม {user.display_name_th}"
    parts = (["สั่งการ-เกษียน"] if texts else []) + ([signer_label] if image else [])
    key, digest = storage.save_encrypted(result)
    try:
        with transaction.atomic():
            Document.objects.select_for_update().get(pk=document.pk)  # ลำดับเวอร์ชันไม่ชนกัน
            version = (document.attachments.aggregate(v=Max("version"))["v"] or 0) + 1
            stem = PurePath(attachment.original_name).stem
            new_file = Attachment.objects.create(
                document=document,
                original_name=f"{stem} ({', '.join(parts)}).pdf"[:255],
                storage_key=key,
                size=len(result),
                sha256=digest,
                page_count=attachment.page_count,
                is_main=attachment.is_main,
                is_signed_copy=attachment.is_signed_copy or image is not None,
                version=version,
                uploaded_by=user,
            )
            if texts:
                log_event(document, user, DocumentEvent.Action.ENDORSED, ip,
                          file=new_file.original_name, texts=len(texts))
            if image is not None:
                DocumentSignature.objects.create(
                    document=document,
                    source_attachment=attachment,
                    signed_attachment=new_file,
                    signer=user,
                    sig_type=SignatureType.DIGITAL if is_digital else SignatureType.IMAGE,
                    signature_image=image,
                    certificate=credential,
                    page=signature["page"],
                    position=f"x={signature['x']:.3f} y={signature['y']:.3f} w={signature['w']:.3f}",
                    source_sha256=attachment.sha256,
                    signed_sha256=hashlib.sha256(result).hexdigest(),
                    mfa_verified=True,
                    ip_address=ip or None,
                    signed_at=moment,
                )
                log_event(document, user, DocumentEvent.Action.SIGNED, ip, file=new_file.original_name,
                          sig_type="ลายมือชื่อดิจิทัล (ใบรับรองทดสอบ)" if is_digital else "ภาพลายมือชื่อ",
                          page=signature["page"])
            from apps.notifications.services import notify

            action = " และ".join(
                (["สั่งการ/เกษียน"] if texts else []) + (["ลงนาม"] if image is not None else [])
            )
            notify([document.created_by], f"{user.display_name_th} {action}แล้ว", body=document.subject,
                   document=document, exclude=user, url=reverse("documents:viewer", args=[new_file.pk]))
    except Exception:
        storage.remove_quietly(key)
        raise
    return new_file
