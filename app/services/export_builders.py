"""Pure document/audio builders for admin submission exports.

Split out of exports.py (which now holds only the route handlers) so the heavy
formatting logic — a ~260-line Word-document builder and the audio-zip packer —
lives on its own and can be read/tested in isolation. No FastAPI/router state here.
"""
import io
import re
import zipfile

from docx import Document

from app.db_helpers import safe_json_parse
from app.models import User, Assignment
from app.services import storage

_INVALID_XML_CHARS = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]")


def _xml_safe(value):
    """Recursively remove characters OOXML 1.0 cannot represent."""
    if isinstance(value, str):
        return _INVALID_XML_CHARS.sub("", value)
    if isinstance(value, list):
        return [_xml_safe(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_xml_safe(item) for item in value)
    if isinstance(value, dict):
        return {key: _xml_safe(item) for key, item in value.items()}
    return value


def _build_submission_docx(student: User, assignment: Assignment, sub) -> bytes:
    doc = Document()

    # ── Document title ────────────────────────────────────────────────────────
    title = doc.add_heading(_xml_safe(assignment.title) if assignment else "作業", 0)
    title.alignment = 1  # center

    # Student info table
    info = doc.add_table(rows=3, cols=2)
    info.style = "Light Shading Accent 1"
    labels = ["學生", "嘗試次數", "完成時間"]
    values = [
        f"{_xml_safe(student.name)}（{_xml_safe(student.student_id)}）",
        f"第 {sub.attempt_number} 次",
        sub.submitted_at.strftime("%Y-%m-%d %H:%M") if sub.submitted_at else "未完成",
    ]
    for i, (lbl, val) in enumerate(zip(labels, values)):
        info.cell(i, 0).text = lbl
        info.cell(i, 1).text = val
        run = info.cell(i, 0).paragraphs[0].runs
        if run:
            run[0].bold = True
    doc.add_paragraph()

    # ── Section 0: Job profile ────────────────────────────────────────────────
    doc.add_heading("Section 0　欲應徵的職位", 1)
    profile = _xml_safe(getattr(sub, "job_profile_data", None) or {})
    for label, key in (
        ("欲應徵職位", "desired_position"),
        ("職位工作內容", "role_description"),
        ("所需職能", "required_competencies"),
        ("其他補充", "additional_notes"),
    ):
        p = doc.add_paragraph()
        p.add_run(f"{label}：").bold = True
        p.add_run(str(profile.get(key) or "（未填寫）"))

    # ── Section 1: Writing ────────────────────────────────────────────────────
    doc.add_heading("Section 1　寫作練習", 1)

    doc.add_heading("草稿一 Draft 1", 2)
    draft1_answers = _xml_safe(getattr(sub, 'draft1_answers', None))
    if draft1_answers and isinstance(draft1_answers, list):
        for item in draft1_answers:
            doc.add_heading(f"Q{item.get('index', 0)+1}: {item.get('question', '')}", 3)
            doc.add_paragraph(item.get("text") or "（未填寫）")
    else:
        doc.add_paragraph("（未填寫）")

    q_text_map: dict = {}
    if draft1_answers and isinstance(draft1_answers, list):
        for item in draft1_answers:
            idx = item.get('index')
            if idx is not None:
                q_text_map[idx] = item.get('question', '')
    # Exports must only use the attempt's immutable question snapshot.
    snapshot = _xml_safe(getattr(sub, 'questions_snapshot', None))
    asgn_qs: list = snapshot if isinstance(snapshot, list) else []

    doc.add_heading("AI 回饋", 2)
    fb = _xml_safe(safe_json_parse(sub.draft2_ai_feedback))
    if fb:
        questions_fb = fb.get("questions", [])
        if questions_fb and isinstance(questions_fb, list):
            for q in questions_fb:
                q_idx = q.get('index', 0)
                q_text = q_text_map.get(q_idx) or (asgn_qs[q_idx] if q_idx < len(asgn_qs) else '')
                heading_text = f"Q{q_idx + 1}：{q_text}" if q_text else f"Q{q_idx + 1}"
                doc.add_heading(heading_text, 3)
                corrections = q.get("grammar_corrections", [])
                if corrections:
                    doc.add_heading(f"文法修正（{len(corrections)} 處）", 4)
                    for c in corrections:
                        p = doc.add_paragraph(style="List Bullet")
                        p.add_run("原句：").bold = True
                        p.add_run(str(c.get("original", "")))
                        p2 = doc.add_paragraph(style="List Bullet")
                        p2.add_run("修正：").bold = True
                        p2.add_run(str(c.get("corrected", "")))
                        if c.get("explanation"):
                            p3 = doc.add_paragraph(style="List Bullet")
                            p3.add_run("說明：").bold = True
                            p3.add_run(str(c.get("explanation", "")))
                        doc.add_paragraph()
                polished = q.get("polished_sample", "")
                if polished:
                    doc.add_heading("建議範文", 4)
                    doc.add_paragraph(str(polished))
        else:
            corrections = fb.get("grammar_corrections", [])
            if corrections:
                num_q = len(asgn_qs) or (max(q_text_map.keys(), default=-1) + 1)
                draft1_text_map: dict = {}
                if draft1_answers and isinstance(draft1_answers, list):
                    for item in draft1_answers:
                        if isinstance(item, dict) and item.get('index') is not None:
                            draft1_text_map[item['index']] = item.get('text', '')
                if num_q > 0:
                    corr_by_q = [[] for _ in range(num_q)]
                    unmatched = []
                    for c in corrections:
                        hit = False
                        orig = c.get('original', '')
                        for i in range(num_q):
                            ans = draft1_text_map.get(i, '')
                            if ans and orig and orig in ans:
                                corr_by_q[i].append(c)
                                hit = True
                                break
                        if not hit:
                            unmatched.append(c)
                    for i in range(num_q):
                        if not corr_by_q[i]:
                            continue
                        q_text = q_text_map.get(i) or (asgn_qs[i] if i < len(asgn_qs) else '')
                        heading_text = f"Q{i + 1}：{q_text}" if q_text else f"Q{i + 1}"
                        doc.add_heading(heading_text, 3)
                        doc.add_heading(f"文法修正（{len(corr_by_q[i])} 處）", 4)
                        for c in corr_by_q[i]:
                            p = doc.add_paragraph(style="List Bullet")
                            p.add_run("原句：").bold = True
                            p.add_run(str(c.get("original", "")))
                            p2 = doc.add_paragraph(style="List Bullet")
                            p2.add_run("修正：").bold = True
                            p2.add_run(str(c.get("corrected", "")))
                            if c.get("explanation"):
                                p3 = doc.add_paragraph(style="List Bullet")
                                p3.add_run("說明：").bold = True
                                p3.add_run(str(c.get("explanation", "")))
                            doc.add_paragraph()
                    if unmatched:
                        doc.add_heading(f"其他文法修正（{len(unmatched)} 處）", 3)
                        for c in unmatched:
                            p = doc.add_paragraph(style="List Bullet")
                            p.add_run("原句：").bold = True
                            p.add_run(str(c.get("original", "")))
                            p2 = doc.add_paragraph(style="List Bullet")
                            p2.add_run("修正：").bold = True
                            p2.add_run(str(c.get("corrected", "")))
                            if c.get("explanation"):
                                p3 = doc.add_paragraph(style="List Bullet")
                                p3.add_run("說明：").bold = True
                                p3.add_run(str(c.get("explanation", "")))
                            doc.add_paragraph()
                else:
                    doc.add_heading("文法修正", 3)
                    for c in corrections:
                        p = doc.add_paragraph(style="List Bullet")
                        p.add_run("原句：").bold = True
                        p.add_run(str(c.get("original", "")))
                        p2 = doc.add_paragraph(style="List Bullet")
                        p2.add_run("修正：").bold = True
                        p2.add_run(str(c.get("corrected", "")))
                        if c.get("explanation"):
                            p3 = doc.add_paragraph(style="List Bullet")
                            p3.add_run("說明：").bold = True
                            p3.add_run(str(c.get("explanation", "")))
                        doc.add_paragraph()
            polished = fb.get("polished_sample", "")
            if polished:
                doc.add_heading("建議範文", 3)
                doc.add_paragraph(str(polished))
        org = fb.get("organization_suggestions", [])
        if org:
            doc.add_heading("組織架構建議", 3)
            for s in org:
                doc.add_paragraph(str(s), style="List Bullet")
    else:
        doc.add_paragraph("（尚未獲取 AI 回饋）")

    doc.add_heading("最終草稿 Final Draft", 2)
    final_draft_answers = _xml_safe(getattr(sub, 'final_draft_answers', None))
    if final_draft_answers and isinstance(final_draft_answers, list):
        for item in final_draft_answers:
            doc.add_heading(f"Q{item.get('index', 0)+1}: {item.get('question', '')}", 3)
            doc.add_paragraph(item.get("text") or "（未填寫）")
    else:
        doc.add_paragraph("（未填寫）")

    # ── Section 2: Shadowing ──────────────────────────────────────────────────
    doc.add_heading("Section 2　口說練習一：跟讀", 1)
    speaking1_questions = _xml_safe(sub.speaking1_questions or [])
    if speaking1_questions:
        doc.add_heading("語音辨識結果", 2)
        for q in sorted(speaking1_questions, key=lambda x: x.get("index", 0)):
            transcript = q.get("transcript")
            if transcript:
                doc.add_heading(f"Q{q.get('index', 0) + 1}", 3)
                doc.add_paragraph(transcript)
    else:
        doc.add_paragraph("（未完成跟讀練習）")

    # ── Section 3: Roleplay ───────────────────────────────────────────────────
    doc.add_heading("Section 3　口說練習二：角色扮演面試", 1)
    conv = _xml_safe(safe_json_parse(sub.roleplay_conversation))
    turns = conv.get("turns", []) if conv else []
    if turns:
        for t in turns:
            doc.add_heading(f"第 {t.get('turn_number', '?')} 輪", 2)
            p = doc.add_paragraph()
            p.add_run("面試官提問：").bold = True
            p.add_run(t.get("interviewer_question", ""))
            p2 = doc.add_paragraph()
            p2.add_run("學生回答：").bold = True
            p2.add_run(t.get("student_transcript") or "（未回答）")
    else:
        doc.add_paragraph("（未完成角色扮演）")

    # ── Section 4: Report ─────────────────────────────────────────────────────
    doc.add_heading("Section 4　口語表現回饋", 1)
    report = _xml_safe(safe_json_parse(sub.report_data))
    if report:
        analysis_labels = {
            "language_complexity": "語言豐富度",
            "language_accuracy": "語言準確度",
            "content_logic": "內容邏輯與組織", "interview_strategy": "面試策略與表現效果",
        }

        analysis = report.get("analysis", {})
        if analysis:
            doc.add_heading("詳細分析", 2)
            for key, label in analysis_labels.items():
                val = analysis.get(key, "")
                if val:
                    p = doc.add_paragraph()
                    p.add_run(f"{label}：").bold = True
                    p.add_run(str(val))

        strengths = report.get("strengths", [])
        if strengths:
            doc.add_heading("表現優點", 2)
            for s in strengths:
                doc.add_paragraph(f"✓  {s}", style="List Bullet")

        suggestions = report.get("overall_suggestions", [])
        if suggestions:
            doc.add_heading("改進建議", 2)
            for s in suggestions:
                doc.add_paragraph(f"→  {s}", style="List Bullet")

    else:
        doc.add_paragraph("（尚未生成 AI 回饋）")

    # ── Section 5: Reflection ─────────────────────────────────────────────────
    doc.add_heading("Section 5　心得學習單", 1)
    reflection = _xml_safe(getattr(sub, "reflection_data", None) or {})
    questions = reflection.get("questions") or []
    answers = reflection.get("answers") or []
    if questions:
        for index, question in enumerate(questions):
            doc.add_heading(f"{index + 1}. {question}", 2)
            doc.add_paragraph(answers[index] if index < len(answers) and answers[index] else "（未填寫）")
    else:
        doc.add_paragraph("（未填寫）")
    p = doc.add_paragraph()
    p.add_run("是否回報問題：").bold = True
    p.add_run("是" if reflection.get("has_issue") else "否")
    if reflection.get("has_issue"):
        p = doc.add_paragraph()
        p.add_run("問題類別：").bold = True
        p.add_run(str(reflection.get("issue_category") or ""))
        p = doc.add_paragraph()
        p.add_run("問題說明：").bold = True
        p.add_run(str(reflection.get("issue_description") or ""))

    # ── Section 6: Latest teacher grade ───────────────────────────────────────
    doc.add_heading("Section 6　老師最新批改結果", 1)
    grade = _xml_safe(getattr(sub, "latest_grade_data", None))
    if grade:
        summary = doc.add_table(rows=3, cols=2)
        summary.style = "Light Shading Accent 1"
        for index, (label, value) in enumerate((
            ("教師最後分", f"{grade['final_score']:g} / 100"),
            ("評分規準", f"{grade['rubric_name']} v{grade['rubric_version_number']}"),
            ("批改者", grade.get("grader_name") or grade.get("grader_student_id") or ""),
        )):
            summary.cell(index, 0).text = label
            summary.cell(index, 1).text = str(value)
        doc.add_heading("評分規準明細", 2)
        for item in grade.get("ratings") or []:
            doc.add_paragraph(
                f"{item.get('dimension_name', '')} · {item.get('criterion_name', '')}：{item.get('level_label', '')}",
                style="List Bullet",
            )
        doc.add_heading("總評", 2)
        doc.add_paragraph(grade.get("teacher_comment") or "")
        doc.add_heading("改善回饋", 2)
        doc.add_paragraph(grade.get("teacher_feedback") or "")
    else:
        doc.add_paragraph("（老師尚未批改）")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def _build_submission_audio_zip(student: User, sub) -> bytes:
    conv = safe_json_parse(sub.roleplay_conversation)
    turns = conv.get("turns", []) if conv else []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        audio_files = []
        for k in (sub.shadowing_tts_keys or []):
            if k.get("key"):
                audio_files.append((k["key"], f"section2_shadowing_tts_q{k.get('index', 0) + 1}.mp3"))
        for q in (sub.speaking1_questions or []):
            if q.get("audio_key"):
                audio_files.append((q["audio_key"], f"section2_shadowing_recording_q{q.get('index', 0) + 1}.mp3"))
        for t in turns:
            n = t.get("turn_number", 0)
            if t.get("interviewer_tts_key"):
                audio_files.append((t["interviewer_tts_key"], f"section3_turn{n}_interviewer.mp3"))
            if t.get("student_audio_key"):
                audio_files.append((t["student_audio_key"], f"section3_turn{n}_student.mp3"))

        for key, filename in audio_files:
            try:
                data = storage.download_file(key)
                zf.writestr(filename, data)
            except Exception:
                pass
    buf.seek(0)
    return buf.read()
