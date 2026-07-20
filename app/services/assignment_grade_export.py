"""Assignment grade export data selection and XLSX construction."""
import io
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, load_only

from app.models import User, Assignment, Submission, SubmissionGradeRevision
from app.services.admin_scope import apply_student_visibility_filter, student_matches_assignment
from app.services.grading import latest_grade, grade_admin_payload
from app.services.submission_data import hydrate_submission_from_normalized
from app.services.workflow_policy import workflow_stage_label
from app.services.xlsx import append_xlsx_row

_TAIPEI = ZoneInfo("Asia/Taipei")
_GRADEBOOK_HEADERS = [
    "學號", "姓名", "Email", "班級", "嘗試次數", "最新嘗試序號", "目前進度",
    "繳交狀態", "繳交時間", "批改狀態", "Rubric 名稱", "Rubric 版本",
    "Rubric 計算分數", "最後成績", "批改者", "批改時間", "老師總評", "改進建議",
]
_RUBRIC_DETAIL_HEADERS = [
    "學號", "姓名", "Email", "班級", "最新嘗試序號", "Rubric 名稱", "Rubric 版本",
    "面向代碼", "面向名稱", "面向配分", "評分項目代碼", "評分項目名稱",
    "評分項目說明", "項目滿分", "評定等級", "等級名稱", "等級說明", "實得分",
]
def _hydrate_for_export(db: Session, sub: Submission) -> Submission:
    hydrate_submission_from_normalized(db, sub)
    row = latest_grade(db, sub.id)
    setattr(sub, "latest_grade_data", grade_admin_payload(row) if row else None)
    return sub


def _get_visible_students_for_assignment(db: Session, admin: User, assignment: Assignment) -> list[User]:
    students = apply_student_visibility_filter(
        db.query(User).options(load_only(User.id, User.student_id, User.name, User.email, User.course_num)),
        admin,
    ).all()
    return [student for student in students if student_matches_assignment(student, assignment)]


def _latest_submissions_by_user(submissions: list[Submission]) -> dict[int, Submission]:
    latest: dict[int, Submission] = {}
    for submission in submissions:
        current = latest.get(submission.user_id)
        current_key = (
            int(current.attempt_number or 0),
            int(current.id or 0),
        ) if current else None
        candidate_key = (int(submission.attempt_number or 0), int(submission.id or 0))
        if current_key is None or candidate_key > current_key:
            latest[submission.user_id] = submission
    return latest


def _xlsx_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(_TAIPEI).replace(tzinfo=None)


def _stage_label(submission: Submission | None) -> str:
    if submission is None:
        return "未開始"
    stage = int(submission.stage or 0)
    label = workflow_stage_label(stage)
    return f"第 {stage} 階段：{label}" if label else f"第 {stage} 階段"


def _grader_label(grade: SubmissionGradeRevision | None) -> str:
    if grade is None:
        return ""
    name = (grade.grader_name or "").strip()
    grader_id = (grade.grader_student_id or "").strip()
    if name and grader_id:
        return f"{name}（{grader_id}）"
    return name or grader_id


def _ordered_rubric_ratings(grade: SubmissionGradeRevision) -> list[dict]:
    ratings = [item for item in (grade.ratings_json or []) if isinstance(item, dict)]
    ratings_by_key = {
        str(item.get("criterion_key")): item
        for item in ratings
        if item.get("criterion_key") is not None
    }
    ordered: list[dict] = []
    seen: set[str] = set()
    snapshot = grade.rubric_snapshot if isinstance(grade.rubric_snapshot, dict) else {}
    shared_levels = snapshot.get("levels") if isinstance(snapshot.get("levels"), list) else []

    for dimension in snapshot.get("dimensions") or []:
        if not isinstance(dimension, dict):
            continue
        for criterion in dimension.get("criteria") or []:
            if not isinstance(criterion, dict):
                continue
            criterion_key = str(criterion.get("key") or "")
            rating = ratings_by_key.get(criterion_key)
            if not rating:
                continue
            levels = criterion.get("levels") if isinstance(criterion.get("levels"), list) else shared_levels
            selected_level = next(
                (
                    level for level in levels
                    if isinstance(level, dict) and str(level.get("value")) == str(rating.get("level"))
                ),
                {},
            )
            ordered.append({
                **rating,
                "dimension_key": dimension.get("key") or rating.get("dimension_key"),
                "dimension_name": dimension.get("name") or rating.get("dimension_name"),
                "dimension_weight": dimension.get("weight"),
                "criterion_key": criterion.get("key") or rating.get("criterion_key"),
                "criterion_name": criterion.get("name") or rating.get("criterion_name"),
                "criterion_description": criterion.get("description") or rating.get("criterion_description"),
                "max_points": criterion.get("points") if criterion.get("points") is not None else rating.get("max_points"),
                "level_label": rating.get("level_label") or selected_level.get("label"),
                "level_anchor": rating.get("level_anchor") or selected_level.get("anchor"),
            })
            seen.add(criterion_key)

    for rating in ratings:
        criterion_key = str(rating.get("criterion_key") or "")
        if criterion_key not in seen:
            ordered.append({**rating, "dimension_weight": None})
    return ordered


def _style_export_sheet(
    worksheet,
    widths: list[int],
    *,
    datetime_columns: tuple[int, ...] = (),
    number_formats: dict[int, str] | None = None,
) -> None:
    header_fill = PatternFill("solid", fgColor="4F46E5")
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = f"A1:{get_column_letter(worksheet.max_column)}{worksheet.max_row}"
    worksheet.row_dimensions[1].height = 30
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for column in datetime_columns:
        for cell in worksheet.iter_cols(min_col=column, max_col=column, min_row=2):
            for item in cell:
                if item.value not in (None, ""):
                    item.number_format = "yyyy-mm-dd hh:mm"
    for column, number_format in (number_formats or {}).items():
        for cell in worksheet.iter_cols(min_col=column, max_col=column, min_row=2):
            for item in cell:
                if isinstance(item.value, (int, float)):
                    item.number_format = number_format


def _build_assignment_grade_workbook(
    assignment: Assignment,
    students: list[User],
    submissions: list[Submission],
    grades_by_submission: dict[int, SubmissionGradeRevision],
):
    workbook = openpyxl.Workbook()
    workbook.properties.title = f"{assignment.title} 學生成績"
    workbook.properties.subject = "作業成績與 Rubric 評分明細"
    gradebook = workbook.active
    gradebook.title = "成績總表"
    details = workbook.create_sheet("Rubric 明細")
    gradebook.append(_GRADEBOOK_HEADERS)
    details.append(_RUBRIC_DETAIL_HEADERS)

    submissions_by_user: dict[int, list[Submission]] = defaultdict(list)
    for submission in submissions:
        submissions_by_user[submission.user_id].append(submission)
    latest_by_user = _latest_submissions_by_user(submissions)
    sorted_students = sorted(
        students,
        key=lambda student: (
            (student.course_num or "").casefold(),
            (student.student_id or "").casefold(),
            int(student.id),
        ),
    )

    for student in sorted_students:
        latest = latest_by_user.get(student.id)
        grade = grades_by_submission.get(latest.id) if latest else None
        submitted = bool(latest and latest.submitted_at is not None)
        submission_status = "已繳交" if submitted else ("未繳交" if latest else "未開始")
        grading_status = "已批改" if grade else ("待批改" if submitted else "未就緒")
        append_xlsx_row(gradebook, [
            student.student_id,
            student.name,
            student.email,
            student.course_num or "",
            len(submissions_by_user.get(student.id, [])),
            latest.attempt_number if latest else None,
            _stage_label(latest),
            submission_status,
            _xlsx_datetime(latest.submitted_at) if latest else None,
            grading_status,
            grade.rubric_name if grade else "",
            grade.rubric_version_number if grade else None,
            float(grade.rubric_score) if grade else None,
            float(grade.final_score) if grade else None,
            _grader_label(grade),
            _xlsx_datetime(grade.created_at) if grade else None,
            grade.teacher_comment if grade else "",
            grade.teacher_feedback if grade else "",
        ])

        if not latest or not grade:
            continue
        for rating in _ordered_rubric_ratings(grade):
            append_xlsx_row(details, [
                student.student_id,
                student.name,
                student.email,
                student.course_num or "",
                latest.attempt_number,
                grade.rubric_name,
                grade.rubric_version_number,
                rating.get("dimension_key"),
                rating.get("dimension_name"),
                rating.get("dimension_weight"),
                rating.get("criterion_key"),
                rating.get("criterion_name"),
                rating.get("criterion_description"),
                rating.get("max_points"),
                rating.get("level"),
                rating.get("level_label"),
                rating.get("level_anchor"),
                rating.get("awarded_points"),
            ])

    _style_export_sheet(
        gradebook,
        [14, 16, 28, 14, 11, 14, 22, 12, 18, 12, 24, 12, 16, 12, 22, 18, 45, 45],
        datetime_columns=(9, 16),
        number_formats={13: "0.00", 14: "0.0"},
    )
    _style_export_sheet(
        details,
        [14, 16, 28, 14, 14, 24, 12, 20, 22, 12, 22, 24, 42, 12, 12, 18, 50, 12],
        number_formats={10: "0.00", 14: "0.00", 18: "0.00"},
    )
    return workbook


def _safe_assignment_grade_filename(assignment: Assignment) -> str:
    invalid = set('/\\:*?"<>|')
    safe_title = "".join(
        "_" if character in invalid or ord(character) < 32 else character
        for character in (assignment.title or "")
    ).strip(" ._")[:80]
    return f"{safe_title or f'assignment_{assignment.id}'}_學生成績.xlsx"


# ── Per-submission exports ────────────────────────────────────────────────────

