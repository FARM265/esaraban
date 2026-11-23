"""เส้นทางเสนอร่างหนังสือที่สร้างจากแม่แบบ: หัวหน้ากลุ่มงานตรวจ แล้วผู้บริหารพิจารณาสั่งการ/ลงนาม"""
from django.db import migrations

KINDS = [
    ("OUTGOING", "หนังสือภายนอก"),
    ("INTERNAL", "บันทึกข้อความ"),
    ("ORDER", "คำสั่ง"),
    ("ANNOUNCE", "ประกาศ"),
]
STEPS = [("HEAD", "OWNER", "REVIEW", 24), ("EXECUTIVE", "ANY", "COMMAND", 24)]


def seed(apps, schema_editor):
    Template = apps.get_model("workflow", "WorkflowTemplate")
    Step = apps.get_model("workflow", "WorkflowStep")
    for kind, label in KINDS:
        template, created = Template.objects.get_or_create(name=f"มาตรฐาน: เสนอลงนาม{label}", doc_kind=kind)
        if created:
            for order, (role, scope, step_kind, sla) in enumerate(STEPS, start=1):
                Step.objects.create(
                    template=template, order=order, role=role, scope=scope, kind=step_kind, sla_hours=sla
                )


class Migration(migrations.Migration):

    dependencies = [("workflow", "0002_seed_templates")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
