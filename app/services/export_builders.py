"""Current-schema Word and audio builders for submission results."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
import re
import zipfile

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.models import Assignment, User
from app.services import storage
from app.services.workflow_policy import CORE_QUESTION_COUNT


_INVALID_XML_CHARS = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]")
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_FONT = "Microsoft JhengHei"
_BRAND = "4F46E5"
_BRAND_DARK = "312E81"
_BRAND_LIGHT = "EEF2FF"
_TEXT = "1F2937"
_MUTED = "6B7280"
_BORDER = "D1D5DB"
_SUCCESS_LIGHT = "ECFDF5"


@dataclass(frozen=True)
class AudioAsset:
    key: str
    archive_path: str
    category: str


@dataclass(frozen=True)
class DownloadedAudioAsset:
    archive_path: str
    category: str
    payload: bytes


def _xml_safe(value):
    """Remove characters forbidden by OOXML without changing data structure."""
    if isinstance(value, str):
        return _INVALID_XML_CHARS.sub("", value)
    if isinstance(value, list):
        return [_xml_safe(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_xml_safe(item) for item in value)
    if isinstance(value, dict):
        return {key: _xml_safe(item) for key, item in value.items()}
    return value


def safe_export_name(value: str, fallback: str = "作業", limit: int = 80) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", str(value or "")).strip(" ._")
    return cleaned[:limit] or fallback


def _set_run_font(
    run,
    *,
    size: float | None = None,
    bold: bool | None = None,
    color: str | None = None,
):
    run.font.name = _FONT
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), _FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return run


def _set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        tc_pr.append(shading)
    shading.set(qn("w:fill"), fill)


def _set_cell_margins(
    cell,
    *,
    top: int = 100,
    start: int = 140,
    bottom: int = 100,
    end: int = 140,
) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    margins = tc_pr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for name, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = margins.find(qn(f"w:{name}"))
        if node is None:
            node = OxmlElement(f"w:{name}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_table_borders(table, color: str = _BORDER, size: int = 6) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:color"), color)


def _set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    tr_pr.append(repeat)


def _set_row_cant_split(row) -> None:
    row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))


def _keep_with_next(paragraph) -> None:
    paragraph.paragraph_format.keep_with_next = True


def _add_field(paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    code = OxmlElement("w:instrText")
    code.set(qn("xml:space"), "preserve")
    code.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend((begin, code, separate, end))


def _configure_document(doc: Document, student: User, assignment: Assignment, sub) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.7)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)
    section.header_distance = Cm(0.8)
    section.footer_distance = Cm(0.8)

    normal = doc.styles["Normal"]
    normal.font.name = _FONT
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor.from_string(_TEXT)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    for name, size, color in (
        ("Title", 24, _BRAND_DARK),
        ("Heading 1", 16, _BRAND_DARK),
        ("Heading 2", 13, _BRAND_DARK),
        ("Heading 3", 11, _TEXT),
    ):
        style = doc.styles[name]
        style.font.name = _FONT
        style._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.keep_with_next = True

    header = section.header.paragraphs[0]
    header.paragraph_format.space_after = Pt(3)
    _set_run_font(header.add_run("AI 英語面試練習系統"), size=9, bold=True, color=_BRAND)
    _set_run_font(header.add_run(f"　｜　{_xml_safe(assignment.title)}"), size=9, color=_MUTED)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run_font(
        footer.add_run(
            f"{_xml_safe(student.name)}（{_xml_safe(student.student_id)}）｜"
            f"第 {sub.attempt_number} 次｜第 "
        ),
        size=8.5,
        color=_MUTED,
    )
    _add_field(footer, "PAGE")
    _set_run_font(footer.add_run(" 頁，共 "), size=8.5, color=_MUTED)
    _add_field(footer, "NUMPAGES")
    _set_run_font(footer.add_run(" 頁"), size=8.5, color=_MUTED)

    doc.core_properties.title = str(assignment.title)
    doc.core_properties.subject = "學生英語面試學習成果報告"
    doc.core_properties.author = "AI 英語面試練習系統"


def _add_section_heading(doc: Document, number: int, title: str) -> None:
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Cm(2.6)
    table.columns[1].width = Cm(14.6)
    left, right = table.rows[0].cells
    _set_cell_shading(left, _BRAND_DARK)
    _set_cell_shading(right, _BRAND)
    for cell in (left, right):
        _set_cell_margins(cell, top=130, bottom=130, start=170, end=170)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    paragraph = left.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _keep_with_next(paragraph)
    _set_run_font(paragraph.add_run(f"SECTION {number}"), size=9.5, bold=True, color="FFFFFF")
    paragraph = right.paragraphs[0]
    _keep_with_next(paragraph)
    _set_run_font(paragraph.add_run(title), size=13, bold=True, color="FFFFFF")
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def _add_subheading(doc: Document, text: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(4)
    _keep_with_next(paragraph)
    _set_run_font(paragraph.add_run(text), size=12, bold=True, color=_BRAND_DARK)


def _add_labeled_paragraph(
    doc: Document,
    label: str,
    value: object,
    *,
    empty: str = "（未填寫）",
) -> None:
    paragraph = doc.add_paragraph()
    _set_run_font(paragraph.add_run(f"{label}："), bold=True, color=_BRAND_DARK)
    _set_run_font(paragraph.add_run(str(value or empty)))


def _add_answer_card(doc: Document, question: str, answer: object) -> None:
    table = doc.add_table(rows=2, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    _set_table_borders(table, "C7D2FE", 6)
    header, body = table.cell(0, 0), table.cell(1, 0)
    _set_cell_shading(header, _BRAND_LIGHT)
    _set_cell_shading(body, "FFFFFF")
    for cell in (header, body):
        _set_cell_margins(cell, top=110, bottom=110, start=160, end=160)
    _keep_with_next(header.paragraphs[0])
    _set_run_font(header.paragraphs[0].add_run(question), size=10.5, bold=True, color=_BRAND_DARK)
    _set_run_font(body.paragraphs[0].add_run(str(answer or "（未填寫）")), size=10.5)
    _set_row_cant_split(table.rows[0])
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def _add_corrections_table(doc: Document, corrections: list[dict]) -> None:
    table = doc.add_table(rows=1, cols=3)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    _set_table_borders(table)
    for index, label in enumerate(("原句", "修正", "說明")):
        cell = table.rows[0].cells[index]
        _set_cell_shading(cell, _BRAND_DARK)
        _set_cell_margins(cell)
        _set_run_font(cell.paragraphs[0].add_run(label), size=9.5, bold=True, color="FFFFFF")
    _set_repeat_table_header(table.rows[0])
    for correction in corrections:
        row = table.add_row()
        values = (
            correction["original"],
            correction["corrected"],
            correction["explanation"] or "—",
        )
        for index, value in enumerate(values):
            cell = row.cells[index]
            _set_cell_margins(cell)
            if index == 0:
                _set_cell_shading(cell, "FEF2F2")
            elif index == 1:
                _set_cell_shading(cell, _SUCCESS_LIGHT)
            _set_run_font(cell.paragraphs[0].add_run(str(value)), size=9.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def _add_bullets(doc: Document, values: list[object], *, color: str = _TEXT) -> None:
    for value in values:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.space_after = Pt(3)
        _set_run_font(paragraph.add_run(str(value)), color=color)


def _current_feedback(raw, question_count: int) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("AI 回饋不是目前的物件格式")
    questions = raw.get("questions")
    suggestions = raw.get("organization_suggestions")
    if not isinstance(questions, list) or len(questions) != question_count:
        raise ValueError("AI 回饋題數與目前題目快照不一致")
    if not isinstance(suggestions, list) or not all(
        isinstance(suggestion, str) for suggestion in suggestions
    ):
        raise ValueError("AI 回饋缺少 organization_suggestions")
    normalized = []
    for expected_index, item in enumerate(questions):
        if not isinstance(item, dict) or item.get("index") != expected_index:
            raise ValueError("AI 回饋題目 index 不是目前的固定順序")
        corrections = item.get("grammar_corrections")
        polished = item.get("polished_sample")
        if not isinstance(corrections, list) or not isinstance(polished, str):
            raise ValueError("AI 回饋題目缺少正式欄位")
        clean_corrections = []
        for correction in corrections:
            if not isinstance(correction, dict) or not all(
                isinstance(correction.get(field), str)
                for field in ("original", "corrected", "explanation")
            ):
                raise ValueError("AI 回饋文法修正不是目前的正式格式")
            clean_corrections.append(correction)
        normalized.append({**item, "grammar_corrections": clean_corrections})
    return {"questions": normalized, "organization_suggestions": suggestions}


def _current_json_object(raw, label: str) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError(f"{label}不是目前的 JSON 物件格式")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}不是有效 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label}不是目前的物件格式")
    return parsed


def _current_questions(raw) -> list[str]:
    if (
        not isinstance(raw, list)
        or len(raw) != CORE_QUESTION_COUNT
        or not all(isinstance(question, str) and question.strip() for question in raw)
    ):
        raise ValueError(f"題目快照必須是目前固定的 {CORE_QUESTION_COUNT} 題格式")
    return raw


def _current_answers(raw, questions: list[str], label: str) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError(f"{label}不是目前的答案清單格式")
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"{label}包含非物件答案")
        index = item.get("index")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= len(questions)
            or index in seen
            or item.get("question") != questions[index]
            or not isinstance(item.get("text"), str)
        ):
            raise ValueError(f"{label}的題號、題目或答案文字與目前題目快照不一致")
        seen.add(index)
    return raw


def build_submission_docx(student: User, assignment: Assignment, sub) -> bytes:
    """Build the single current-format professional learning report."""
    doc = Document()
    _configure_document(doc, student, assignment, sub)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(8)
    title.paragraph_format.space_after = Pt(3)
    _set_run_font(title.add_run(_xml_safe(assignment.title)), size=24, bold=True, color=_BRAND_DARK)
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(14)
    _set_run_font(subtitle.add_run("英語面試學習成果報告"), size=11, bold=True, color=_MUTED)

    info = doc.add_table(rows=2, cols=2)
    info.alignment = WD_TABLE_ALIGNMENT.CENTER
    info.autofit = True
    _set_table_borders(info, "C7D2FE", 6)
    submitted_at = sub.submitted_at.strftime("%Y-%m-%d %H:%M") if sub.submitted_at else "未完成"
    info_values = (
        ("學生", f"{_xml_safe(student.name)}（{_xml_safe(student.student_id)}）"),
        ("作答版本", f"第 {sub.attempt_number} 次"),
        ("完成時間", submitted_at),
        ("報告內容", "寫作、口說、AI 回饋、心得與教師批改"),
    )
    for index, (label, value) in enumerate(info_values):
        cell = info.cell(index // 2, index % 2)
        _set_cell_shading(cell, _BRAND_LIGHT if index % 2 == 0 else "FFFFFF")
        _set_cell_margins(cell, top=130, bottom=130, start=170, end=170)
        paragraph = cell.paragraphs[0]
        _set_run_font(paragraph.add_run(f"{label}\n"), size=8.5, bold=True, color=_MUTED)
        _set_run_font(paragraph.add_run(str(value)), size=10.5, bold=True, color=_TEXT)
    for row in info.rows:
        _set_row_cant_split(row)
    doc.add_paragraph()

    _add_section_heading(doc, 0, "欲應徵的職位")
    profile = _xml_safe(getattr(sub, "job_profile_data", None) or {})
    if not isinstance(profile, dict):
        raise ValueError("職位資料不是目前的物件格式")
    for label, key in (
        ("欲應徵職位", "desired_position"),
        ("職位工作內容", "role_description"),
        ("所需職能", "required_competencies"),
        ("其他補充", "additional_notes"),
    ):
        _add_labeled_paragraph(doc, label, profile.get(key))

    _add_section_heading(doc, 1, "寫作練習")
    raw_questions = _current_questions(getattr(sub, "questions_snapshot", None))
    questions = _xml_safe(raw_questions)
    draft1 = _xml_safe(
        _current_answers(
            getattr(sub, "draft1_answers", None) or [],
            raw_questions,
            "草稿一",
        )
    )
    final_draft = _xml_safe(
        _current_answers(
            getattr(sub, "final_draft_answers", None) or [],
            raw_questions,
            "最終草稿",
        )
    )

    _add_subheading(doc, "草稿一 Draft 1")
    if draft1:
        for item in draft1:
            if not isinstance(item, dict):
                raise ValueError("草稿一答案不是目前格式")
            _add_answer_card(doc, f"Q{int(item['index']) + 1}　{item['question']}", item.get("text"))
    else:
        doc.add_paragraph("（未填寫）")

    _add_subheading(doc, "AI 回饋")
    feedback = _xml_safe(_current_feedback(getattr(sub, "draft2_ai_feedback", None), len(questions)))
    if feedback:
        for item in feedback["questions"]:
            index = int(item["index"])
            _add_subheading(doc, f"Q{index + 1}　{questions[index]}")
            corrections = item["grammar_corrections"]
            if corrections:
                _add_corrections_table(doc, corrections)
            else:
                paragraph = doc.add_paragraph()
                _set_run_font(paragraph.add_run("本題沒有需要優先修正的文法或用字。"), color=_MUTED)
            _add_answer_card(doc, "建議範文", item["polished_sample"])
        _add_subheading(doc, "組織架構建議")
        _add_bullets(doc, feedback["organization_suggestions"], color=_BRAND_DARK)
    else:
        doc.add_paragraph("（尚未取得 AI 回饋）")

    _add_subheading(doc, "最終草稿 Final Draft")
    if final_draft:
        for item in final_draft:
            if not isinstance(item, dict):
                raise ValueError("最終草稿答案不是目前格式")
            _add_answer_card(doc, f"Q{int(item['index']) + 1}　{item['question']}", item.get("text"))
    else:
        doc.add_paragraph("（未填寫）")

    _add_section_heading(doc, 2, "口說練習一：跟讀")
    shadowing = _xml_safe(getattr(sub, "speaking1_questions", None) or [])
    if not isinstance(shadowing, list):
        raise ValueError("跟讀資料不是目前格式")
    if shadowing:
        for item in sorted(shadowing, key=lambda value: int(value.get("index", 0))):
            _add_answer_card(
                doc,
                f"Q{int(item.get('index', 0)) + 1}　語音辨識結果",
                item.get("transcript") or "（無辨識文字）",
            )
    else:
        doc.add_paragraph("（未完成跟讀練習）")

    _add_section_heading(doc, 3, "口說練習二：角色扮演面試")
    conversation = _xml_safe(
        _current_json_object(getattr(sub, "roleplay_conversation", None), "角色扮演資料")
    )
    turns = conversation.get("turns", []) if conversation else []
    if turns:
        for turn in turns:
            if (
                not isinstance(turn, dict)
                or not isinstance(turn.get("turn_number"), int)
                or not isinstance(turn.get("interviewer_question"), str)
                or (
                    turn.get("student_transcript") is not None
                    and not isinstance(turn.get("student_transcript"), str)
                )
            ):
                raise ValueError("角色扮演回合不是目前格式")
            _add_subheading(doc, f"第 {turn['turn_number']} 輪")
            _add_answer_card(doc, "面試官提問", turn.get("interviewer_question"))
            _add_answer_card(doc, "學生回答", turn.get("student_transcript") or "（未回答）")
    else:
        doc.add_paragraph("（未完成角色扮演）")

    _add_section_heading(doc, 4, "口語表現回饋")
    report = _xml_safe(_current_json_object(getattr(sub, "report_data", None), "口語回饋資料"))
    if report:
        labels = {
            "language_complexity": "語言豐富度",
            "language_accuracy": "語言準確度",
            "content_logic": "內容邏輯與組織",
            "interview_strategy": "面試策略與表現效果",
        }
        analysis = report.get("analysis") or {}
        if not isinstance(analysis, dict):
            raise ValueError("口語回饋 analysis 不是目前格式")
        _add_subheading(doc, "詳細分析")
        for key, label in labels.items():
            _add_labeled_paragraph(doc, label, analysis.get(key), empty="—")
        strengths = report.get("strengths") or []
        suggestions = report.get("overall_suggestions") or []
        if (
            not isinstance(strengths, list)
            or not isinstance(suggestions, list)
            or not all(isinstance(value, str) for value in strengths + suggestions)
        ):
            raise ValueError("口語回饋清單不是目前格式")
        _add_subheading(doc, "表現優點")
        _add_bullets(doc, strengths, color="047857")
        _add_subheading(doc, "改進建議")
        _add_bullets(doc, suggestions, color="9A3412")
    else:
        doc.add_paragraph("（尚未生成 AI 回饋）")

    _add_section_heading(doc, 5, "心得學習單")
    reflection = _xml_safe(getattr(sub, "reflection_data", None) or {})
    if not isinstance(reflection, dict):
        raise ValueError("心得資料不是目前格式")
    reflection_questions = reflection.get("questions") or []
    reflection_answers = reflection.get("answers") or []
    if (
        not isinstance(reflection_questions, list)
        or not isinstance(reflection_answers, list)
        or not all(
            isinstance(value, str)
            for value in reflection_questions + reflection_answers
        )
    ):
        raise ValueError("心得題目或答案不是目前格式")
    if reflection_questions:
        for index, question in enumerate(reflection_questions):
            _add_answer_card(
                doc,
                f"{index + 1}. {question}",
                reflection_answers[index] if index < len(reflection_answers) else "",
            )
    else:
        doc.add_paragraph("（未填寫）")
    _add_labeled_paragraph(doc, "是否回報問題", "是" if reflection.get("has_issue") else "否")
    if reflection.get("has_issue"):
        _add_labeled_paragraph(doc, "問題類別", reflection.get("issue_category"))
        _add_labeled_paragraph(doc, "問題說明", reflection.get("issue_description"))

    _add_section_heading(doc, 6, "老師最新批改結果")
    grade = _xml_safe(getattr(sub, "latest_grade_data", None))
    if grade:
        if not isinstance(grade, dict):
            raise ValueError("教師批改資料不是目前格式")
        score = doc.add_table(rows=1, cols=2)
        score.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(score, "A5B4FC", 8)
        score_label, score_value = score.rows[0].cells
        _set_cell_shading(score_label, _BRAND_DARK)
        _set_cell_shading(score_value, _BRAND_LIGHT)
        for cell in (score_label, score_value):
            _set_cell_margins(cell, top=180, bottom=180, start=200, end=200)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _set_run_font(
            score_label.paragraphs[0].add_run("教師最後成績"),
            size=12,
            bold=True,
            color="FFFFFF",
        )
        score_paragraph = score_value.paragraphs[0]
        score_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_run_font(
            score_paragraph.add_run(f"{float(grade['final_score']):g} / 100"),
            size=20,
            bold=True,
            color=_BRAND_DARK,
        )
        doc.add_paragraph()
        _add_labeled_paragraph(
            doc,
            "評分規準",
            f"{grade['rubric_name']} v{grade['rubric_version_number']}",
        )
        _add_labeled_paragraph(
            doc,
            "批改者",
            grade.get("grader_name") or grade.get("grader_student_id") or "—",
        )
        _add_subheading(doc, "評分規準明細")
        ratings = grade.get("ratings") or []
        if not isinstance(ratings, list):
            raise ValueError("教師 Rubric 明細不是目前格式")
        rubric_table = doc.add_table(rows=1, cols=3)
        rubric_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(rubric_table)
        for index, label in enumerate(("評分面向", "評分項目", "結果")):
            cell = rubric_table.rows[0].cells[index]
            _set_cell_shading(cell, _BRAND_DARK)
            _set_cell_margins(cell)
            _set_run_font(cell.paragraphs[0].add_run(label), size=9.5, bold=True, color="FFFFFF")
        _set_repeat_table_header(rubric_table.rows[0])
        for item in ratings:
            row = rubric_table.add_row()
            values = (
                item.get("dimension_name", ""),
                item.get("criterion_name", ""),
                item.get("level_label", ""),
            )
            for index, value in enumerate(values):
                _set_cell_margins(row.cells[index])
                _set_run_font(row.cells[index].paragraphs[0].add_run(str(value)), size=9.5)
            _set_row_cant_split(row)
        _add_subheading(doc, "總評")
        _add_answer_card(doc, "老師總評", grade.get("teacher_comment") or "—")
        _add_subheading(doc, "改善回饋")
        _add_answer_card(doc, "後續建議", grade.get("teacher_feedback") or "—")
    else:
        doc.add_paragraph("（老師尚未批改）")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def submission_audio_assets(sub) -> list[AudioAsset]:
    """Return every current audio reference in stable report order."""
    assets: list[AudioAsset] = []
    tts_entries = getattr(sub, "shadowing_tts_keys", None) or []
    speaking_entries = getattr(sub, "speaking1_questions", None) or []
    if not isinstance(tts_entries, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("index"), int)
        and (item.get("key") is None or isinstance(item.get("key"), str))
        for item in tts_entries
    ):
        raise ValueError("跟讀示範音檔索引不是目前格式")
    if not isinstance(speaking_entries, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("index"), int)
        and (
            item.get("audio_key") is None
            or isinstance(item.get("audio_key"), str)
        )
        for item in speaking_entries
    ):
        raise ValueError("學生跟讀音檔索引不是目前格式")
    for item in sorted(tts_entries, key=lambda value: value["index"]):
        if item.get("key"):
            number = item["index"] + 1
            assets.append(
                AudioAsset(
                    str(item["key"]),
                    f"音檔/跟讀示範/跟讀示範_Q{number}.mp3",
                    "跟讀示範",
                )
            )
    for item in sorted(speaking_entries, key=lambda value: value["index"]):
        if item.get("audio_key"):
            number = item["index"] + 1
            assets.append(
                AudioAsset(
                    str(item["audio_key"]),
                    f"音檔/學生跟讀/學生跟讀_Q{number}.mp3",
                    "學生跟讀",
                )
            )
    conversation = _current_json_object(
        getattr(sub, "roleplay_conversation", None),
        "角色扮演資料",
    )
    turns = conversation.get("turns", []) if conversation else []
    if not isinstance(turns, list) or not all(
        isinstance(turn, dict)
        and isinstance(turn.get("turn_number"), int)
        and (
            turn.get("interviewer_tts_key") is None
            or isinstance(turn.get("interviewer_tts_key"), str)
        )
        and (
            turn.get("student_audio_key") is None
            or isinstance(turn.get("student_audio_key"), str)
        )
        for turn in turns
    ):
        raise ValueError("角色扮演音檔回合不是目前格式")
    for turn in sorted(turns, key=lambda value: value["turn_number"]):
        number = turn["turn_number"]
        if turn.get("interviewer_tts_key"):
            assets.append(
                AudioAsset(
                    str(turn["interviewer_tts_key"]),
                    f"音檔/面試官語音/面試官_第{number}輪.mp3",
                    "面試官語音",
                )
            )
        if turn.get("student_audio_key"):
            assets.append(
                AudioAsset(
                    str(turn["student_audio_key"]),
                    f"音檔/學生面試錄音/學生_第{number}輪.mp3",
                    "學生面試錄音",
                )
            )
    for asset in assets:
        if not storage.is_current_object_key(asset.key, "audio"):
            raise ValueError(f"音檔不屬於目前資料版本：{asset.archive_path}")
    archive_paths = [asset.archive_path for asset in assets]
    if len(archive_paths) != len(set(archive_paths)):
        raise ValueError("音檔題號或回合重複，無法建立穩定成果包")
    return assets


def _validate_complete_audio_assets(assets: list[AudioAsset]) -> None:
    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset.category] = counts.get(asset.category, 0) + 1
    expected = {
        "跟讀示範": CORE_QUESTION_COUNT,
        "學生跟讀": CORE_QUESTION_COUNT,
    }
    for category, count in expected.items():
        if counts.get(category, 0) != count:
            raise ValueError(f"{category}音檔必須完整包含 {count} 題")
    interviewer_count = counts.get("面試官語音", 0)
    student_count = counts.get("學生面試錄音", 0)
    if interviewer_count < 1 or student_count != interviewer_count:
        raise ValueError("角色扮演的面試官與學生音檔必須逐輪完整配對")


def download_submission_audio(sub) -> list[DownloadedAudioAsset]:
    """Download all referenced audio or fail the whole operation."""
    assets = submission_audio_assets(sub)
    _validate_complete_audio_assets(assets)
    downloaded: list[DownloadedAudioAsset] = []
    for asset in assets:
        try:
            payload = storage.download_file(asset.key)
        except Exception as exc:
            raise RuntimeError(f"音檔下載失敗：{asset.archive_path}") from exc
        if not payload:
            raise RuntimeError(f"音檔內容為空：{asset.archive_path}")
        downloaded.append(
            DownloadedAudioAsset(asset.archive_path, asset.category, payload)
        )
    return downloaded


def audio_manifest(downloaded: list[DownloadedAudioAsset]) -> str:
    counts: dict[str, int] = {}
    for asset in downloaded:
        counts[asset.category] = counts.get(asset.category, 0) + 1
    lines = [
        "AI 英語面試練習系統－成果包檔案清單",
        "",
        "學習成果報告.docx",
        *[asset.archive_path for asset in downloaded],
        "",
        "音檔統計：",
        *[
            f"- {label}：{counts.get(label, 0)} 個"
            for label in ("跟讀示範", "學生跟讀", "面試官語音", "學生面試錄音")
        ],
    ]
    return "\n".join(lines)


def build_submission_audio_zip(student: User, sub) -> bytes:
    downloaded = download_submission_audio(sub)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for asset in downloaded:
            archive.writestr(asset.archive_path, asset.payload)
        archive.writestr("_檔案清單.txt", audio_manifest(downloaded).encode("utf-8"))
    return buffer.getvalue()


def build_submission_result_package(student: User, assignment: Assignment, sub) -> bytes:
    """Build one all-or-nothing ZIP with the Word report and every referenced audio."""
    document = build_submission_docx(student, assignment, sub)
    downloaded = download_submission_audio(sub)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("學習成果報告.docx", document)
        for asset in downloaded:
            archive.writestr(asset.archive_path, asset.payload)
        archive.writestr("_檔案清單.txt", audio_manifest(downloaded).encode("utf-8"))
    return buffer.getvalue()
