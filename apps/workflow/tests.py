import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, UserRole
from apps.accounts.testing import login_verified, make_admin, make_user
from apps.core.constants import RoleCode, SecrecyLevel
from apps.documents import access
from apps.documents.models import DocumentEvent, DocumentStatus
from apps.documents.services import register_incoming
from apps.registry.models import RegisterBook

from . import services
from .models import Decision, InstanceStatus, StepKind, TaskKind, TaskStatus, WorkflowStep, WorkflowTemplate

TMP_STORAGE = Path(tempfile.mkdtemp(prefix="esaraban-wf-"))
PDF = b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\n%%EOF\n"


def tearDownModule():
    shutil.rmtree(TMP_STORAGE, ignore_errors=True)


@override_settings(PRIVATE_STORAGE_ROOT=TMP_STORAGE)
class WorkflowTestBase(TestCase):
    def setUp(self):
        self.dept_a = Department.objects.create(code="A", name_th="กลุ่มงาน A")
        self.dept_a1 = Department.objects.create(code="A1", name_th="กลุ่มงาน A1", parent=self.dept_a)
        self.dept_b = Department.objects.create(code="B", name_th="กลุ่มงาน B")
        self.clerk = make_user("clerk", roles=[RoleCode.CLERK], clearance_level=SecrecyLevel.SECRET)
        self.head_a = make_user("head_a", roles=[(RoleCode.HEAD, self.dept_a)], clearance_level=SecrecyLevel.SECRET)
        self.head_b = make_user("head_b", roles=[(RoleCode.HEAD, self.dept_b)], clearance_level=SecrecyLevel.SECRET)
        self.exe = make_user("exe", roles=[RoleCode.EXECUTIVE], clearance_level=SecrecyLevel.SECRET)
        self.staff_a1 = make_user("staff_a1", roles=[RoleCode.STAFF], department=self.dept_a1)
        self.staff_b = make_user("staff_b", roles=[RoleCode.STAFF], department=self.dept_b)
        self.template = WorkflowTemplate.objects.get(name="มาตรฐาน: หนังสือรับทั่วไป")
        self.doc = self.make_doc()

    def make_doc(self, dept="default", secrecy=SecrecyLevel.NORMAL):
        return register_incoming(
            book=RegisterBook.objects.get(code="RCV"),
            data={"subject": "เรื่องทดสอบ workflow", "source_doc_no": "x", "source_org": "y",
                  "secrecy": secrecy, "owner_department": self.dept_a1 if dept == "default" else dept},
            main_file=("main.pdf", PDF, 1), extra_files=[], user=self.clerk,
        )

    def start(self, doc=None):
        return services.start_workflow(doc or self.doc, self.template, self.clerk)

    def open_task(self, doc=None):
        return services.running_instance(doc or self.doc).tasks.get(status=TaskStatus.OPEN)

    def refresh(self):
        self.doc.refresh_from_db()
        return self.doc


class FlowTests(WorkflowTestBase):
    def test_full_flow_to_done(self):
        self.start()
        self.assertEqual(self.refresh().status, DocumentStatus.IN_REVIEW)

        task = self.open_task()
        self.assertEqual(task.kind, TaskKind.REVIEW)
        self.assertIn(task, services.actionable_tasks(self.head_a))
        self.assertNotIn(task, services.actionable_tasks(self.staff_a1))
        services.act(task, self.head_a, Decision.FORWARD, comment="เห็นควรเสนอ")

        task = self.open_task()
        self.assertEqual(task.kind, TaskKind.COMMAND)
        services.act(task, self.exe, Decision.COMMAND, command_text="มอบดำเนินการ",
                     assignees=[self.staff_a1, self.staff_b], due_date=timezone.localdate() + timedelta(days=3))
        self.assertEqual(self.refresh().status, DocumentStatus.COMMANDED)
        self.assertEqual(self.doc.due_date, timezone.localdate() + timedelta(days=3))

        act_a1 = services.actionable_tasks(self.staff_a1).get()
        services.act(act_a1, self.staff_a1, Decision.COMPLETE, comment="ส่งข้อมูลแล้ว")
        self.assertEqual(self.refresh().status, DocumentStatus.IN_PROGRESS)
        act_b = services.actionable_tasks(self.staff_b).get()
        services.act(act_b, self.staff_b, Decision.COMPLETE)
        self.assertEqual(self.refresh().status, DocumentStatus.DONE)
        self.assertEqual(self.doc.workflows.get().status, InstanceStatus.DONE)

        actions = set(self.doc.events.values_list("action", flat=True))
        for expected in ["WF_STARTED", "WF_FORWARD", "WF_COMMAND", "WF_COMPLETE"]:
            self.assertIn(expected, actions)

    def test_head_of_other_department_cannot_act(self):
        self.start()
        task = self.open_task()
        self.assertEqual(services.can_act(self.head_b, task), (False, None))
        with self.assertRaises(PermissionDenied):
            services.act(task, self.head_b, Decision.FORWARD)

    def test_return_chain_and_resubmit(self):
        self.start()
        services.act(self.open_task(), self.head_a, Decision.FORWARD)
        services.act(self.open_task(), self.exe, Decision.RETURN, comment="ขอข้อมูลเพิ่ม")
        task = self.open_task()
        self.assertEqual((task.kind, task.step_index), (TaskKind.REVIEW, 0))
        self.assertEqual(self.refresh().status, DocumentStatus.RETURNED)

        services.act(task, self.head_a, Decision.RETURN, comment="แก้ชื่อเรื่อง")
        revise = self.open_task()
        self.assertEqual((revise.kind, revise.assignee), (TaskKind.REVISE, self.clerk))

        services.act(revise, self.clerk, Decision.RESUBMIT, comment="แก้แล้ว")
        self.assertEqual(self.open_task().step_index, 0)
        self.assertEqual(self.refresh().status, DocumentStatus.IN_REVIEW)

    def test_return_requires_reason(self):
        self.start()
        with self.assertRaises(ValidationError):
            services.act(self.open_task(), self.head_a, Decision.RETURN, comment="  ")

    def test_command_without_assignees_finishes(self):
        self.start()
        services.act(self.open_task(), self.head_a, Decision.FORWARD)
        services.act(self.open_task(), self.exe, Decision.COMMAND, command_text="ทราบ เก็บเข้าแฟ้ม")
        self.assertEqual(self.refresh().status, DocumentStatus.DONE)

    def test_command_text_required(self):
        self.start()
        services.act(self.open_task(), self.head_a, Decision.FORWARD)
        with self.assertRaises(ValidationError):
            services.act(self.open_task(), self.exe, Decision.COMMAND, command_text="")

    def test_wrong_decision_for_task_rejected(self):
        self.start()
        with self.assertRaises(ValidationError):
            services.act(self.open_task(), self.head_a, Decision.COMMAND, command_text="x")

    def test_task_cannot_be_acted_twice(self):
        self.start()
        task = self.open_task()
        services.act(task, self.head_a, Decision.FORWARD)
        with self.assertRaises(ValidationError):
            services.act(task, self.head_a, Decision.FORWARD)

    def test_cancel_from_revise_returns_to_registered(self):
        self.start()
        services.act(self.open_task(), self.head_a, Decision.RETURN, comment="ไม่เกี่ยวกับกลุ่มงาน")
        services.act(self.open_task(), self.clerk, Decision.CANCEL, comment="ส่งผิดกลุ่มงาน")
        self.assertEqual(self.refresh().status, DocumentStatus.REGISTERED)
        self.start()  # เสนอใหม่ได้
        self.assertEqual(self.doc.workflows.count(), 2)


class AssignTests(WorkflowTestBase):
    """ผู้บริหารสั่งการมอบหัวหน้ากลุ่มงาน แล้วหัวหน้ากลุ่มงานมอบต่อให้บุคลากร"""

    def command_to_head(self):
        self.start()
        services.act(self.open_task(), self.head_a, Decision.FORWARD)
        services.act(self.open_task(), self.exe, Decision.COMMAND, command_text="มอบกลุ่มงาน A ดำเนินการ",
                     assignees=[self.head_a], due_date=timezone.localdate() + timedelta(days=5))
        return self.open_task()

    def test_head_assigns_staff_and_command_carries_over(self):
        head_task = self.command_to_head()
        self.assertTrue(services.can_assign(self.head_a, head_task))
        services.act(head_task, self.head_a, Decision.ASSIGN, command_text="ทำรายงานส่งภายในวันศุกร์",
                     assignees=[self.staff_a1])
        head_task.refresh_from_db()
        self.assertEqual(head_task.decision, Decision.ASSIGN)
        self.assertIn("มอบให้", head_task.comment)
        staff_task = self.open_task()
        self.assertEqual(staff_task.assignee, self.staff_a1)
        self.assertIn("มอบกลุ่มงาน A ดำเนินการ", staff_task.command_text)
        self.assertIn("ทำรายงานส่งภายในวันศุกร์", staff_task.command_text)
        self.assertEqual(staff_task.due_at, head_task.due_at)  # ไม่ระบุกำหนดใหม่ ใช้กำหนดเดิม
        self.assertEqual(self.refresh().status, DocumentStatus.COMMANDED)
        self.assertTrue(self.staff_a1.notifications.filter(title="ได้รับมอบหมายให้ดำเนินการ").exists())
        self.assertTrue(self.doc.events.filter(action=DocumentEvent.Action.ASSIGNED).exists())

        services.act(staff_task, self.staff_a1, Decision.COMPLETE, comment="ส่งรายงานแล้ว")
        self.assertEqual(self.refresh().status, DocumentStatus.DONE)

    def test_staff_cannot_assign(self):
        self.start()
        services.act(self.open_task(), self.head_a, Decision.FORWARD)
        services.act(self.open_task(), self.exe, Decision.COMMAND, command_text="ดำเนินการ", assignees=[self.staff_a1])
        task = self.open_task()
        self.assertFalse(services.can_assign(self.staff_a1, task))
        with self.assertRaises(PermissionDenied):
            services.act(task, self.staff_a1, Decision.ASSIGN, assignees=[self.staff_b])

    def test_head_of_other_department_cannot_assign(self):
        self.start()
        services.act(self.open_task(), self.head_a, Decision.FORWARD)
        services.act(self.open_task(), self.exe, Decision.COMMAND, command_text="ดำเนินการ", assignees=[self.head_b])
        task = self.open_task()
        self.assertFalse(services.can_assign(self.head_b, task))  # เรื่องของกลุ่มงาน A1

    def test_assign_needs_someone(self):
        head_task = self.command_to_head()
        with self.assertRaises(ValidationError):
            services.act(head_task, self.head_a, Decision.ASSIGN, assignees=[])

    def test_assign_through_page(self):
        head_task = self.command_to_head()
        login_verified(self.client, self.head_a)
        page = self.client.get(reverse("documents:detail", args=[self.doc.pk]))
        self.assertContains(page, "มอบให้บุคลากรดำเนินการ")
        self.assertContains(page, f'name="assignees" value="{self.staff_a1.pk}"')
        response = self.client.post(reverse("workflow:act", args=[head_task.pk]),
                                    {"decision": "ASSIGN", "assignees": [self.staff_a1.pk, self.staff_b.pk]})
        self.assertRedirects(response, reverse("documents:detail", args=[self.doc.pk]), fetch_redirect_response=False)
        self.assertEqual(
            set(services.running_instance(self.doc).tasks.filter(status=TaskStatus.OPEN).values_list("assignee", flat=True)),
            {self.staff_a1.pk, self.staff_b.pk},
        )
        self.client.logout()
        login_verified(self.client, self.staff_a1)
        self.assertNotContains(self.client.get(reverse("documents:detail", args=[self.doc.pk])), "มอบให้บุคลากรดำเนินการ")


class StartTests(WorkflowTestBase):
    def test_cannot_start_twice(self):
        self.start()
        with self.assertRaises(ValidationError):
            self.start()

    def test_owner_department_required(self):
        doc = self.make_doc(dept=None)
        with self.assertRaises(ValidationError):
            self.start(doc)

    def test_refuses_when_nobody_can_receive(self):
        UserRole.objects.filter(user=self.head_a).delete()
        with self.assertRaisesMessage(ValidationError, "หัวหน้ากลุ่มงาน"):
            self.start()

    def test_secret_document_needs_cleared_reviewers(self):
        doc = self.make_doc(secrecy=SecrecyLevel.SECRET)
        self.head_a.clearance_level = SecrecyLevel.NORMAL
        self.head_a.save()
        with self.assertRaises(ValidationError):
            self.start(doc)

    def test_template_changes_do_not_affect_running(self):
        instance = self.start()
        WorkflowStep.objects.filter(template=self.template).delete()
        WorkflowStep.objects.create(template=self.template, order=1, role=RoleCode.EXECUTIVE, scope="ANY", kind=StepKind.COMMAND)
        services.act(self.open_task(), self.head_a, Decision.FORWARD)
        instance.refresh_from_db()
        self.assertEqual(len(instance.steps), 2)


class VisibilityTests(WorkflowTestBase):
    def test_assignee_from_other_department_can_view(self):
        self.assertFalse(access.can_view(self.staff_b, self.doc))
        self.start()
        services.act(self.open_task(), self.head_a, Decision.FORWARD)
        services.act(self.open_task(), self.exe, Decision.COMMAND, command_text="x", assignees=[self.staff_b])
        self.assertTrue(access.can_view(self.staff_b, self.doc))

    def test_cannot_assign_user_without_clearance(self):
        doc = self.make_doc(secrecy=SecrecyLevel.CONFIDENTIAL)
        self.start(doc)
        services.act(self.open_task(doc), self.head_a, Decision.FORWARD)
        with self.assertRaises(ValidationError):
            services.act(self.open_task(doc), self.exe, Decision.COMMAND, command_text="x", assignees=[self.staff_a1])


class DelegationTests(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.deputy = make_user("deputy", clearance_level=SecrecyLevel.SECRET)
        self.start()
        services.act(self.open_task(), self.head_a, Decision.FORWARD)

    def test_delegate_acts_on_behalf(self):
        today = timezone.localdate()
        services.create_delegation(delegator=self.exe, delegate=self.deputy, start_date=today, end_date=today,
                                   reason="ไปราชการ", created_by=self.exe)
        task = self.open_task()
        self.assertEqual(services.can_act(self.deputy, task), (True, self.exe))
        self.assertTrue(access.can_view(self.deputy, self.doc))
        services.act(task, self.deputy, Decision.COMMAND, command_text="ทราบ")
        task.refresh_from_db()
        self.assertEqual((task.acted_by, task.on_behalf_of), (self.deputy, self.exe))

    def test_expired_or_revoked_delegation_has_no_effect(self):
        today = timezone.localdate()
        old = services.create_delegation(delegator=self.exe, delegate=self.deputy, start_date=today - timedelta(days=5),
                                         end_date=today - timedelta(days=1), reason="เก่า", created_by=self.exe)
        self.assertFalse(services.can_act(self.deputy, self.open_task())[0])
        current = services.create_delegation(delegator=self.exe, delegate=self.deputy, start_date=today,
                                             end_date=today, reason="ใหม่", created_by=self.exe)
        services.revoke_delegation(current, self.exe)
        self.assertFalse(services.can_act(self.deputy, self.open_task())[0])
        self.assertIsNotNone(old)

    def test_delegate_needs_own_clearance(self):
        doc = self.make_doc(secrecy=SecrecyLevel.SECRET)
        services.start_workflow(doc, self.template, self.clerk)
        services.act(self.open_task(doc), self.head_a, Decision.FORWARD)
        low = make_user("low")
        today = timezone.localdate()
        services.create_delegation(delegator=self.exe, delegate=low, start_date=today, end_date=today,
                                   reason="x", created_by=self.exe)
        self.assertFalse(services.can_act(low, self.open_task(doc))[0])

    def test_cannot_delegate_to_self(self):
        today = timezone.localdate()
        with self.assertRaises(ValidationError):
            services.create_delegation(delegator=self.exe, delegate=self.exe, start_date=today, end_date=today,
                                       reason="x", created_by=self.exe)


class ViewTests(WorkflowTestBase):
    def test_start_and_act_through_pages(self):
        login_verified(self.client, self.clerk)
        page = self.client.get(reverse("documents:detail", args=[self.doc.pk]))
        self.assertContains(page, "เริ่มเสนอ")
        self.client.post(reverse("workflow:start", args=[self.doc.pk]), {"template": self.template.pk, "comment": ""})
        self.assertEqual(self.refresh().status, DocumentStatus.IN_REVIEW)

        self.client.logout()
        login_verified(self.client, self.head_a)
        tasks_page = self.client.get(reverse("workflow:my_tasks"))
        self.assertContains(tasks_page, self.doc.registration.display_no)
        # จำนวนงานท้ายเมนู "งานรอดำเนินการ" และรายการงานในหน้าหลัก
        self.assertContains(tasks_page, '<span class="nav-badge"')
        home = self.client.get(reverse("core:home"))
        self.assertContains(home, self.doc.subject)
        detail = self.client.get(reverse("documents:detail", args=[self.doc.pk]))
        self.assertContains(detail, "เสนอขั้นถัดไป")
        task = self.open_task()
        self.client.post(reverse("workflow:act", args=[task.pk]), {"decision": "FORWARD", "comment": "เห็นควร"})
        self.assertEqual(self.open_task().kind, TaskKind.COMMAND)

    def test_act_by_wrong_user_is_blocked(self):
        self.start()
        login_verified(self.client, self.head_b)
        response = self.client.post(reverse("workflow:act", args=[self.open_task().pk]), {"decision": "FORWARD"})
        self.assertEqual(response.status_code, 404)  # head_b มองไม่เห็นเอกสารนี้
        self.assertEqual(self.open_task().status, TaskStatus.OPEN)

    def test_template_must_end_with_command(self):
        login_verified(self.client, make_admin())
        data = {
            "name": "ทดสอบ", "doc_kind": "INCOMING", "is_active": "on",
            "steps-TOTAL_FORMS": "1", "steps-INITIAL_FORMS": "0", "steps-MIN_NUM_FORMS": "0", "steps-MAX_NUM_FORMS": "1000",
            "steps-0-order": "1", "steps-0-role": "HEAD", "steps-0-scope": "OWNER", "steps-0-kind": "REVIEW", "steps-0-sla_hours": "24",
        }
        response = self.client.post(reverse("workflow:template_create"), data)
        self.assertContains(response, "ขั้นตอนสุดท้ายต้องเป็นการสั่งการ")
        data["steps-0-kind"] = "COMMAND"
        response = self.client.post(reverse("workflow:template_create"), data)
        self.assertRedirects(response, reverse("workflow:template_list"))
        self.assertEqual(WorkflowTemplate.objects.get(name="ทดสอบ").steps.count(), 1)

    def test_swap_step_order(self):
        login_verified(self.client, make_admin())
        steps = list(self.template.steps.order_by("order"))
        data = {
            "name": self.template.name, "doc_kind": "INCOMING", "is_active": "on",
            "steps-TOTAL_FORMS": "2", "steps-INITIAL_FORMS": "2", "steps-MIN_NUM_FORMS": "0", "steps-MAX_NUM_FORMS": "1000",
            "steps-0-id": steps[0].pk, "steps-0-order": "2", "steps-0-role": "HEAD", "steps-0-scope": "OWNER",
            "steps-0-kind": "REVIEW", "steps-0-sla_hours": "24",
            "steps-1-id": steps[1].pk, "steps-1-order": "1", "steps-1-role": "EXECUTIVE", "steps-1-scope": "ANY",
            "steps-1-kind": "COMMAND", "steps-1-sla_hours": "24",
        }
        response = self.client.post(reverse("workflow:template_edit", args=[self.template.pk]), data)
        self.assertContains(response, "ขั้นตอนสุดท้ายต้องเป็นการสั่งการ")  # สลับแล้วคำสั่งการไม่อยู่ท้าย
        data["steps-1-kind"] = "REVIEW"
        data["steps-0-kind"] = "COMMAND"
        data["steps-0-role"] = "EXECUTIVE"
        data["steps-1-role"] = "HEAD"
        response = self.client.post(reverse("workflow:template_edit", args=[self.template.pk]), data)
        self.assertRedirects(response, reverse("workflow:template_list"))

    def test_staff_cannot_manage_templates(self):
        login_verified(self.client, self.staff_a1)
        self.assertEqual(self.client.get(reverse("workflow:template_list")).status_code, 403)

    def test_delegation_page_limits_delegator_to_self(self):
        login_verified(self.client, self.exe)
        today = timezone.localdate().isoformat()
        self.client.post(reverse("workflow:delegations"), {
            "delegator": self.head_a.pk, "delegate": self.staff_a1.pk,
            "start_date": today, "end_date": today, "reason": "พยายามมอบแทนคนอื่น",
        })
        self.assertFalse(self.head_a.delegations_given.exists())
        self.client.post(reverse("workflow:delegations"), {
            "delegator": self.exe.pk, "delegate": self.staff_a1.pk,
            "start_date": today, "end_date": today, "reason": "ไปราชการ",
        })
        delegation = self.exe.delegations_given.get()
        self.client.post(reverse("workflow:delegation_revoke", args=[delegation.pk]))
        delegation.refresh_from_db()
        self.assertIsNotNone(delegation.revoked_at)
