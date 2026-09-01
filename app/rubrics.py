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

SYSTEM_RUBRIC_NAME = "AI 英語面試練習評分規準"
SYSTEM_RUBRIC_DESCRIPTION = "依寫作、跟讀、角色扮演與心得四個作業流程，以五個各 20 分的向度進行分析式評量。"


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


# The system rubric mirrors the evidence that an assistant can actually review
# in each student workflow: writing drafts, shadowing audio, roleplay turns and
# the submitted reflection.  Every dimension has the same six exact scores so
# assistants never need to convert a percentage or infer a hidden scale.
DEFAULT_RUBRIC_DEFINITION: dict[str, Any] = {
    "levels": RUBRIC_LEVELS,
    "notes": [
        "總分 100 分：五個向度各 20 分；每個向度只能選擇 20、16、12、8、4 或 0 分。",
        "評分證據以系統實際保留的內容為準：寫作草稿、AI 寫作回饋、最終稿、跟讀錄音與逐字稿、角色扮演錄音與逐字稿，以及五題心得。",
        "欲應徵職位資料與 AI 回饋本身不單獨計分；職位資料用來判斷寫作內容的連結，AI 回饋用來判斷學生是否選擇並完成適合自己的修訂。",
        "跟讀以可理解度為準，不以接近母語口音為標準；逐字稿可能有辨識誤差，必要時應回聽原始錄音。",
        "遲交在 Rubric 總分外扣 20 分，最低為 0 分；請在「異動／調分理由」記錄。",
    ],
    "dimensions": [
        _single_criterion_dimension(
            "writing_content_job_fit",
            "寫作練習（一）：內容與職位連結",
            20,
            "查看四題最終稿，評量學生是否直接回答題目，並把自己的經驗、能力與「欲應徵的職位」資料具體連結。",
            [
                _score_level(20, "完整達成", "四題都直接回應題目；多數回答能連結目標職位或職能，並用具體且前後一致的個人經驗、做法或結果支持重點。"),
                _score_level(16, "穩定達成", "四題大多切題；多數回答能連結目標職位或職能，並提供合適的個人細節，只有少數內容較概括。"),
                _score_level(12, "基本達成", "四題都有基本回應，也有提到職位、能力或個人經驗，但多數說明較簡短，連結不夠具體。"),
                _score_level(8, "部分達成", "只有部分回答切題，或多題停留在概括敘述；個人經驗與職位需求的關係不清楚。"),
                _score_level(4, "初步呈現", "僅有少量可判讀內容；多數回答過短、偏題，或幾乎沒有提到職位與自己的經驗。"),
                _score_level(0, "證據不足", "未提交最終稿，或內容空白、與題目無關，無法判斷。"),
            ],
        ),
        _single_criterion_dimension(
            "writing_revision_clarity",
            "寫作練習（二）：修訂與清楚表達",
            20,
            "比較四題草稿、AI 寫作回饋與最終稿，評量學生是否判斷並運用適用的建議，以及能否用有順序、可理解的英文清楚表達。",
            [
                _score_level(20, "完整達成", "能判斷並處理適用的回饋，修訂不只是換字；各題重點與細節順序清楚，英文錯誤不影響理解，並保留自己的真實內容。"),
                _score_level(16, "穩定達成", "多數需要調整之處已在最終稿修正；結構大致清楚，少量用字、句型或銜接問題不妨礙理解。"),
                _score_level(12, "基本達成", "看得出部分修訂，但多集中在字詞或文法；能用簡單英文傳達主要意思，部分內容順序或句子仍不清楚。"),
                _score_level(8, "部分達成", "草稿與最終稿差異有限，或修改後仍有較多零散、重複與不完整句子，需要評分者推測部分意思。"),
                _score_level(4, "初步呈現", "僅做少量表面修改、直接沿用大段建議範文，或最終稿大多無法形成清楚回答。"),
                _score_level(0, "證據不足", "缺少草稿、AI 寫作回饋或最終稿，無法比較修訂；或英文內容不足以判讀。"),
            ],
        ),
        _single_criterion_dimension(
            "shadowing_clarity",
            "跟讀練習：語音清楚度",
            20,
            "查看四題跟讀錄音，必要時對照逐字稿與示範音訊，評量學生朗讀自己最終稿時是否容易理解；不以母語口音為標準。",
            [
                _score_level(20, "完整達成", "四題錄音都清楚且能連續說完；速度、停頓與節奏能支持句意，聽者幾乎不需費力即可理解。"),
                _score_level(16, "穩定達成", "四題整體容易理解且大致順暢；偶有發音、速度或停頓問題，但不影響主要內容。"),
                _score_level(12, "基本達成", "多數內容可以理解；有較多停頓、逐字念讀或部分發音不清，聽者需要一些努力。"),
                _score_level(8, "部分達成", "錄音常中斷、速度明顯不穩或多處發音不清，部分內容難以理解。"),
                _score_level(4, "初步呈現", "僅有少量語音可理解；大部分錄音過短、反覆中斷，或發音問題明顯遮蔽內容。"),
                _score_level(0, "證據不足", "未提供可用錄音，或四題錄音大多無法理解。"),
            ],
        ),
        _single_criterion_dimension(
            "roleplay_response",
            "角色扮演：理解與即席回應",
            20,
            "查看各輪角色扮演錄音與逐字稿，評量學生是否直接回應四個核心題目，並針對最後的臨場追問補充具體細節；不要求逐字背誦最終稿。",
            [
                _score_level(20, "完整達成", "四個核心題目與臨場追問都直接回應；回答有清楚重點與合適的真實細節，臨場追問能針對被問的單一細節補充。"),
                _score_level(16, "穩定達成", "多數題目都能直接回應並加入個人細節；臨場追問大致切題，少數回答略短或較概括。"),
                _score_level(12, "基本達成", "能回應熟悉的核心題目，但部分回答只重述準備內容或細節不足；臨場追問可辨認方向但不完整。"),
                _score_level(8, "部分達成", "多題沒有掌握問題重點、回答彼此零散，或臨場追問未針對被問的細節回答。"),
                _score_level(4, "初步呈現", "僅少數題目有可判讀且切題的回答；多數回答過短、偏題或只重複原稿。"),
                _score_level(0, "證據不足", "未完成角色扮演，或錄音／逐字稿不足以判斷回答內容。"),
            ],
        ),
        _single_criterion_dimension(
            "reflection_evidence_action",
            "心得撰寫：反思證據與改進行動",
            20,
            "查看五題心得，評量學生是否引用本次練習證據說明自己的判斷，並提出可以執行與檢查的下一步。",
            [
                _score_level(20, "完整達成", "五題都引用寫作、跟讀、角色扮演或 AI 回饋中的具體證據；能說明優勢、困難與原因，並提出包含做法、時間和檢查方式的改進行動。"),
                _score_level(16, "穩定達成", "五題大多具體，能連結練習證據並說明優勢與待改進處；後續行動可執行，只有一項細節較不完整。"),
                _score_level(12, "基本達成", "五題都有作答，能指出優勢、困難或待改進處，但證據與原因較簡略；後續行動仍較概括。"),
                _score_level(8, "部分達成", "多數心得停留在「很好」「要加強」等概括描述；很少引用作業內容，後續行動缺少做法、時間或檢查方式。"),
                _score_level(4, "初步呈現", "僅有少量可判讀反思；大多重述 AI 回饋或題目，未說明自己的判斷，也沒有具體下一步。"),
                _score_level(0, "證據不足", "未正式送出心得，或內容不足以判斷學習反思與改進計畫。"),
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
