"""เส้นทางการเสนอเริ่มต้น ผู้ดูแลระบบแก้ไขหรือเพิ่มได้ที่เมนู "เส้นทางการเสนอ"

ขั้นที่ 1 (เจ้าหน้าที่สารบรรณลงรับและกดเริ่มเสนอ) ไม่ต้องอยู่ในเส้นทาง เพราะเป็นผู้เริ่มเรื่อง
ขั้นสุดท้ายต้องเป็นการสั่งการ ซึ่งผู้บริหารจะเลือกผู้รับผิดชอบในตอนนั้น
"""
from django.db import migrations

TEMPLATES = [
    (
        "มาตรฐาน: หนังสือรับทั่วไป",
        "INCOMING",
        [("HEAD", "OWNER", "REVIEW", 24), ("EXECUTIVE", "ANY", "COMMAND", 24)],
    ),
    (
        "เรื่องด่วน: เสนอผู้บริหารโดยตรง",
        "INCOMING",
        [("EXECUTIVE", "ANY", "COMMAND", 4)],
    ),
]


def seed(apps, schema_editor):
    Template = apps.get_model("workflow", "WorkflowTemplate")
    Step = apps.get_model("workflow", "WorkflowStep")
    for name, kind, steps in TEMPLATES:
        template, created = Template.objects.get_or_create(name=name, doc_kind=kind)
        if created:
            for order, (role, scope, step_kind, sla) in enumerate(steps, start=1):
                Step.objects.create(
                    template=template, order=order, role=role, scope=scope, kind=step_kind, sla_hours=sla
                )


class Migration(migrations.Migration):

    dependencies = [("workflow", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
