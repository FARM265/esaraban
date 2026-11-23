"""การตั้งค่าสำหรับรันบนคลาวด์: ที่เก็บไฟล์ S3 และ IP ของผู้ใช้หลัง proxy (ไม่เชื่อมต่อบริการจริง)"""
import io
from unittest import mock

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts.security import client_ip
from apps.documents import storage

S3 = dict(
    ESARABAN_STORAGE_BACKEND="s3", S3_ENDPOINT_URL="https://example.invalid/storage/v1/s3", S3_REGION="ap-southeast-1",
    S3_BUCKET="esaraban-files", S3_ACCESS_KEY_ID="test", S3_SECRET_ACCESS_KEY="test",
)


class FakeS3:
    """แทน boto3 client ด้วยที่เก็บในหน่วยความจำ"""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop((Bucket, Key), None)


@override_settings(**S3)
class S3StorageTests(SimpleTestCase):
    def setUp(self):
        self.fake = FakeS3()
        patcher = mock.patch.object(storage, "_s3", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_files_are_encrypted_before_upload_and_roundtrip(self):
        data = b"%PDF-1.4 test document"
        key, digest = storage.save_encrypted(data)
        uploaded = self.fake.objects[("esaraban-files", key)]
        self.assertNotIn(b"%PDF", uploaded)  # ผู้ให้บริการที่เก็บไฟล์เห็นแต่ข้อมูลที่เข้ารหัสแล้ว
        self.assertEqual(storage.read_decrypted(key, digest), data)

    def test_tampered_object_detected(self):
        key, _ = storage.save_encrypted(b"original")
        with self.assertRaises(ValueError):
            storage.read_decrypted(key, "0" * 64)

    def test_bad_keys_rejected(self):
        for key in ("../secret", "other/file.bin", "documents/../../x"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                storage.read_decrypted(key)

    def test_probe_and_cleanup(self):
        self.assertIn("esaraban-files", storage.probe())
        self.assertEqual(self.fake.objects, {})  # ไฟล์ทดสอบถูกลบแล้ว


class ProxyClientIPTests(SimpleTestCase):
    def request(self, **meta):
        return RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", **meta)

    @override_settings(TRUST_PROXY_IP_HEADER=False)
    def test_headers_ignored_when_not_behind_proxy(self):
        req = self.request(HTTP_X_REAL_IP="1.2.3.4", HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(client_ip(req), "10.0.0.1")

    @override_settings(TRUST_PROXY_IP_HEADER=True, PROXY_CLIENT_IP_HEADER="True-Client-IP", PROXY_XFF_HOPS=2)
    def test_cloud_proxy_header_then_forwarded_for(self):
        self.assertEqual(client_ip(self.request(HTTP_TRUE_CLIENT_IP="203.0.113.7")), "203.0.113.7")
        # ไม่มี header: ใช้ X-Forwarded-For ตัวที่ 2 จากท้าย ตัวแรกสุดผู้ใช้ปลอมมาได้
        req = self.request(HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.8, 10.1.1.1")
        self.assertEqual(client_ip(req), "203.0.113.8")
        self.assertEqual(client_ip(self.request(HTTP_TRUE_CLIENT_IP="not-an-ip")), "10.0.0.1")

    @override_settings(TRUST_PROXY_IP_HEADER=True, PROXY_CLIENT_IP_HEADER="none", PROXY_XFF_HOPS=2)
    def test_render_settings_ignore_spoofable_headers(self):
        req = self.request(HTTP_X_REAL_IP="6.6.6.6", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.9, 10.1.1.1")
        self.assertEqual(client_ip(req), "203.0.113.9")
