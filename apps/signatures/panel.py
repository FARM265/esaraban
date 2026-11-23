"""ข้อมูลแผง "ลงนาม" ในหน้ารายละเอียดเอกสาร (การเลือกตำแหน่งทำในตัวดู PDF)"""
from . import services


def signable_attachments(document):
    return list(document.attachments.order_by("-version", "uploaded_at"))


def context_for(user, document):
    records = document.signatures.select_related("signer", "signed_attachment")
    can = services.can_sign(user, document)
    attachments = signable_attachments(document) if can else []
    main = next((a for a in attachments if a.is_main), attachments[0] if attachments else None)
    return {
        "can_sign": can,
        "sign_target": main,
        "sign_has_image": can and services.active_signature_image(user) is not None,
        "sign_records": records,
    }
