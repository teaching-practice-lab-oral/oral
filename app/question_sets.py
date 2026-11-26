"""Curated public interview questions and their question-specific scaffolds."""
from __future__ import annotations

import unicodedata
from collections import OrderedDict
from copy import deepcopy
from typing import Iterable


DEFAULT_QUESTION_SET_KEY = "background_motivation"
CUSTOM_QUESTION_MAX_CHARS = 500


def contains_non_latin_script(text: str | None) -> bool:
    """Return whether text contains non-Latin letters or CJK/full-width punctuation."""
    for char in text or "":
        codepoint = ord(char)
        if 0x3000 <= codepoint <= 0x303F or 0xFF00 <= codepoint <= 0xFFEF:
            return True
        if char.isalpha() and "LATIN" not in unicodedata.name(char, ""):
            return True
    return False


def _item(
    question: str,
    goal: str,
    steps: tuple[str, ...],
    evidence: str,
    starters: tuple[str, ...],
) -> dict:
    return {
        "question": question,
        "goal": goal,
        "steps": list(steps),
        "evidence": evidence,
        "starters": list(starters),
    }


QUESTION_SETS = OrderedDict(
    [
        (
            "background_motivation",
            {
                "label": "個人背景與動機",
                "items": [
                    _item(
                        "Please briefly introduce yourself and your academic background.",
                        "讓面試官快速了解你目前的身分、學術背景，以及其中與目標職位相關的重點。",
                        ("說明目前身分與就讀領域", "簡述學校、科系或重要學習經驗", "用一句話點出與目標職位的連結"),
                        "挑一項最能代表你的課程、專題或校園經驗，不必逐項重述履歷。",
                        ("I am currently…", "My academic background is in…", "Through my studies, I have developed…"),
                    ),
                    _item(
                        "Why did you choose your major, and how does it relate to this position?",
                        "說明選擇科系的真實動機，並把所學能力具體連結到目標職位。",
                        ("說明選擇科系的原因", "點出一項相關課程、知識或能力", "解釋這項學習如何用在職位上"),
                        "回想當初選系的具體原因，再從所學中挑一項符合職位需求的能力。",
                        ("I chose my major because…", "Through my major, I learned…", "This relates to the position because…"),
                    ),
                    _item(
                        "Why are you interested in this industry and this position?",
                        "分別說明產業與職位吸引你的原因，並連結自己的經驗或發展方向。",
                        ("指出產業吸引你的具體原因", "說明職位中感興趣的工作內容", "連結自己的能力、經驗或目標"),
                        "各挑一項可由產業趨勢與職位描述支持的理由，避免只說很有興趣。",
                        ("I am interested in this industry because…", "This position appeals to me because…", "It matches my…"),
                    ),
                    _item(
                        "Do you have any work or internship experience? What were your main responsibilities?",
                        "清楚交代工作或實習經驗與主要職責；沒有正式經驗時，也能誠實連結相關實作經歷。",
                        ("直接回答是否有工作或實習經驗", "說明職稱、單位或工作情境", "列出主要職責與一項學習"),
                        "挑一段最相關的工作、實習、打工或專案經驗；若沒有正式經驗，可說明課程、社團或志工中的相關責任。",
                        ("I have experience working as…", "My main responsibilities included…", "From this experience, I learned…"),
                    ),
                ],
            },
        ),
        (
            "skills_achievements",
            {
                "label": "技能、專業能力與成就",
                "items": [
                    _item(
                        "What skills do you have that are relevant to this position?",
                        "挑出職位真正需要的能力，並用具體證據說明自己如何使用這些能力。",
                        ("點出一至兩項相關技能", "說明曾在什麼情境使用", "連結到職位中的實際用途"),
                        "從職位所需職能中挑一至兩項你已有真實學習或使用經驗的能力。",
                        ("One relevant skill I have is…", "I used this skill when…", "In this position, it would help me…"),
                    ),
                    _item(
                        "What is your proudest accomplishment during your college years?",
                        "用一項大學期間的具體成果呈現目標、個人行動、結果與學習。",
                        ("交代成果的背景與目標", "說明自己的關鍵行動", "說出結果及學到什麼"),
                        "選一件大學期間有明確成果，且能分辨出你個人貢獻的課堂、專題、社團或工作經驗。",
                        ("My proudest accomplishment in college was…", "My role was to…", "As a result…"),
                    ),
                    _item(
                        "What is your greatest strength, and what is one area you would like to improve?",
                        "用證據支持一項優勢，並把待改善處說成正在採取行動的成長目標。",
                        ("說出一項與職位相關的優勢", "用真實例子證明", "說明一項待改善處與目前行動"),
                        "找一件能證明優勢的事，再選一項不會否定職位核心能力的真實改善目標。",
                        ("My greatest strength is…", "For example…", "I am improving… by…"),
                    ),
                    _item(
                        "Why should we hire you?",
                        "整合職位需求、個人證據與可帶來的貢獻，提出可信而不誇大的錄用理由。",
                        ("指出自己符合的一至兩項職位需求", "用經驗或成果支持", "說明能為團隊帶來的貢獻"),
                        "從職位描述挑出最重要的需求，再找出能證明你已具備相關能力的例子。",
                        ("You should hire me because…", "My experience in… shows that…", "I can contribute by…"),
                    ),
                ],
            },
        ),
        (
            "situational_problem_solving",
            {
                "label": "情境與問題解決能力",
                "items": [
                    _item(
                        "Describe a major challenge you faced in school or work and how you handled it.",
                        "用具體情境呈現你如何分析重大挑戰、採取行動並從結果中學習。",
                        ("交代挑戰、目標與限制", "說明自己採取的關鍵行動", "說出結果與學習"),
                        "選一個在學校或工作中確實需要你調整做法、投入努力或尋求協助的重大挑戰。",
                        ("A major challenge I faced was…", "To handle it, I…", "As a result…"),
                    ),
                    _item(
                        "How do you handle stress and pressure?",
                        "說明可持續的壓力管理方法，並用實際情境證明你能維持工作品質。",
                        ("說明面對壓力時的基本做法", "舉例如何排序、溝通或調整", "說出方法帶來的結果"),
                        "回想一次有期限、工作量或協作壓力的情境，以及你實際採取的應對方法。",
                        ("I handle stress by…", "For example, when…", "This helps me…"),
                    ),
                    _item(
                        "Can you give an example of a mistake you made and what you learned from it?",
                        "誠實說明一項真實錯誤、補救行動與後續改變，展現承擔責任和學習能力。",
                        ("交代錯誤與造成的影響", "說明如何承認並補救", "指出學到什麼及如何避免再發生"),
                        "選一項你能承擔責任、確實有補救，而且不涉及嚴重道德問題的真實錯誤。",
                        ("One mistake I made was…", "I took responsibility by…", "I learned that…"),
                    ),
                    _item(
                        "How would you handle a coworker who is difficult to work with?",
                        "提出尊重、就事論事且能維持合作的處理方式，並知道何時尋求適當協助。",
                        ("先了解具體行為與彼此觀點", "私下溝通並聚焦共同目標", "持續影響工作時留下紀錄並適當求助"),
                        "聚焦可觀察的工作行為與影響，不替對方貼標籤，也不要假設衝突一定是對方的錯。",
                        ("First, I would try to understand…", "I would discuss the issue by…", "If the problem continued, I would…"),
                    ),
                ],
            },
        ),
        (
            "work_attitude_soft_skills",
            {
                "label": "工作態度與職場軟實力",
                "items": [
                    _item(
                        "Do you prefer working independently or with a team? Why?",
                        "表達工作偏好，同時證明你能依任務需要在獨立與合作之間調整。",
                        ("先直接說明偏好", "用一個經驗解釋原因", "補充何時會採用另一種方式"),
                        "選一個能看出你如何完成個人責任或與他人協作的例子。",
                        ("I generally prefer… because…", "For example…", "However, when the task requires…, I…"),
                    ),
                    _item(
                        "Describe a time you had a disagreement with your manager or a team member. How was it resolved?",
                        "說明你如何理解歧見、採取溝通行動並讓合作繼續，而不是把責任推給別人。",
                        ("交代歧見與雙方觀點", "說明自己的溝通或協調行動", "說出如何解決及後續反思"),
                        "回想一次與主管或團隊成員真正存在不同意見，而且最後有具體處理結果的經驗。",
                        ("We disagreed about…", "I addressed it by…", "The issue was resolved when…"),
                    ),
                    _item(
                        "What core work value or principle is most important to you, and why?",
                        "用實際行為說明一項核心工作價值，並解釋它如何影響你的工作方式。",
                        ("點出一項核心價值並說明含義", "用真實行為或經驗證明", "解釋它對工作成果或合作的重要性"),
                        "選一項你曾在課堂、社團或工作中真正實踐過，而且能舉例的核心價值。",
                        ("The core work value I care about most is…", "I demonstrated this when…", "It is important because…"),
                    ),
                    _item(
                        "How do you respond to constructive criticism from a professor, manager, or peer?",
                        "展現你能冷靜理解回饋、確認改善方向，並把建議轉化成具體行動。",
                        ("先傾聽並確認回饋重點", "需要時詢問例子或改善標準", "採取行動並追蹤改進結果"),
                        "準備一個你曾收到建設性回饋、調整做法並有所改善的真實例子。",
                        ("When I receive constructive criticism, I…", "I make sure I understand by…", "Then, I apply it by…"),
                    ),
                ],
            },
        ),
        (
            "company_future",
            {
                "label": "企業了解、未來展望與提問",
                "items": [
                    _item(
                        "What do you know about our industry?",
                        "呈現你對目標產業做過基本研究，並能說明趨勢、挑戰或所需能力與自己的關係。",
                        ("說出一至兩項已查證的產業資訊", "解釋其趨勢或挑戰為何重要", "連結到自己的準備或目標職位"),
                        "使用自己實際查到的產業現況、趨勢或挑戰；沒有資料時不要猜測。",
                        ("From my research, I learned that the industry…", "One important trend is…", "This matters to me because…"),
                    ),
                    _item(
                        "What do you know about our company, and why do you want to work here?",
                        "用已查證的公司資訊說明你確實做過功課，並連結想加入的具體理由。",
                        ("說出已查證的公司、產品、服務或文化資訊", "解釋這項資訊為何吸引你", "連結自己的能力、價值或貢獻"),
                        "從公司官方資訊挑一至兩項與目標職位有關的事實，避免套用任何公司都適用的理由。",
                        ("From my research, I understand that your company…", "I want to work here because…", "I could contribute by…"),
                    ),
                    _item(
                        "What are your career goals for the next 3 to 5 years, and how does this job align with them?",
                        "提出具體但保有彈性的三至五年成長方向，並清楚說明這份工作如何支持該方向。",
                        ("說明三至五年想建立的能力或貢獻", "指出這份工作的相關學習與責任", "解釋兩者如何連結"),
                        "從目標職位所需職能中挑一項想深化的能力，不必保證特定職稱或升遷。",
                        ("Over the next three to five years, I hope to…", "This job would allow me to…", "That aligns with my goal because…"),
                    ),
                    _item(
                        "Do you have any questions for us?",
                        "提出一個有助理解工作、團隊或成功標準的問題，展現你對職位做過思考。",
                        ("選定真正想了解的工作資訊", "提出一個開放而具體的問題", "避免詢問公開資料已有明確答案的內容"),
                        "從工作內容、團隊合作、前三個月目標、培訓或成功標準中選一項。",
                        ("Yes, I would like to ask…", "Could you tell me more about…", "How does the team…"),
                    ),
                ],
            },
        ),
    ]
)

PRESET_TITLE_TO_QUESTION_SET = {
    "作業一：個人背景與動機": "background_motivation",
    "作業二：技能、專業能力與成就": "skills_achievements",
    "作業三：情境與問題解決能力": "situational_problem_solving",
    "作業四：工作態度與職場軟實力": "work_attitude_soft_skills",
    "作業五：企業了解、未來展望與提問": "company_future",
}


def question_set_questions(key: str) -> list[str]:
    row = QUESTION_SETS.get(key)
    if row is None:
        raise KeyError(key)
    return [item["question"] for item in row["items"]]


def question_set_scaffold_blueprints(key: str) -> list[dict]:
    row = QUESTION_SETS.get(key)
    if row is None:
        raise KeyError(key)
    return deepcopy(row["items"])


def default_questions() -> list[str]:
    return question_set_questions(DEFAULT_QUESTION_SET_KEY)


def normalize_custom_questions(questions: Iterable[str] | None) -> list[str]:
    values = [str(question or "").strip() for question in (questions or [])]
    if len(values) != 4 or any(not value for value in values):
        raise ValueError("自訂題組必須恰好填寫 4 題，且每題不可空白。")
    if any(len(value) > CUSTOM_QUESTION_MAX_CHARS for value in values):
        raise ValueError(f"自訂題目每題不可超過 {CUSTOM_QUESTION_MAX_CHARS} 個字元。")
    if any(contains_non_latin_script(value) for value in values):
        raise ValueError("自訂面試題目必須使用英文，不可包含中文或其他非拉丁文字。")
    return values


def question_set_catalog() -> list[dict]:
    return [
        {"key": key, "label": row["label"], "questions": question_set_questions(key)}
        for key, row in QUESTION_SETS.items()
    ]
