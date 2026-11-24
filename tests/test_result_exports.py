from datetime import datetime
from io import BytesIO
import json
from types import SimpleNamespace
from urllib.parse import quote
from zipfile import ZipFile

import pytest

from app.models import Assignment, User
from app.services import export_builders


def current_submission():
    questions = [f"Question {index + 1}?" for index in range(4)]
    answers = [
        {
            "index": index,
            "question": question,
            "text": f"This is answer {index + 1}.",
        }
        for index, question in enumerate(questions)
    ]
    feedback = {
        "questions": [
            {
                "index": index,
                "grammar_corrections": [
                    {
                        "original": "This answer",
                        "corrected": "This is my answer",
                        "explanation": "補上動詞與所有格。",
                    }
                ],
                "polished_sample": f"This is polished answer {index + 1}.",
            }
            for index in range(4)
        ],
        "organization_suggestions": ["先說重點", "補充例子", "簡短收尾"],
    }
    return SimpleNamespace(
        attempt_number=2,
        submitted_at=datetime(2026, 7, 25, 15, 30),
        job_profile_data={
            "desired_position": "軟體工程師",
            "role_description": "開發與維護系統",
            "required_competencies": "程式設計與溝通",
            "additional_notes": "",
        },
        questions_snapshot=questions,
        draft1_answers=answers,
        final_draft_answers=answers,
        draft2_ai_feedback=feedback,
        speaking1_questions=[
            {
                "index": index,
                "transcript": f"This is answer {index + 1}.",
                "audio_key": f"generation/audio/S001/1/shadowing_{index}.mp3",
            }
            for index in range(4)
        ],
        shadowing_tts_keys=[
            {
                "index": index,
                "key": f"generation/audio/S001/1/tts_{index}.mp3",
            }
            for index in range(4)
        ],
        roleplay_conversation=(
            '{"turns":[{"turn_number":1,'
            '"interviewer_question":"Tell me about yourself.",'
            '"student_transcript":"I am a student.",'
            '"interviewer_tts_key":"generation/audio/S001/1/interviewer.mp3",'
            '"student_audio_key":"generation/audio/S001/1/student.mp3"}]}'
        ),
        report_data=(
            '{"analysis":{"language_complexity":"良好","language_accuracy":"良好",'
            '"content_logic":"清楚","interview_strategy":"穩定"},'
            '"strengths":["內容完整"],"overall_suggestions":["增加具體例子"]}'
        ),
        reflection_data={
            "questions": ["你學到什麼？"],
            "answers": ["我學到如何準備面試。"],
            "has_issue": False,
        },
        latest_grade_data={
            "final_score": 88,
            "rubric_name": "評分規準",
            "rubric_version_number": 1,
            "grader_name": "王老師",
            "ratings": [
                {
                    "dimension_name": "內容",
                    "criterion_name": "完整度",
                    "level_label": "良好",
                }
            ],
            "teacher_comment": "表現良好",
            "teacher_feedback": "增加具體例子",
        },
    )


def test_professional_docx_contains_current_sections_and_branding():
    student = User(name="王小明", student_id="S001")
    assignment = Assignment(title="作業一：個人背景與動機")

    payload = export_builders.build_submission_docx(
        student,
        assignment,
        current_submission(),
    )

    with ZipFile(BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        styles_xml = archive.read("word/styles.xml").decode("utf-8")
        footer_xml = archive.read("word/footer1.xml").decode("utf-8")
    assert "SECTION 0" in document_xml
    assert "SECTION 6" in document_xml
    assert "教師最後成績" in document_xml
    assert "4F46E5" in document_xml
    assert "Microsoft JhengHei" in styles_xml
    assert "NUMPAGES" in footer_xml


def test_professional_docx_includes_personalized_fifth_roleplay_turn():
    submission = current_submission()
    submission.roleplay_conversation = json.dumps({
        "current_turn": 5,
        "turns": [
            {
                "turn_number": number,
                "source_question_index": number - 1,
                "interviewer_question": (
                    "What did helping that customer teach you about staying calm?"
                    if number == 5
                    else f"Core interview question {number}?"
                ),
                "student_transcript": f"Spoken answer {number}.",
                "interviewer_tts_key": None,
                "student_audio_key": None,
            }
            for number in range(1, 6)
        ],
    })

    payload = export_builders.build_submission_docx(
        User(name="王小明", student_id="S001"),
        Assignment(title="作業"),
        submission,
    )

    with ZipFile(BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert "第 5 輪" in document_xml
    assert "What did helping that customer teach you about staying calm?" in document_xml
    assert "Spoken answer 5." in document_xml


def test_professional_docx_handles_long_content_and_keeps_layout_rules():
    submission = current_submission()
    long_text = "This is a detailed interview answer with evidence and reflection. " * 120
    for answer in submission.draft1_answers + submission.final_draft_answers:
        answer["text"] = long_text
    submission.draft2_ai_feedback["questions"][0]["grammar_corrections"] = [
        {
            "original": f"Original sentence {index}",
            "corrected": f"Corrected sentence {index}",
            "explanation": "說明內容 " * 40,
        }
        for index in range(12)
    ]
    submission.latest_grade_data["ratings"] = [
        {
            "dimension_name": f"面向 {index}",
            "criterion_name": f"長評分項目 {index} " * 4,
            "level_label": "表現優良",
        }
        for index in range(20)
    ]
    submission.latest_grade_data["teacher_feedback"] = "後續改善建議 " * 300

    payload = export_builders.build_submission_docx(
        User(name="王小明", student_id="S001"),
        Assignment(title="長文字成果報告"),
        submission,
    )

    with ZipFile(BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert long_text[:120] in document_xml
    assert document_xml.index("SECTION 0") < document_xml.index("SECTION 6")
    assert 'w:w="11906"' in document_xml
    assert 'w:h="16838"' in document_xml
    assert "<w:keepNext" in document_xml
    assert "<w:cantSplit" in document_xml
    assert "<w:tblHeader" in document_xml


def test_docx_rejects_legacy_flat_feedback():
    submission = current_submission()
    submission.draft2_ai_feedback = {
        "grammar_corrections": [],
        "polished_sample": "legacy",
    }
    with pytest.raises(ValueError, match="題數"):
        export_builders.build_submission_docx(
            User(name="王小明", student_id="S001"),
            Assignment(title="作業"),
            submission,
        )


def test_docx_rejects_invalid_current_json_instead_of_downgrading():
    submission = current_submission()
    submission.roleplay_conversation = "{broken"
    with pytest.raises(ValueError, match="不是有效 JSON"):
        export_builders.build_submission_docx(
            User(name="王小明", student_id="S001"),
            Assignment(title="作業"),
            submission,
        )


def test_result_package_contains_word_all_audio_and_manifest(monkeypatch):
    submission = current_submission()
    monkeypatch.setattr(
        export_builders.storage.settings,
        "OBJECT_STORAGE_NAMESPACE",
        "generation",
    )
    monkeypatch.setattr(
        export_builders.storage,
        "download_file",
        lambda key: f"bytes:{key}".encode(),
    )

    payload = export_builders.build_submission_result_package(
        User(name="王小明", student_id="S001"),
        Assignment(title="作業"),
        submission,
    )

    with ZipFile(BytesIO(payload)) as archive:
        names = set(archive.namelist())
        manifest = archive.read("_檔案清單.txt").decode("utf-8")
    assert "學習成果報告.docx" in names
    assert "音檔/跟讀示範/跟讀示範_Q1.mp3" in names
    assert "音檔/學生跟讀/學生跟讀_Q4.mp3" in names
    assert "音檔/面試官語音/面試官_第1輪.mp3" in names
    assert "音檔/學生面試錄音/學生_第1輪.mp3" in names
    assert "跟讀示範：4 個" in manifest
    assert "學生面試錄音：1 個" in manifest


def test_result_package_is_all_or_nothing_when_audio_is_missing(monkeypatch):
    monkeypatch.setattr(
        export_builders.storage.settings,
        "OBJECT_STORAGE_NAMESPACE",
        "generation",
    )
    def fail_one(key):
        if key.endswith("shadowing_2.mp3"):
            raise FileNotFoundError(key)
        return b"audio"

    monkeypatch.setattr(export_builders.storage, "download_file", fail_one)
    with pytest.raises(RuntimeError, match="學生跟讀_Q3"):
        export_builders.build_submission_result_package(
            User(name="王小明", student_id="S001"),
            Assignment(title="作業"),
            current_submission(),
        )


def test_result_package_rejects_incomplete_audio_categories(monkeypatch):
    monkeypatch.setattr(
        export_builders.storage.settings,
        "OBJECT_STORAGE_NAMESPACE",
        "generation",
    )
    submission = current_submission()
    submission.shadowing_tts_keys = submission.shadowing_tts_keys[:3]
    monkeypatch.setattr(export_builders.storage, "download_file", lambda _key: b"audio")
    with pytest.raises(ValueError, match="跟讀示範音檔必須完整包含 4 題"):
        export_builders.build_submission_result_package(
            User(name="王小明", student_id="S001"),
            Assignment(title="作業"),
            submission,
        )


def test_unicode_attachment_filename_is_latin1_safe_after_rfc5987_encoding():
    filename = "S001_第2次_音檔.zip"
    header = f"attachment; filename*=UTF-8''{quote(filename)}"
    assert header.encode("latin-1")
    assert "%E7%AC%AC2%E6%AC%A1" in header
