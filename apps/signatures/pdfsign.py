"""
ลายมือชื่อดิจิทัลบน PDF (มาตรฐาน PDF: /adbe.pkcs7.detached, CMS SignedData, RSA-SHA256)

- sign_pdf    เพิ่มลายมือชื่อแบบ incremental update (ต่อท้ายไฟล์ ไม่แก้ไบต์เดิม) ลายมือชื่อก่อนหน้าจึงยังใช้ได้
              ภาพที่มองเห็น (ภาพลายมือชื่อ + คำอธิบาย) อยู่ใน appearance ของช่องลายมือชื่อ ไม่ได้เขียนทับเนื้อหาหน้า
- verify_pdf  ตรวจทุกลายมือชื่อในไฟล์: hash ของช่วงที่ลงนาม ลายมือชื่อของผู้ลงนาม ใบรับรองออกโดย CA ที่เชื่อถือ
              และมีการเพิ่มข้อมูลหลังลงนามหรือไม่

ไม่ import Django จึงทดสอบแยกได้ อ่านไฟล์ที่ผ่าน pdfcheck แล้วเท่านั้น
"""
import datetime as dt
import hashlib
import re
import zlib
from dataclasses import dataclass, field
from io import BytesIO

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    StreamObject,
    TextStringObject,
)

SIG_BYTES = 16384                    # พื้นที่สำรองสำหรับ CMS (hex จึงยาว 2 เท่า)
BYTERANGE_PLACEHOLDER = 9_999_999_999
SUBFILTER = "/adbe.pkcs7.detached"


class SignError(Exception):
    pass


# ---------------------------------------------------------------- ลงนาม
def _pdf_date(moment):
    moment = moment.astimezone(dt.timezone.utc)
    return moment.strftime("D:%Y%m%d%H%M%S+00'00'")


def _image_xobject(png):
    """แปลง PNG เป็น Image XObject (RGB + SMask สำหรับความโปร่งใส)"""
    image = Image.open(BytesIO(png)).convert("RGBA")
    width, height = image.size
    rgb = image.convert("RGB").tobytes()
    alpha = image.getchannel("A").tobytes()

    def stream(data, colorspace):
        obj = StreamObject()
        obj._data = zlib.compress(data, 9)
        obj.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(width),
            NameObject("/Height"): NumberObject(height),
            NameObject("/ColorSpace"): NameObject(colorspace),
            NameObject("/BitsPerComponent"): NumberObject(8),
            NameObject("/Filter"): NameObject("/FlateDecode"),
        })
        return obj

    return stream(rgb, "/DeviceRGB"), stream(alpha, "/DeviceGray")


ROTATION_MATRIX = {0: (1, 0, 0, 1), 90: (0, 1, -1, 0), 180: (-1, 0, 0, -1), 270: (0, -1, 1, 0)}


def _appearance(writer, png, width, height, rotation=0):
    """width/height คือขนาดที่เห็นบนจอ ถ้าหน้าถูกหมุน หมุนภาพกลับด้วย /Matrix เพื่อให้ตั้งตรงบนจอ"""
    image, mask = _image_xobject(png)
    image[NameObject("/SMask")] = writer._add_object(mask)
    image_ref = writer._add_object(image)
    ap = DecodedStreamObject()
    ap.set_data(f"q {width:.3f} 0 0 {height:.3f} 0 0 cm /Img Do Q".encode())
    ap.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(width), FloatObject(height)]),
        NameObject("/Matrix"): ArrayObject([NumberObject(v) for v in ROTATION_MATRIX[rotation]] + [NumberObject(0)] * 2),
        NameObject("/Resources"): DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Img"): image_ref}),
        }),
    })
    return writer._add_object(ap)


def _walk_fields(reader):
    """ไล่ช่องใน AcroForm เอง (get_fields ของ pypdf พยายามถอดรหัส /Contents ที่เป็นไบนารีแล้วล้ม)"""
    root = reader.trailer["/Root"]
    acroform = root.get("/AcroForm")
    if acroform is None:
        return
    stack = [(item, "") for item in reversed(list(acroform.get_object().get("/Fields", [])))]
    seen = set()
    while stack:
        ref, parent_name = stack.pop()
        node = ref.get_object()
        if id(node) in seen:
            continue
        seen.add(id(node))
        name = str(node.get("/T", ""))
        full = f"{parent_name}.{name}" if parent_name and name else (name or parent_name)
        kids = node.get("/Kids")
        if kids:
            stack.extend((kid, full) for kid in reversed(list(kids.get_object())))
        yield full, node


def _field_names(reader):
    return {name for name, _ in _walk_fields(reader)}


def sign_pdf(pdf, *, key, cert, chain=(), signer_name="", reason="", location="", moment=None,
             appearance=None, field_prefix="ลงนาม"):
    """
    appearance = {"page": เลขหน้า (เริ่ม 1), "x", "y", "w": สัดส่วนของหน้า (x, y คือมุมซ้ายบน), "png": bytes}
    ถ้าไม่ระบุ จะเป็นลายมือชื่อที่มองไม่เห็น
    """
    moment = moment or dt.datetime.now(dt.timezone.utc)
    try:
        reader = PdfReader(BytesIO(pdf))
        writer = PdfWriter(BytesIO(pdf), incremental=True)
    except Exception as exc:  # pypdf ยก exception ได้หลายแบบเมื่อไฟล์เสีย
        raise SignError("อ่านไฟล์ PDF ไม่ได้") from exc
    if reader.is_encrypted:
        raise SignError("ไฟล์ถูกเข้ารหัส ลงนามไม่ได้")
    # pypdf ไม่นับเลขอ็อบเจกต์ของ xref stream ที่ตนเขียนไว้ในรอบก่อน ถ้าไม่จองไว้ ลายมือชื่อที่สองจะได้เลขซ้ำกับ xref stream
    size = int(reader.trailer.get("/Size", 0))
    if len(writer._objects) < size - 1:
        writer._objects.extend([None] * (size - 1 - len(writer._objects)))

    existing = _field_names(reader)
    index = 1
    while f"{field_prefix}{index}" in existing:
        index += 1
    field_name = f"{field_prefix}{index}"

    sig = DictionaryObject({
        NameObject("/Type"): NameObject("/Sig"),
        NameObject("/Filter"): NameObject("/Adobe.PPKLite"),
        NameObject("/SubFilter"): NameObject(SUBFILTER),
        NameObject("/ByteRange"): ArrayObject([NumberObject(0)] + [NumberObject(BYTERANGE_PLACEHOLDER)] * 3),
        NameObject("/Contents"): ByteStringObject(b"\x00" * SIG_BYTES),
        NameObject("/M"): TextStringObject(_pdf_date(moment)),
    })
    if signer_name:
        sig[NameObject("/Name")] = TextStringObject(signer_name)
    if reason:
        sig[NameObject("/Reason")] = TextStringObject(reason)
    if location:
        sig[NameObject("/Location")] = TextStringObject(location)
    sig_ref = writer._add_object(sig)

    page_number = appearance["page"] if appearance else 1
    if not 1 <= page_number <= len(writer.pages):
        raise SignError(f"เลขหน้าต้องอยู่ระหว่าง 1 ถึง {len(writer.pages)}")
    page = writer.pages[page_number - 1]
    widget = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Sig"),
        NameObject("/T"): TextStringObject(field_name),
        NameObject("/V"): sig_ref,
        NameObject("/F"): NumberObject(132),  # Print + Locked
        NameObject("/P"): page.indirect_reference,
    })
    if appearance:
        rect = _widget_rect(page, appearance)
        x0, y0, x1, y1 = rect
        rotation = (page.get("/Rotate", 0) or 0) % 360
        view_w, view_h = (y1 - y0, x1 - x0) if rotation in (90, 270) else (x1 - x0, y1 - y0)
        widget[NameObject("/Rect")] = ArrayObject([FloatObject(v) for v in rect])
        widget[NameObject("/AP")] = DictionaryObject({
            NameObject("/N"): _appearance(writer, appearance["png"], view_w, view_h, rotation),
        })
    else:
        widget[NameObject("/Rect")] = ArrayObject([FloatObject(0)] * 4)
    widget_ref = writer._add_object(widget)

    annots = page.get("/Annots")
    annots = ArrayObject(list(annots.get_object())) if annots is not None else ArrayObject()
    annots.append(widget_ref)
    page[NameObject("/Annots")] = annots

    root = writer._root_object
    acroform = root.get("/AcroForm")
    acroform = DictionaryObject(dict(acroform.get_object())) if acroform is not None else DictionaryObject()
    fields = acroform.get("/Fields")
    fields = ArrayObject(list(fields.get_object())) if fields is not None else ArrayObject()
    fields.append(widget_ref)
    acroform[NameObject("/Fields")] = fields
    acroform[NameObject("/SigFlags")] = NumberObject(3)
    root[NameObject("/AcroForm")] = writer._add_object(acroform)

    out = BytesIO()
    writer.write(out)
    data = bytearray(out.getvalue())
    if not data.startswith(pdf):
        raise SignError("การเขียนแบบต่อท้ายไฟล์ล้มเหลว")
    return _fill_signature(data, len(pdf), key, cert, chain, moment)


def _widget_rect(page, appearance):
    """แปลงตำแหน่งบนจอ (สัดส่วน มุมซ้ายบน) เป็น Rect ในพิกัด PDF ของหน้า (คำนึงถึง cropbox และการหมุน)"""
    box = page.cropbox
    left, bottom = float(box.left), float(box.bottom)
    width, height = float(box.width), float(box.height)
    rotation = (page.get("/Rotate", 0) or 0) % 360
    image = Image.open(BytesIO(appearance["png"]))
    view_w, view_h = (height, width) if rotation in (90, 270) else (width, height)
    w = appearance["w"] * view_w
    h = w * image.height / image.width
    vx, vy = appearance["x"] * view_w, appearance["y"] * view_h  # มุมซ้ายบนบนจอ
    if rotation == 0:
        x0, y0 = left + vx, bottom + height - vy - h
        return [x0, y0, x0 + w, y0 + h]
    if rotation == 90:
        x0, y0 = left + vy, bottom + vx
        return [x0, y0, x0 + h, y0 + w]
    if rotation == 180:
        x0, y0 = left + width - vx - w, bottom + vy
        return [x0, y0, x0 + w, y0 + h]
    x0, y0 = left + width - vy - h, bottom + height - vx - w
    return [x0, y0, x0 + h, y0 + w]


def _fill_signature(data, original_length, key, cert, chain, moment):
    tail = bytes(data[original_length:])
    placeholder = b"<" + b"0" * (SIG_BYTES * 2) + b">"
    at = tail.find(placeholder)
    if at < 0 or tail.find(placeholder, at + 1) >= 0:
        raise SignError("หาตำแหน่งลายมือชื่อในไฟล์ไม่พบ")
    start = original_length + at
    end = start + len(placeholder)
    br_pattern = re.compile(rb"/ByteRange\s*\[\s*0\s+%d\s+%d\s+%d\s*\]" % ((BYTERANGE_PLACEHOLDER,) * 3))
    matches = list(br_pattern.finditer(tail))
    if len(matches) != 1:
        raise SignError("หาตำแหน่ง ByteRange ไม่พบ")
    match = matches[0]
    byte_range = f"/ByteRange [0 {start} {end} {len(data) - end}]".encode()
    byte_range = byte_range.ljust(match.end() - match.start(), b" ")
    data[original_length + match.start():original_length + match.end()] = byte_range

    signed = bytes(data[:start]) + bytes(data[end:])
    builder = pkcs7.PKCS7SignatureBuilder().set_data(signed).add_signer(cert, key, hashes.SHA256())
    for extra in chain:
        builder = builder.add_certificate(extra)
    cms = builder.sign(
        Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary,
                       pkcs7.PKCS7Options.NoCapabilities],
    )
    if len(cms) > SIG_BYTES:
        raise SignError("ลายมือชื่อมีขนาดใหญ่เกินพื้นที่สำรอง")
    data[start + 1:end - 1] = cms.hex().upper().encode().ljust(SIG_BYTES * 2, b"0")
    return bytes(data)


# ---------------------------------------------------------------- อ่าน CMS (DER) แบบย่อ
def _tlv(buf, pos):
    tag = buf[pos]
    pos += 1
    length = buf[pos]
    pos += 1
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4:
            raise ValueError("ความยาว DER ไม่รองรับ")
        length = int.from_bytes(buf[pos:pos + count], "big")
        pos += count
    if pos + length > len(buf):
        raise ValueError("ข้อมูล DER ไม่ครบ")
    return tag, pos, pos + length  # tag, เริ่มเนื้อหา, จบ


def _children(buf, start, end):
    items, pos = [], start
    while pos < end:
        tag, cstart, cend = _tlv(buf, pos)
        items.append((tag, pos, cstart, cend))
        pos = cend
    return items


def _oid(raw):
    first = raw[0]
    parts, value = [first // 40, first % 40], 0
    for byte in raw[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return ".".join(map(str, parts))


OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
OID_SIGNING_TIME = "1.2.840.113549.1.9.5"
DIGESTS = {
    "2.16.840.1.101.3.4.2.1": hashes.SHA256, "2.16.840.1.101.3.4.2.2": hashes.SHA384,
    "2.16.840.1.101.3.4.2.3": hashes.SHA512, "1.3.14.3.2.26": hashes.SHA1,
}


@dataclass
class ParsedCMS:
    certificates: list
    digest_algorithm: object
    signed_attrs_der: bytes
    message_digest: bytes
    signing_time: object
    signature: bytes
    serial: int


def parse_cms(der):
    _, s, e = _tlv(der, 0)                                 # ContentInfo
    top = _children(der, s, e)
    if _oid(der[top[0][2]:top[0][3]]) != OID_SIGNED_DATA:
        raise ValueError("ไม่ใช่ SignedData")
    _, s, e = _tlv(der, top[1][2])                         # [0] EXPLICIT -> SignedData SEQUENCE
    parts = _children(der, s, e)
    certificates, signer_infos = [], None
    for tag, start, cstart, cend in parts[3:]:
        if tag == 0xA0:                                    # certificates [0] IMPLICIT
            for _, cs, _, ce in _children(der, cstart, cend):
                certificates.append(x509.load_der_x509_certificate(der[cs:ce]))
        elif tag == 0x31:
            signer_infos = (cstart, cend)
    if signer_infos is None:
        raise ValueError("ไม่มี SignerInfo")
    infos = _children(der, *signer_infos)
    _, _, s, e = infos[0]
    fields = _children(der, s, e)
    sid = _children(der, fields[1][2], fields[1][3])       # IssuerAndSerialNumber
    serial = int.from_bytes(der[sid[1][2]:sid[1][3]], "big", signed=True)
    digest_oid = _oid(der[_children(der, fields[2][2], fields[2][3])[0][2]:_children(der, fields[2][2], fields[2][3])[0][3]])
    position = 3
    signed_attrs_der, message_digest, signing_time = b"", b"", None
    if fields[3][0] == 0xA0:
        tag, start, cstart, cend = fields[3]
        signed_attrs_der = b"\x31" + der[start + 1:cend]   # เปลี่ยน [0] IMPLICIT เป็น SET ก่อนคำนวณ
        for _, _, as_, ae in _children(der, cstart, cend):
            attr = _children(der, as_, ae)
            oid = _oid(der[attr[0][2]:attr[0][3]])
            value = _children(der, attr[1][2], attr[1][3])[0]
            if oid == OID_MESSAGE_DIGEST:
                message_digest = bytes(der[value[2]:value[3]])
            elif oid == OID_SIGNING_TIME:
                signing_time = _parse_time(value[0], bytes(der[value[2]:value[3]]))
        position = 4
    signature = bytes(der[fields[position + 1][2]:fields[position + 1][3]])
    if digest_oid not in DIGESTS:
        raise ValueError("ไม่รองรับอัลกอริทึม hash นี้")
    return ParsedCMS(certificates, DIGESTS[digest_oid](), signed_attrs_der, message_digest, signing_time,
                     signature, serial)


def _parse_time(tag, raw):
    text = raw.decode()
    fmt = "%y%m%d%H%M%SZ" if tag == 0x17 else "%Y%m%d%H%M%SZ"
    try:
        return dt.datetime.strptime(text, fmt).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------- ตรวจสอบ
@dataclass
class SignatureCheck:
    field_name: str
    signer: str = ""
    signing_time: object = None
    reason: str = ""
    intact: bool = False            # hash ของช่วงที่ลงนามตรงกัน
    signature_valid: bool = False   # ลายมือชื่อถูกต้องตามกุญแจของใบรับรอง
    trusted: bool = False           # ใบรับรองออกโดย CA ที่ระบบเชื่อถือ และยังไม่หมดอายุ ณ เวลาลงนาม
    covers_whole_file: bool = False
    revision_end: int = 0
    certificate_fingerprint: str = ""
    problems: list = field(default_factory=list)

    @property
    def ok(self):
        return self.intact and self.signature_valid and self.trusted


def has_signatures(pdf):
    return SUBFILTER.encode() in pdf or b"/ETSI.CAdES.detached" in pdf


def verify_pdf(pdf, trusted_roots=()):
    if not has_signatures(pdf):
        return []
    reader = PdfReader(BytesIO(pdf))
    results = []
    for name, node in _walk_fields(reader):
        if node.get("/FT") != "/Sig" or node.get("/V") is None:
            continue
        value = node["/V"].get_object()
        results.append(_check_one(pdf, name, value, trusted_roots))
    results.sort(key=lambda r: r.revision_end)
    return results


def _check_one(pdf, name, value, trusted_roots):
    check = SignatureCheck(field_name=name, reason=str(value.get("/Reason", "")))
    try:
        a, b, c, d = (int(v) for v in value["/ByteRange"])
        contents = bytes(value["/Contents"])
        if a != 0 or b < 0 or c < b or c + d > len(pdf):
            raise ValueError("ByteRange ไม่ถูกต้อง")
        check.revision_end = c + d
        check.covers_whole_file = c + d == len(pdf)
        signed = pdf[a:a + b] + pdf[c:c + d]
        cms = parse_cms(contents)  # ความยาวใน DER บอกขอบเขตเอง ศูนย์ที่เติมท้ายจึงไม่มีผล
    except Exception as exc:  # ไฟล์จากภายนอกอาจผิดรูปแบบได้หลายแบบ
        check.problems.append(f"อ่านลายมือชื่อไม่ได้: {exc}")
        return check

    signer_cert = next((cert for cert in cms.certificates if cert.serial_number == cms.serial), None)
    if signer_cert is None:
        check.problems.append("ไม่พบใบรับรองของผู้ลงนามในลายมือชื่อ")
        return check
    from .pki import common_name, fingerprint

    check.signer = common_name(signer_cert)
    check.certificate_fingerprint = fingerprint(signer_cert)
    check.signing_time = cms.signing_time

    digest = hashes.Hash(cms.digest_algorithm)
    digest.update(signed)
    check.intact = digest.finalize() == cms.message_digest
    if not check.intact:
        check.problems.append("เนื้อหาที่ลงนามถูกแก้ไข (hash ไม่ตรง)")

    try:
        public_key = signer_cert.public_key()
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(cms.signature, cms.signed_attrs_der, ec.ECDSA(cms.digest_algorithm))
        else:
            public_key.verify(cms.signature, cms.signed_attrs_der, padding.PKCS1v15(), cms.digest_algorithm)
        check.signature_valid = True
    except (InvalidSignature, ValueError, TypeError):
        check.problems.append("ลายมือชื่อไม่ถูกต้องตามใบรับรอง")

    moment = cms.signing_time or dt.datetime.now(dt.timezone.utc)
    issuer = next((root for root in trusted_roots if root.subject == signer_cert.issuer), None)
    if issuer is None:
        check.problems.append("ใบรับรองไม่ได้ออกโดย CA ที่ระบบเชื่อถือ")
    else:
        try:
            signer_cert.verify_directly_issued_by(issuer)
            if not signer_cert.not_valid_before_utc <= moment <= signer_cert.not_valid_after_utc:
                check.problems.append("ใบรับรองไม่อยู่ในช่วงอายุ ณ เวลาลงนาม")
            else:
                check.trusted = True
        except (InvalidSignature, ValueError, TypeError):
            check.problems.append("ใบรับรองไม่ได้ออกโดย CA ที่ระบบเชื่อถือ")
    return check


def sha256(data):
    return hashlib.sha256(data).hexdigest()
