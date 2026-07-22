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
                        "Please briefly introduce yourself.",
                        "讓面試官快速知道你是誰、有哪些相關背景，以及你和目標職位的連結。",
                        ("說明目前身分或專業背景", "挑一項與職位最相關的經驗或能力", "用一句話連回目標職位"),
                        "選一項最能代表你、也和職位相關的學習或工作經驗。",
                        ("I am currently…", "One relevant experience I have is…", "This is relevant to the position because…"),
                    ),
                    _item(
                        "Could you tell me about your educational background or work experience?",
                        "從教育或工作經歷中挑出與職位最相關的部分，而不是逐項重述履歷。",
                        ("交代經歷的情境與內容", "說明自己實際做了什麼", "說明學到的能力如何用在職位上"),
                        "回想一門課、專題、社團、打工或實習中真正做過的工作。",
                        ("During my…", "My main responsibility was…", "From this experience, I learned…"),
                    ),
                    _item(
                        "Why are you interested in applying for this position?",
                        "說清楚你理解這份工作的哪個部分，以及它為何符合你的動機與能力。",
                        ("指出吸引你的具體工作內容", "連結自己的動機或相關經驗", "說明希望如何貢獻或成長"),
                        "從職位描述中挑一項你真的想做、也說得出原因的工作內容。",
                        ("I am interested in this position because…", "This role matches my experience in…", "I hope to contribute by…"),
                    ),
                    _item(
                        "What is your greatest strength, and what is one area you would like to improve?",
                        "用證據支持一項優勢，並把待改善處說成正在採取行動的成長目標。",
                        ("說出一項與職位相關的優勢", "用真實例子證明", "說明一項待改善處與目前行動"),
                        "找一件能證明優勢的事，再選一項不會否定職位核心能力的真實改善目標。",
                        ("One of my strengths is…", "For example…", "I am currently improving… by…"),
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
                        "What are your key professional skills?",
                        "挑出職位真正需要的能力，並用證據說明自己如何使用這些能力。",
                        ("點出一至兩項核心技能", "說明曾在什麼情境使用", "連結到職位中的實際用途"),
                        "從職位所需職能中挑一項你已有真實學習或使用經驗的能力。",
                        ("One of my key skills is…", "I used this skill when…", "In this position, it would help me…"),
                    ),
                    _item(
                        "Tell me about a specific achievement you are proud of.",
                        "用一件具體成果呈現你的目標、行動、結果與學習，而不是只說自己表現很好。",
                        ("交代目標或挑戰", "說明自己的關鍵行動", "說出結果及學到什麼"),
                        "選一件有明確成果，而且能分辨出你個人貢獻的課堂、社團或工作經驗。",
                        ("One achievement I am proud of is…", "My role was to…", "As a result…"),
                    ),
                    _item(
                        "How do your skills and experience match the requirements of this position?",
                        "把一項工作需求、一項個人能力與一個真實證據清楚對應起來。",
                        ("指出一項職位需求", "說明對應的能力或經驗", "用具體例子證明適配"),
                        "從 job-profile 的工作內容與職能各挑一項，找出兩者可由哪段經驗連起來。",
                        ("This position requires…", "My experience in… has prepared me to…", "For example…"),
                    ),
                    _item(
                        "What skill are you currently developing, and how are you improving it?",
                        "呈現你知道自己的能力缺口，並正在用可檢查的方法持續改善。",
                        ("說明正在發展的技能與原因", "描述具體練習或學習方法", "說明如何確認進步"),
                        "選一項和目標職位有關、目前確實正在練習的技能。",
                        ("I am currently developing…", "To improve it, I…", "I track my progress by…"),
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
                        "Tell me about a time you had a conflict with a classmate, colleague, or supervisor. How did you handle it?",
                        "說明你如何理解歧見、採取溝通行動並讓合作繼續，而不是把責任推給別人。",
                        ("交代歧見與雙方立場", "說明自己的溝通或協調行動", "說出結果與反思"),
                        "回想一次真正存在不同意見、而你有採取行動處理的合作經驗。",
                        ("We disagreed about…", "I handled it by…", "In the end…"),
                    ),
                    _item(
                        "Describe a stressful work or study situation. How did you manage it?",
                        "呈現你如何辨識壓力來源、安排優先順序並完成重要工作。",
                        ("交代壓力情境與限制", "說明如何排序、求助或調整", "說出結果與下次做法"),
                        "選一個有時間、工作量或協作壓力，而且你確實做出調整的情境。",
                        ("A stressful situation I faced was…", "I managed it by…", "This helped me…"),
                    ),
                    _item(
                        "Imagine that you face an unexpected problem while performing one of the duties of your target position. What would you do?",
                        "根據目標職位的實際工作，提出安全、合理並知道何時回報的處理順序。",
                        ("先釐清問題與影響", "評估選項並採取行動", "需要時回報並確認結果"),
                        "從 job-profile 挑一項工作內容，想像其中可能出現但不必虛構成自己經歷的問題。",
                        ("First, I would…", "Then, I would…", "If necessary, I would…"),
                    ),
                    _item(
                        "How do you make decisions when facing a difficult problem?",
                        "說明你如何蒐集資訊、比較選項並用明確判準做決定。",
                        ("確認目標與必要資訊", "比較選項、風險與影響", "做出決定並檢查結果"),
                        "回想一次需要權衡時間、品質、合作或風險的真實決定。",
                        ("When I face a difficult problem, I first…", "I compare…", "After deciding, I…"),
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
                        "How do you contribute to a team and handle disagreements?",
                        "說明你在團隊中的具體貢獻，以及意見不同時如何讓工作繼續。",
                        ("指出自己常做的團隊貢獻", "說明處理歧見的方法", "用合作結果作結"),
                        "回想一次你有明確分工、提出意見或協助整合團隊工作的經驗。",
                        ("In a team, I usually contribute by…", "When we disagree, I…", "This helps the team…"),
                    ),
                    _item(
                        "How do you manage stress in a fast-paced environment?",
                        "呈現你在變化快速時仍能排序、溝通並維持工作品質的方法。",
                        ("說明如何判斷優先順序", "描述使用的組織或溝通方法", "說明如何確認重要工作完成"),
                        "找一個同時有多項任務、期限或臨時變動的真實情境。",
                        ("I manage stress by…", "I prioritize…", "To maintain quality, I…"),
                    ),
                    _item(
                        "What professional value or principle is most important to you? Why?",
                        "用實際行為說明一項職業價值，而不是只說抽象形容詞。",
                        ("點出一項價值並解釋含義", "用真實行為或經驗證明", "連結到目標職位的工作方式"),
                        "選一項你曾在課堂、社團或工作中真正實踐過的價值。",
                        ("The professional value I care about most is…", "I demonstrated this when…", "In this position, it would mean…"),
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
                        "What do you know about the company or industry you want to work in?",
                        "呈現你做過基本研究，並能說明資訊和目標職位的關係。",
                        ("說出已查證的公司或產業資訊", "解釋它為何重要", "連結到目標職位或自己的準備"),
                        "使用自己實際查到的公司、產品、服務或產業資訊；沒有資料時不要猜測。",
                        ("From my research, I learned that…", "This is important because…", "For this position…"),
                    ),
                    _item(
                        "Why are you interested in this position and company?",
                        "分開說明職位與公司的吸引力，再連結自己能投入的能力或目標。",
                        ("說明職位吸引你的具體內容", "說明公司吸引你的已知原因", "連結自己的能力或貢獻"),
                        "各挑一項可由職位描述與公司公開資訊支持的理由。",
                        ("I am interested in this position because…", "I am also interested in the company because…", "I could contribute by…"),
                    ),
                    _item(
                        "What are your career goals for the next three to five years?",
                        "提出和職位相關、具體但保有彈性的能力與工作成長方向。",
                        ("說明近期要建立的能力或貢獻", "描述三至五年的成長方向", "連結目前職位如何支持這個方向"),
                        "從目標職位所需職能中挑一項想深化的能力，不必保證特定職稱。",
                        ("In the short term, I hope to…", "Over the next three to five years…", "This position would help me…"),
                    ),
                    _item(
                        "What question would you like to ask the interviewer?",
                        "提出一個有助理解工作、團隊或成功標準的問題，展現你對職位做過思考。",
                        ("選定真正想了解的工作資訊", "提出一個開放而具體的問題", "避免詢問公開資料已有明確答案的內容"),
                        "從工作內容、團隊合作、前三個月目標、培訓或成功標準中選一項。",
                        ("I would like to ask…", "Could you tell me more about…", "How does the team…"),
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
