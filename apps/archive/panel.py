"""แผง "คลังเอกสาร" ในหน้ารายละเอียดเอกสาร"""
from . import services
from .forms import ArchiveForm, ReleaseForm


def context_for(user, document):
    can_archive = services.can_archive(user, document)
    can_release = services.can_release(user, document)
    return {
        "archive_record": services.active_record(document) if document.status == "ARCHIVED" else None,
        "archive_form": ArchiveForm() if can_archive else None,
        "archive_folders": services.folders() if can_archive else [],
        "release_form": ReleaseForm() if can_release else None,
    }
