"""ข้อมูลแผง "หนังสือจากแม่แบบ" ในหน้ารายละเอียดเอกสาร"""
from . import services
from .forms import IssueForm
from .models import LetterContent


def context_for(user, document):
    letter = LetterContent.objects.filter(pk=document.pk).first()
    if letter is None:
        return {"letter": None}
    can_issue = services.can_issue(user, document)
    books = services.books_for(document) if can_issue else None
    return {
        "letter": letter,
        "letter_can_revise": services.can_revise(user, document),
        "letter_issue_form": IssueForm(books=books) if can_issue and books.exists() else None,
        "letter_issue_no_book": can_issue and not books.exists(),
    }
