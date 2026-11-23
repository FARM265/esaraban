"""
สร้าง/ปรับสิทธิ์ผู้ใช้ฐานข้อมูลแบบจำกัดสิทธิ์ ที่ระบบใช้ขณะทำงานจริง (รันโดย entrypoint หลัง migrate ด้วยผู้ใช้เจ้าของฐานข้อมูล)

ผู้ใช้นี้ (POSTGRES_APP_USER):
- อ่าน/เพิ่ม/แก้/ลบข้อมูลได้ แต่สร้าง/ลบ/แก้โครงสร้างตารางไม่ได้ ไม่ใช่ superuser สร้างฐานข้อมูลหรือผู้ใช้อื่นไม่ได้
- แก้ไขหรือลบ Audit Log ไม่ได้ในระดับสิทธิ์ (นอกเหนือจาก trigger) และแก้ประวัติ migration ไม่ได้
รันซ้ำได้ทุกครั้ง (ตารางใหม่จาก migration จะได้สิทธิ์ตามไปด้วย)
"""
import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def statements(role, password, database):
    from psycopg import sql

    ident, db = sql.Identifier(role), sql.Identifier(database)
    return [
        sql.SQL(
            "DO $do$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {}) "
            "THEN CREATE ROLE {} LOGIN; END IF; END $do$"
        ).format(sql.Literal(role), ident),
        sql.SQL("ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}").format(
            ident, sql.Literal(password)
        ),
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db),
        sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(db, ident),
        sql.SQL("REVOKE CREATE ON SCHEMA public FROM PUBLIC"),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident),
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(ident),
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(ident),
        sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON audit_auditentry FROM {}").format(ident),
        sql.SQL("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON django_migrations FROM {}").format(ident),
    ]


class Command(BaseCommand):
    help = "สร้างหรือปรับสิทธิ์ผู้ใช้ฐานข้อมูลแบบจำกัดสิทธิ์ (POSTGRES_APP_USER) ต้องรันด้วยผู้ใช้เจ้าของฐานข้อมูล"

    def handle(self, *args, **options):
        role = os.environ.get("POSTGRES_APP_USER", "")
        password = os.environ.get("POSTGRES_APP_PASSWORD", "")
        database = connection.settings_dict["NAME"]
        if not role:
            self.stdout.write("POSTGRES_APP_USER ไม่ได้ตั้ง ข้ามขั้นตอนนี้ (ระบบใช้ผู้ใช้เจ้าของฐานข้อมูล)")
            return
        if not NAME.match(role) or role == connection.settings_dict["USER"]:
            raise CommandError("POSTGRES_APP_USER ต้องเป็นตัวพิมพ์เล็ก a-z ตัวเลข หรือ _ และต้องไม่ซ้ำกับ POSTGRES_USER")
        if len(password) < 16:
            raise CommandError("POSTGRES_APP_PASSWORD ต้องยาวอย่างน้อย 16 ตัวอักษร")
        with connection.cursor() as cursor:
            for statement in statements(role, password, database):
                cursor.execute(statement.as_string(cursor.connection))
        self.stdout.write(self.style.SUCCESS(f"ตั้งสิทธิ์ผู้ใช้ฐานข้อมูล {role} แล้ว"))
