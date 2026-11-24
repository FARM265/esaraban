"""
ค่าตั้งต้นที่ใช้ร่วมกันทุกสภาพแวดล้อม (dev / prod)
ค่าที่เป็นความลับทั้งหมดอ่านจาก Environment Variables หรือไฟล์ .env เท่านั้น
"""
from pathlib import Path

import environ
from django.contrib.messages import constants as message_constants
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    ORG_CODE=(str, "ปช XXXX"),
    PRIVATE_STORAGE_ROOT=(str, "private_storage"),
    SESSION_IDLE_MINUTES=(int, 30),
)
# อ่าน .env ถ้ามี (บน server จริงควรตั้ง environment variables ตรง ๆ แทน)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
# Render ตั้งชื่อโดเมนของบริการไว้ในตัวแปรนี้ให้อัตโนมัติ (เช่น esaraban.onrender.com)
RENDER_EXTERNAL_HOSTNAME = env.str("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, RENDER_EXTERNAL_HOSTNAME]

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.registry",
    "apps.documents",
    "apps.workflow",
    "apps.signatures",
    "apps.annotations",
    "apps.letters",
    "apps.archive",
    "apps.notifications",
    "apps.audit",
    "apps.reports",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

MIDDLEWARE = [
    "apps.core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # บนคลาวด์ที่ไม่มี nginx ให้ Django ส่งไฟล์ CSS/JS เอง (เปิดด้วย SERVE_STATIC=True)
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if env.bool("SERVE_STATIC", default=False) else []),
    "apps.core.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # ทุกหน้าต้องเข้าสู่ระบบ ยกเว้นหน้าที่ประกาศ @login_not_required (ปลอดภัยไว้ก่อน)
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.EnforceMFAMiddleware",
]

MESSAGE_TAGS = {message_constants.ERROR: "danger"}  # ให้ตรงกับ class alert-danger ของ Bootstrap

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site_context",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database (PostgreSQL เท่านั้น)
# --------------------------------------------------------------------------
# ใช้ DATABASE_URL ถ้ามี (เครื่องพัฒนา) หรือประกอบจาก POSTGRES_* (Docker)
# เพื่อให้ตั้งรหัสผ่านฐานข้อมูลไว้ที่เดียวในไฟล์ .env.docker
if env.str("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER"),
            "PASSWORD": env("POSTGRES_PASSWORD"),
            "HOST": env.str("POSTGRES_HOST", default="localhost"),
            "PORT": env.int("POSTGRES_PORT", default=5432),
        }
    }
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["CONN_MAX_AGE"] = 60

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# ผู้ใช้และรหัสผ่าน
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# MFA: ค่าว่าง = ใช้ SECRET_KEY สร้างกุญแจเข้ารหัส (ถ้าเปลี่ยน SECRET_KEY ผู้ใช้ต้องตั้ง MFA ใหม่)
MFA_ENCRYPTION_KEY = env.str("MFA_ENCRYPTION_KEY", default="")
MFA_ISSUER = "E-Saraban NACC CM"
# ขอรหัส 6 หลักจากแอป Authenticator ตอนเข้าสู่ระบบ ปิดไว้ตามที่ผู้ใช้ขอ (เข้าด้วยชื่อผู้ใช้และรหัสผ่านอย่างเดียว)
# ระบบเปิดบนอินเทอร์เน็ต ผู้รับผิดชอบควรพิจารณาเปิด (True) ถ้ามีข้อมูลสำคัญ เพื่อกันกรณีรหัสผ่านรั่ว
ESARABAN_LOGIN_REQUIRE_MFA = env.bool("ESARABAN_LOGIN_REQUIRE_MFA", default=False)

# ล็อกบัญชีชั่วคราว
LOGIN_LOCKOUT_MINUTES = env.int("LOGIN_LOCKOUT_MINUTES", default=15)
LOGIN_MAX_FAILURES = env.int("LOGIN_MAX_FAILURES", default=5)
LOGIN_MAX_FAILURES_PER_IP = env.int("LOGIN_MAX_FAILURES_PER_IP", default=20)
# เปิดเฉพาะเมื่ออยู่หลัง nginx ที่ตั้ง X-Real-IP (docker-compose.yml ตั้งให้แล้ว)
TRUST_PROXY_IP_HEADER = env.bool("TRUST_PROXY_IP_HEADER", default=False)
# header ที่ proxy ตั้ง IP จริงของผู้ใช้ (nginx ของระบบ: X-Real-IP)
PROXY_CLIENT_IP_HEADER = env.str("PROXY_CLIENT_IP_HEADER", default="X-Real-IP")
# ถ้าไม่มี header ข้างบน ใช้ X-Forwarded-For นับจากท้าย (1 = ตัวสุดท้าย) เพราะตัวหน้า ๆ ผู้ใช้ปลอมได้
PROXY_XFF_HOPS = env.int("PROXY_XFF_HOPS", default=0)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# ภาษาและเวลา
# --------------------------------------------------------------------------
LANGUAGE_CODE = "th"
LANGUAGES = [("th", "ไทย"), ("en", "English")]
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static files (CSS/JS/ฟอนต์ เก็บในเครื่อง ไม่พึ่ง CDN)
# --------------------------------------------------------------------------
# ที่เก็บไฟล์เอกสาร: "local" = ดิสก์ของเครื่อง, "s3" = Supabase Storage หรือที่เก็บแบบ S3 อื่น (ดู docs/cloud-render-supabase.md)
ESARABAN_STORAGE_BACKEND = env.str("ESARABAN_STORAGE_BACKEND", default="local")
S3_ENDPOINT_URL = env.str("S3_ENDPOINT_URL", default="")
S3_REGION = env.str("S3_REGION", default="ap-southeast-1")
S3_BUCKET = env.str("S3_BUCKET", default="")
S3_ACCESS_KEY_ID = env.str("S3_ACCESS_KEY_ID", default="")
S3_SECRET_ACCESS_KEY = env.str("S3_SECRET_ACCESS_KEY", default="")
if ESARABAN_STORAGE_BACKEND not in ("local", "s3"):
    raise ImproperlyConfigured("ESARABAN_STORAGE_BACKEND ต้องเป็น local หรือ s3")
if ESARABAN_STORAGE_BACKEND == "s3" and not all((S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY)):
    raise ImproperlyConfigured("ใช้ที่เก็บไฟล์ s3 ต้องตั้ง S3_ENDPOINT_URL S3_BUCKET S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY")

STATIC_URL = "static/"
if env.bool("SERVE_STATIC", default=False):
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# --------------------------------------------------------------------------
# ไฟล์เอกสาร: เก็บแบบ private ไม่มี MEDIA_URL สาธารณะ
# ทุกการดาวน์โหลดต้องผ่าน view ที่ตรวจสิทธิ์และบันทึก Audit Log (ขั้นตอนที่ 6)
# --------------------------------------------------------------------------
PRIVATE_STORAGE_ROOT = BASE_DIR / env("PRIVATE_STORAGE_ROOT")
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
ESARABAN_MAX_UPLOAD_BYTES = 20 * 1024 * 1024        # ต่อไฟล์
ESARABAN_MAX_TOTAL_UPLOAD_BYTES = 50 * 1024 * 1024  # ต่อการลงทะเบียน 1 ครั้ง (nginx ตั้งไว้ 60 MB)
ESARABAN_MAX_FILES_PER_UPLOAD = 10
# กุญแจเข้ารหัสไฟล์ ค่าว่าง = สร้างจาก SECRET_KEY (ต้องสำรองไว้คู่กับข้อมูลสำรองเสมอ)
FILE_ENCRYPTION_KEY = env.str("FILE_ENCRYPTION_KEY", default="")
# ชั้น "ลับที่สุด" ปิดไว้จนกว่าผู้รับผิดชอบจะยืนยันว่าอนุญาตให้เก็บในระบบอิเล็กทรอนิกส์
ESARABAN_ALLOW_TOP_SECRET = env.bool("ALLOW_TOP_SECRET", default=False)
# ฟอนต์สำหรับฝังข้อความสั่งการ/เกษียนลงใน PDF (ดาวน์โหลดพร้อม Bootstrap ด้วย scripts/download_vendor)
ESARABAN_TEXT_FONT = BASE_DIR / "static" / "vendor" / "sarabun" / "Sarabun-Regular.ttf"
ESARABAN_TEXT_FONT_BOLD = BASE_DIR / "static" / "vendor" / "sarabun" / "Sarabun-Bold.ttf"
# ลายมือชื่อดิจิทัลด้วยใบรับรองทดสอบที่ระบบสร้างเอง (ไม่มีผลทางกฎหมาย) ปิดได้ถ้าไม่ต้องการให้เลือก
ESARABAN_DIGITAL_SIGNING = env.bool("ESARABAN_DIGITAL_SIGNING", default=True)
# ขอรหัส 6 หลักจากแอปก่อนลงนามทุกครั้ง ปิดไว้ตามที่ผู้ใช้ขอในช่วงทดลอง (ยังต้องเข้าสู่ระบบด้วย MFA ตามปกติ)
# ผู้รับผิดชอบควรพิจารณาเปิด (True) ก่อนใช้งานจริง เพื่อยืนยันว่าผู้ลงนามเป็นเจ้าของบัญชีจริง ณ ขณะลงนาม
ESARABAN_SIGN_REQUIRE_OTP = env.bool("ESARABAN_SIGN_REQUIRE_OTP", default=False)
# ---------------------------------------------------------------------------
# แจ้งเตือนนอกระบบ (อีเมล / LINE) ผู้ใช้เลือกเปิดเองที่ "ตั้งค่าการแจ้งเตือน" ค่าลับทั้งหมดมาจาก Environment Variables
# ---------------------------------------------------------------------------
# ที่อยู่เว็บของระบบ ใช้ทำลิงก์ในข้อความแจ้งเตือน (บน Render ใช้ RENDER_EXTERNAL_URL อัตโนมัติ)
ESARABAN_SITE_URL = env.str("ESARABAN_SITE_URL", default="") or env.str("RENDER_EXTERNAL_URL", default="")
# อีเมล: none = ปิด, smtp = ส่งผ่าน SMTP (เช่น Gmail ในเครื่องสำนักงาน), brevo = ส่งผ่าน Brevo API (ใช้บน Render ฟรี
# เพราะ Render แผนฟรีปิดพอร์ต SMTP)
NOTIFY_EMAIL_BACKEND = env.str("NOTIFY_EMAIL_BACKEND", default="none")
NOTIFY_EMAIL_FROM = env.str("NOTIFY_EMAIL_FROM", default="")
NOTIFY_EMAIL_FROM_NAME = env.str("NOTIFY_EMAIL_FROM_NAME", default="E-Saraban")
BREVO_API_KEY = env.str("BREVO_API_KEY", default="")
EMAIL_HOST = env.str("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_TIMEOUT = 15
# LINE Official Account (Messaging API) ว่าง = ปิดการแจ้งเตือนทาง LINE
LINE_CHANNEL_ACCESS_TOKEN = env.str("LINE_CHANNEL_ACCESS_TOKEN", default="")
LINE_CHANNEL_SECRET = env.str("LINE_CHANNEL_SECRET", default="")
LINE_OA_ID = env.str("LINE_OA_ID", default="")  # Basic ID ของบัญชี เช่น @123abcde
# แจ้ง "หนังสือเข้าใหม่" เมื่อลงทะเบียนรับ ให้ผู้มีบทบาทเหล่านี้ที่ดูแลกลุ่มงานเจ้าของเรื่อง (ว่าง = ไม่แจ้ง)
ESARABAN_NOTIFY_INCOMING_ROLES = env.str("ESARABAN_NOTIFY_INCOMING_ROLES", default="HEAD,EXECUTIVE")
# ส่งแจ้งเตือนนอกระบบใน thread แยก หน้าเว็บจึงไม่ต้องรอ (ปิดในเทสต์)
NOTIFY_ASYNC = env.bool("NOTIFY_ASYNC", default=True)

# ชื่อไฟล์ยืนยันเจ้าของเว็บจาก Google Search Console (วิธี "ไฟล์ HTML") เช่น google1234abcd5678ef90.html
GOOGLE_SITE_VERIFICATION_FILE = env.str("GOOGLE_SITE_VERIFICATION_FILE", default="")

# อ่านข้อความจากหนังสือที่เป็นภาพสแกน (OCR ด้วย tesseract ภาษาไทย ติดตั้งใน Docker image) สำหรับลงปฏิทิน
ESARABAN_OCR_ENABLED = env.bool("ESARABAN_OCR_ENABLED", default=True)
ESARABAN_OCR_MAX_PAGES = 2
FILE_UPLOAD_PERMISSIONS = 0o640

# --------------------------------------------------------------------------
# Session และความปลอดภัยพื้นฐาน
# --------------------------------------------------------------------------
SESSION_IDLE_MINUTES = env("SESSION_IDLE_MINUTES")
SESSION_COOKIE_AGE = SESSION_IDLE_MINUTES * 60
SESSION_SAVE_EVERY_REQUEST = True  # นับเวลาหมดอายุใหม่ทุกครั้งที่ใช้งาน
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
# ตั้งเป็น True ชั่วคราวถ้าหน้าใดใช้งานไม่ได้เพราะ Content-Security-Policy (เบราว์เซอร์จะเตือนใน console แทนการบล็อก)
ESARABAN_CSP_REPORT_ONLY = env.bool("ESARABAN_CSP_REPORT_ONLY", default=False)

# --------------------------------------------------------------------------
# ค่าเฉพาะของระบบสารบรรณ
# --------------------------------------------------------------------------
ESARABAN_ORG_CODE = env("ORG_CODE")
ESARABAN_ORG_NAME = "สำนักงาน ป.ป.ช. ประจำจังหวัดเชียงใหม่"
# หน่วยงานย่อยที่แสดงใต้ชื่อสำนักงาน (หน้าเข้าสู่ระบบและเมนูด้านซ้าย) เว้นว่างได้
ESARABAN_ORG_UNIT = env.str("ESARABAN_ORG_UNIT", default="กลุ่มงานป้องกันการทุจริต")
ESARABAN_IS_TEST_SYSTEM = True  # แสดงแถบ "ระบบทดลอง" บนทุกหน้า

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
