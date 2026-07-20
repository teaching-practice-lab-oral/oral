from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException


# Older/custom rubrics may still use one shared five-level scale.  New rubrics
# can define an exact point scale on each criterion instead.
RUBRIC_LEVELS = [
    {"value": 4, "label": "表現優良", "ratio": 1.0, "anchor": "回答完整、具體且前後一致，能自行完成各項要求。"},
    {"value": 3, "label": "符合標準", "ratio": 0.75, "anchor": "大致完成各項要求，少數不一致或錯誤不影響整體表現。"},
    {"value": 2, "label": "尚待加強", "ratio": 0.5, "anchor": "已完成部分要求，但有些問題反覆出現，影響表達的清楚度或完整性，仍需要一些協助。"},
    {"value": 1, "label": "基礎待提升", "ratio": 0.25, "anchor": "只完成少部分要求，內容較零散，仍需明確引導才能完成。"},
    {"value": 0, "label": "無法評分", "ratio": 0.0, "anchor": "未作答、內容無法判讀，或提供的內容不足以評分。"},
]


def _score_level(points: int, label: str, anchor: str) -> dict[str, Any]:
    return {"value": points, "label": label, "points": points, "anchor": anchor}


def _criterion(
    key: str,
    name: str,
    points: int,
    description: str,
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "points": points,
        "description": description,
        "levels": levels,
    }


def _single_criterion_dimension(
    key: str,
    name: str,
    points: int,
    description: str,
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "weight": points,
        "criteria": [_criterion(key, name, points, description, levels)],
    }


# The system rubric is an analytic rubric for the complete AI interview
# learning cycle.  Its constructs combine the qualitative aspects of spoken
# language in CEFR/IELTS/TOEFL, job-related evidence in structured interviews,
# and observable uptake of feedback during revision and reflection.
DEFAULT_RUBRIC_DEFINITION: dict[str, Any] = {
    "levels": RUBRIC_LEVELS,
    "notes": [
        "評分證據應整合職缺設定、最終書面回答、跟讀錄音、角色扮演與心得反思，不以單一次表現或文法錯誤數量決定總分。",
        "發音以可理解度與聽者所需努力為準；口音本身不扣分。如逐字稿可能有辨識誤差，應回聽原始錄音後再判定。",
        "AI 回饋不是標準答案；「回饋運用與反思」評量學生能否理解、選擇、改寫並連結自己的真實經驗，而非是否照抄建議範文。",
        "設計依據包含 CEFR 口語質性面向、IELTS／TOEFL 口語分析指標、OPM 結構式面試行為錨點，以及回饋素養研究。",
    ],
    "dimensions": [
        _single_criterion_dimension(
            "content_job_fit",
            "回答內容與職位連結",
            25,
            "綜合最終書面回答與角色扮演，評量是否切題，並能把個人經驗、能力與應徵職位或公司需求具體連結。",
            [
                _score_level(25, "完整達成", "能直接回答各題，清楚連結職位需求與個人能力，並以具體且前後一致的經驗、理由或成果支持重點。"),
                _score_level(20, "穩定達成", "多數回答切題且能連結職位，至少提供一項合適細節或例子；少數內容略為概括。"),
                _score_level(15, "基本達成", "大致回應題目，也提到職位或個人能力，但理由、例子或成果不夠具體完整。"),
                _score_level(10, "初步呈現", "回答常停留在簡短敘述或條列，部分偏題，個人經驗與職位需求的連結薄弱。"),
                _score_level(0, "證據不足", "未作答、內容與題目無關，或可判讀的內容不足以評量。"),
            ],
        ),
        _single_criterion_dimension(
            "organization_strategy",
            "組織與面試策略",
            15,
            "評量回答是否先表明重點，再以理由、例子或結果展開，並以適合面試情境的方式清楚、精簡地完成回答。",
            [
                _score_level(15, "完整達成", "重點明確，理由與例子依序展開，銜接自然且收束得宜；回答完整而不冗長。"),
                _score_level(12, "穩定達成", "回答順序清楚，重點與細節大致連貫；偶有重複、跳接或收尾稍弱。"),
                _score_level(9, "基本達成", "可辨認主要意思，能用簡單連接方式組織內容，但部分細節順序不穩或發展不足。"),
                _score_level(6, "初步呈現", "內容較零散或重複，缺少明確的重點—說明—例子關係，需要聽者自行推測連結。"),
                _score_level(0, "證據不足", "沒有可辨認的回答結構，或內容不足以評量。"),
            ],
        ),
        _single_criterion_dimension(
            "language_use",
            "語言範圍與準確度",
            20,
            "綜合最終書面回答與角色扮演逐字稿，評量詞彙、職場語域、句型範圍與文法控制是否足以清楚傳達意思。",
            [
                _score_level(20, "完整達成", "能靈活使用足夠且合宜的職場詞彙與多種句型；即使有少量錯誤，也不影響清楚、精確地表意。"),
                _score_level(16, "穩定達成", "用字大致合宜，能使用簡單句與部分較複雜句型；文法錯誤偶爾出現但不妨礙理解。"),
                _score_level(12, "基本達成", "熟悉主題時有足夠詞彙表達，主要使用簡單句型；反覆錯誤或用字不精確偶爾造成理解負擔。"),
                _score_level(8, "初步呈現", "詞彙與句型有限且重複，文法或用字問題經常使意思不完整或不易理解。"),
                _score_level(0, "證據不足", "沒有足夠英文內容，或語言片段無法形成可理解的意思。"),
            ],
        ),
        _single_criterion_dimension(
            "spoken_delivery",
            "口語表達與可理解度",
            20,
            "綜合跟讀與角色扮演原始錄音，評量發音清楚度、停頓、節奏、重音、語調與持續表達；不以接近母語者口音為標準。",
            [
                _score_level(20, "完整達成", "語音清楚且能持續表達，速度、停頓、重音與語調能支持意思，整體幾乎不增加聽者理解負擔。"),
                _score_level(16, "穩定達成", "整體容易理解且大致流暢；少量發音、節奏或停頓問題不影響主要訊息。"),
                _score_level(12, "基本達成", "多數內容可以理解，但停頓較多、節奏不穩或部分發音問題使聽者需要一些努力。"),
                _score_level(8, "初步呈現", "表達常中斷或過度依賴逐字念讀，發音與節奏問題反覆遮蔽部分意思，聽者需要明顯努力。"),
                _score_level(0, "證據不足", "未提供可用錄音，或大部分語音無法理解。"),
            ],
        ),
        _single_criterion_dimension(
            "interaction_response",
            "互動理解與臨場應對",
            10,
            "依角色扮演評量是否理解問題、直接回應、維持對話並處理追問；聽不懂或一時說不清楚時，能否使用澄清或換句話說等策略。",
            [
                _score_level(10, "完整達成", "能準確理解並直接回應問題，自然接續追問；遇到困難時會主動澄清、確認或換句話說以維持對話。"),
                _score_level(8, "穩定達成", "多數問題都能適切回應並維持對話；偶有延遲或誤解，但通常能自行調整。"),
                _score_level(6, "基本達成", "能處理熟悉且可預期的問題；面對追問時回答較短或不完整，偶爾依賴提示。"),
                _score_level(4, "初步呈現", "常未掌握問題重點，回答彼此孤立；遇到誤解或表達困難時少有修復策略。"),
                _score_level(0, "證據不足", "未參與角色扮演，或沒有足夠互動內容可供評量。"),
            ],
        ),
        _single_criterion_dimension(
            "feedback_reflection",
            "回饋運用與學習反思",
            10,
            "比較草稿、AI 回饋、最終回答與心得，評量學生能否判斷並運用建議、保留個人真實內容，並以練習證據提出後續行動。",
            [
                _score_level(10, "完整達成", "能選擇並轉化合適回饋，最終回答保留自己的真實經驗；反思引用具體練習證據、分析原因並提出可執行的改進計畫。"),
                _score_level(8, "穩定達成", "多數修改能回應回饋且符合個人情境；反思包含具體例子與可行的下一步。"),
                _score_level(6, "基本達成", "看得出有修改，但多集中在表面語言問題；反思能指出優缺點，後續做法仍較概括。"),
                _score_level(4, "初步呈現", "修改很少或大多直接沿用建議範文，難以看出判斷過程；反思籠統，缺少證據或明確行動。"),
                _score_level(0, "證據不足", "未完成最終修訂或心得，或內容不足以判斷是否理解並運用回饋。"),
            ],
        ),
    ],
}


def default_rubric_definition() -> dict[str, Any]:
    return deepcopy(DEFAULT_RUBRIC_DEFINITION)


def _clean_key(value: Any, field_label: str) -> str:
    key = str(value or "").strip()
    if not key or len(key) > 64 or not key.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail=f"{field_label}代碼格式錯誤")
    return key


def _clean_criterion_levels(value: Any, criterion_name: str, max_points: int) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) < 2:
        raise HTTPException(status_code=400, detail=f"{criterion_name} 至少需要兩個評分級距")
    if len(value) > 12 or any(not isinstance(level, dict) for level in value):
        raise HTTPException(status_code=400, detail=f"{criterion_name} 的評分級距格式錯誤")

    clean_levels: list[dict[str, Any]] = []
    seen_values: set[int] = set()
    seen_points: set[Decimal] = set()
    for level in value:
        try:
            level_value = int(level.get("value"))
            awarded = Decimal(str(level.get("points")))
        except (InvalidOperation, TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{criterion_name} 的級距分數必須是數字")
        label = str(level.get("label") or "").strip()
        anchor = str(level.get("anchor") or "").strip()
        if level_value in seen_values or awarded in seen_points:
            raise HTTPException(status_code=400, detail=f"{criterion_name} 的級距分數不可重複")
        if not label or not anchor:
            raise HTTPException(status_code=400, detail=f"{criterion_name} 的級距名稱與說明皆為必填")
        if awarded < 0 or awarded > max_points or awarded != awarded.to_integral_value():
            raise HTTPException(status_code=400, detail=f"{criterion_name} 的級距分數必須是 0 到 {max_points} 之間的整數")
        seen_values.add(level_value)
        seen_points.add(awarded)
        points_value = int(awarded)
        clean_levels.append({
            "value": level_value,
            "label": label[:120],
            "points": points_value,
            "anchor": anchor[:1000],
        })

    awarded_values = [Decimal(str(level["points"])) for level in clean_levels]
    if awarded_values != sorted(awarded_values, reverse=True):
        raise HTTPException(status_code=400, detail=f"{criterion_name} 的級距必須由高分排到低分")
    if awarded_values[0] != Decimal(max_points) or awarded_values[-1] != 0:
        raise HTTPException(status_code=400, detail=f"{criterion_name} 的級距必須包含滿分 {max_points} 與 0 分")
    return clean_levels


def validate_rubric_definition(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("dimensions"), list) or not value["dimensions"]:
        raise HTTPException(status_code=400, detail="評分規準格式不完整，至少需要一個評分面向。")
    dimensions = value["dimensions"]
    if len(dimensions) > 20 or any(not isinstance(dimension, dict) for dimension in dimensions):
        raise HTTPException(status_code=400, detail="每個大項都必須是物件，且需要完整設定。")

    dimension_keys: set[str] = set()
    criterion_keys: set[str] = set()
    total_weight = 0
    clean_dimensions = []
    for dimension in dimensions:
        dimension_key = _clean_key(dimension.get("key"), "評分面向")
        dimension_name = str(dimension.get("name") or "").strip()
        if dimension_key in dimension_keys:
            raise HTTPException(status_code=400, detail=f"評分面向代碼重複：{dimension_key}")
        if not dimension_name:
            raise HTTPException(status_code=400, detail="評分面向名稱為必填")
        dimension_keys.add(dimension_key)
        try:
            weight = int(dimension.get("weight"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="各大項配分必須是整數")
        if weight <= 0:
            raise HTTPException(status_code=400, detail="各大項配分必須大於 0")
        criteria = dimension.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise HTTPException(status_code=400, detail=f"{dimension_name} 至少需要一個評分項目")
        if any(not isinstance(criterion, dict) for criterion in criteria):
            raise HTTPException(status_code=400, detail=f"{dimension_name} 的每個評分項目都必須是物件")
        clean_criteria = []
        points_total = 0
        for criterion in criteria:
            key = _clean_key(criterion.get("key"), "評分項目")
            name = str(criterion.get("name") or "").strip()
            description = str(criterion.get("description") or "").strip()
            try:
                points = int(criterion.get("points"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="各評分項目的配分必須是整數")
            if key in criterion_keys:
                raise HTTPException(status_code=400, detail=f"評分項目代碼重複：{key}")
            if not name or not description or points <= 0:
                raise HTTPException(status_code=400, detail="評分項目的名稱、說明與正整數配分皆為必填")
            criterion_keys.add(key)
            points_total += points
            clean_criterion = {
                "key": key,
                "name": name[:120],
                "points": points,
                "description": description[:1000],
            }
            criterion_levels = _clean_criterion_levels(criterion.get("levels"), name, points)
            if criterion_levels is not None:
                clean_criterion["levels"] = criterion_levels
            clean_criteria.append(clean_criterion)
        if points_total != weight:
            raise HTTPException(status_code=400, detail=f"{dimension_name} 的各項配分總和必須等於此面向的配分 {weight}")
        total_weight += weight
        clean_dimensions.append({
            "key": dimension_key,
            "name": dimension_name[:80],
            "weight": weight,
            "criteria": clean_criteria,
        })
    if total_weight != 100:
        raise HTTPException(status_code=400, detail="所有評分面向的配分總和必須為 100")

    notes = value.get("notes") or []
    if not isinstance(notes, list):
        raise HTTPException(status_code=400, detail="評分注意事項格式錯誤")
    clean_notes = [str(note).strip()[:1000] for note in notes if str(note).strip()]
    return {"levels": deepcopy(RUBRIC_LEVELS), "notes": clean_notes[:10], "dimensions": clean_dimensions}


def calculate_rubric_score(definition: dict[str, Any], ratings: dict[str, int]) -> tuple[Decimal, list[dict[str, Any]]]:
    normalized = validate_rubric_definition(definition)
    expected = {
        criterion["key"]
        for dimension in normalized["dimensions"]
        for criterion in dimension["criteria"]
    }
    if set(ratings) != expected:
        raise HTTPException(status_code=400, detail="每一個評分項目都必須選擇等級")
    shared_level_map = {int(item["value"]): item for item in normalized["levels"]}
    score = Decimal("0")
    result = []
    for dimension in normalized["dimensions"]:
        for criterion in dimension["criteria"]:
            criterion_level_map = {
                int(item["value"]): item for item in criterion.get("levels", [])
            } or shared_level_map
            try:
                level_value = int(ratings[criterion["key"]])
                level = criterion_level_map[level_value]
            except (KeyError, TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{criterion['name']} 的等級無效")
            if "points" in level:
                awarded = Decimal(str(level["points"]))
            else:
                awarded = Decimal(str(criterion["points"])) * Decimal(str(level["ratio"]))
            awarded = awarded.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            score += awarded
            result.append({
                "dimension_key": dimension["key"],
                "dimension_name": dimension["name"],
                "criterion_key": criterion["key"],
                "criterion_name": criterion["name"],
                "criterion_description": criterion["description"],
                "max_points": criterion["points"],
                "level": level_value,
                "level_label": level["label"],
                "level_anchor": level["anchor"],
                "awarded_points": float(awarded),
            })
    return score.quantize(Decimal("0.01")), result
