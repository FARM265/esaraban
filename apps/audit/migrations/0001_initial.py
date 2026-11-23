import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

TRIGGER = """
CREATE OR REPLACE FUNCTION audit_entry_append_only() RETURNS trigger AS $$
BEGIN
    -- ไม่ใช้เครื่องหมายเปอร์เซ็นต์ เพราะ psycopg ตีความเป็นตำแหน่งพารามิเตอร์
    RAISE EXCEPTION USING MESSAGE = 'audit log is append-only (' || TG_OP || ' not allowed)';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_entry_no_update ON audit_auditentry;
CREATE TRIGGER audit_entry_no_update BEFORE UPDATE OR DELETE ON audit_auditentry
    FOR EACH ROW EXECUTE FUNCTION audit_entry_append_only();
"""
DROP = """
DROP TRIGGER IF EXISTS audit_entry_no_update ON audit_auditentry;
DROP FUNCTION IF EXISTS audit_entry_append_only();
"""


def add_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(TRIGGER)


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP)


def create_head(apps, schema_editor):
    apps.get_model("audit", "AuditChainHead").objects.get_or_create(pk=1)


class Migration(migrations.Migration):

    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="AuditChainHead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_seq", models.BigIntegerField(default=0)),
                ("last_hash", models.CharField(default="0000000000000000000000000000000000000000000000000000000000000000", max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name="AuditEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("seq", models.BigIntegerField(editable=False, unique=True)),
                ("at", models.DateTimeField(db_index=True, editable=False)),
                ("actor_label", models.CharField(blank=True, max_length=200)),
                ("category", models.CharField(choices=[("AUTH", "เข้าสู่ระบบ"), ("USER", "ผู้ใช้และสิทธิ์"), ("DOCUMENT", "เอกสาร"), ("REGISTRY", "ทะเบียนเลข"), ("SETTINGS", "ตั้งค่าระบบ")], db_index=True, max_length=20)),
                ("action", models.CharField(db_index=True, max_length=40)),
                ("summary", models.CharField(max_length=500)),
                ("target_type", models.CharField(blank=True, max_length=40)),
                ("target_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("detail", models.JSONField(blank=True, default=dict)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("prev_hash", models.CharField(editable=False, max_length=64)),
                ("hash", models.CharField(editable=False, max_length=64, unique=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-seq"], "verbose_name": "รายการ Audit Log", "verbose_name_plural": "Audit Log"},
        ),
        migrations.RunPython(create_head, migrations.RunPython.noop),
        migrations.RunPython(add_trigger, drop_trigger),
    ]
