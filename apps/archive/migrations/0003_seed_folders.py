from django.db import migrations


def seed(apps, schema_editor):
    """หมวดที่เคยพิมพ์ไว้ตอนจัดเก็บ ให้ขึ้นเป็นตัวเลือกด้วย"""
    ArchiveRecord = apps.get_model("archive", "ArchiveRecord")
    ArchiveFolder = apps.get_model("archive", "ArchiveFolder")
    for name in set(ArchiveRecord.objects.values_list("folder", flat=True)):
        name = " ".join((name or "").split())[:200]
        if name:
            ArchiveFolder.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [("archive", "0002_archive_folder")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
