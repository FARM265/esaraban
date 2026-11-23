"""
ใบรับรองทดสอบสำหรับลายมือชื่อดิจิทัล (ไม่มีผลทางกฎหมาย)

ระบบสร้าง CA ทดสอบของตนเอง แล้วออกใบรับรองให้ผู้ลงนามแต่ละคน ใช้สาธิตการลงนาม/ตรวจสอบเท่านั้น
ใช้งานจริงต้องใช้ใบรับรองจากผู้ให้บริการออกใบรับรองที่ได้รับอนุญาต (เช่น ตามกฎหมายว่าด้วยธุรกรรมทางอิเล็กทรอนิกส์)
ไม่ import Django จึงทดสอบแยกได้
"""
import datetime as dt

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

TEST_LABEL = "ใบรับรองทดสอบ ไม่มีผลทางกฎหมาย"
ORG = "E-Saraban ระบบทดลอง"
CA_YEARS = 10
USER_DAYS = 365


def _fit(text, limit=64):
    """ชื่อใน X.509 จำกัด 64 ไบต์ (UTF-8) อักษรไทยใช้ 3 ไบต์ จึงตัดตามไบต์โดยไม่ตัดกลางตัวอักษร"""
    text = (text or "").strip() or "-"
    while len(text.encode("utf-8")) > limit:
        text = text[:-1]
    return text


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def key_to_pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def key_from_pem(data):
    return serialization.load_pem_private_key(data, password=None)


def cert_to_pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def cert_from_pem(data):
    return x509.load_pem_x509_certificate(data)


def create_ca(org_name):
    key = _key()
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "E-Saraban TEST CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, _fit(ORG)),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "ไม่มีผลทางกฎหมาย"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, _fit(org_name)),
    ])
    now = _now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365 * CA_YEARS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def issue_user_certificate(ca_key, ca_cert, *, common_name, email="", unit=""):
    key = _key()
    attrs = [
        x509.NameAttribute(NameOID.COMMON_NAME, _fit(common_name)),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, _fit(ORG)),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, _fit(unit or "ไม่มีผลทางกฎหมาย")),
    ]
    if email:
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    now = _now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name(attrs)).issuer_name(ca_cert.subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(min(now + dt.timedelta(days=USER_DAYS), ca_cert.not_valid_after_utc))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def fingerprint(cert):
    return cert.fingerprint(hashes.SHA256()).hex()


def common_name(cert):
    values = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    return values[0].value if values else ""
