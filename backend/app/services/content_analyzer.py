import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas import Question


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RULES_FILE = PROJECT_ROOT / "data" / "analysis_rules" / "rules.v2.json"


def _merge_rules(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_rules(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def load_analysis_rules() -> dict[str, Any]:
    with RULES_FILE.open(encoding="utf-8") as file:
        rules = json.load(file)
    extends = rules.pop("extends", None)
    if not extends:
        return rules
    base_file = RULES_FILE.parent / Path(extends).name
    with base_file.open(encoding="utf-8") as file:
        base_rules = json.load(file)
    return _merge_rules(base_rules, rules)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"[。！？!?；;\n]+", text) if item.strip()]


def _first_evidence(text: str, cues: list[str]) -> str:
    normalized_cues = [cue.lower() for cue in cues]
    for sentence in _sentences(text):
        normalized_sentence = _normalized(sentence)
        if any(cue in normalized_sentence for cue in normalized_cues):
            return sentence[:80]
    return ""


def _match_cues(text: str, cues: list[str]) -> list[str]:
    normalized_text = _normalized(text)
    return [cue for cue in dict.fromkeys(cues) if cue.lower() in normalized_text]


def _point_cues(point: str, rules: dict[str, Any]) -> list[str]:
    cues = [point]
    cues.extend(rules["exact_point_cues"].get(point, []))
    for group_name, group_cues in rules["point_cue_groups"].items():
        if group_name in point:
            cues.extend(group_cues)
    if any(name in point for name in ("个人职责", "个人责任", "个人任务")):
        # 题目要点和事实证据共用同一份职责词表，避免一侧漏报。
        cues.extend(rules["evidence_cues"]["responsibility"])
    return list(dict.fromkeys(cues))


def _keyword_analysis(
    question: Question,
    transcript: str,
    rules: dict[str, Any],
) -> dict[str, Any]:
    items = []
    for point in question.expected_points:
        cues = _point_cues(point, rules)
        matched = _match_cues(transcript, cues)
        items.append(
            {
                "point": point,
                "hit": bool(matched),
                "matched_cues": matched[:4],
                "evidence": _first_evidence(transcript, matched),
            }
        )
    hit_count = sum(item["hit"] for item in items)
    total = len(items)
    return {
        "items": items,
        "hit_count": hit_count,
        "total": total,
        "ratio": round(hit_count / total, 3) if total else 0,
    }


def _structure_analysis(
    question: Question,
    transcript: str,
    rules: dict[str, Any],
) -> dict[str, Any]:
    if question.star_expected:
        names = {"S": "情境", "T": "任务", "A": "行动", "R": "结果"}
        cue_groups = rules["star_cues"]
        keys = question.star_expected
        mode = "STAR"
    else:
        names = {"P": "观点/目标", "M": "方法/细节", "C": "权衡/依据", "V": "验证/总结"}
        cue_groups = rules["logical_structure_cues"]
        keys = ["P", "M", "C", "V"]
        mode = "LOGIC"

    dimensions = []
    for key in keys:
        matched = _match_cues(transcript, cue_groups[key])
        dimensions.append(
            {
                "key": key,
                "label": names[key],
                "present": bool(matched),
                "matched_cues": matched[:4],
                "evidence": _first_evidence(transcript, matched),
            }
        )
    present_count = sum(item["present"] for item in dimensions)
    return {
        "mode": mode,
        "label": "STAR 结构" if mode == "STAR" else "逻辑结构",
        "dimensions": dimensions,
        "present_count": present_count,
        "total": len(dimensions),
        "score": round(20 * present_count / len(dimensions)) if dimensions else 0,
    }


def _quantified_evidence(transcript: str) -> str:
    pattern = re.compile(
        r"(?:\d+(?:\.\d+)?\s*(?:%|％|秒|毫秒|分钟|小时|天|周|个月|人|次|个|条|倍|万)|"
        r"[一二三四五六七八九十百零两]+\s*(?:秒|分钟|小时|天|周|个月|人|次|个|条|倍|万)|"
        r"百分之[一二三四五六七八九十百零]+|从.{0,18}(?:提升|降低|减少|缩短|增加).{0,18})"
    )
    for sentence in _sentences(transcript):
        if pattern.search(sentence):
            return sentence[:80]
    return ""


def _evidence_analysis(
    question: Question,
    transcript: str,
    keyword_analysis: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    is_experience_question = bool(question.star_expected)
    definitions = [
        (
            "responsibility" if is_experience_question else "specificity",
            "个人职责" if is_experience_question else "具体细节",
            rules["evidence_cues"]["responsibility"]
            if is_experience_question
            else rules["evidence_cues"]["detail"],
        ),
        ("action", "具体行动", rules["evidence_cues"]["action"]),
        ("result", "结果或验证", rules["evidence_cues"]["result"]),
    ]
    dimensions = []
    for key, label, cues in definitions:
        matched = _match_cues(transcript, cues)
        dimensions.append(
            {
                "key": key,
                "label": label,
                "present": bool(matched),
                "evidence": _first_evidence(transcript, matched),
            }
        )
    quantified = _quantified_evidence(transcript)
    dimensions.append(
        {
            "key": "quantified",
            "label": "量化事实",
            "present": bool(quantified),
            "evidence": quantified,
        }
    )
    present_count = sum(item["present"] for item in dimensions)
    # 两个以上题目要点命中时，也可视为具有一定具体性，但仍保留原始命中证据。
    if not is_experience_question and keyword_analysis["hit_count"] >= 2:
        specificity = dimensions[0]
        specificity["present"] = True
        if not specificity["evidence"]:
            hit = next(item for item in keyword_analysis["items"] if item["hit"])
            specificity["evidence"] = hit["evidence"]
        present_count = sum(item["present"] for item in dimensions)
    return {
        "dimensions": dimensions,
        "present_count": present_count,
        "total": len(dimensions),
        "score": present_count * 5,
    }


def _fluency_scores(
    question: Question,
    metrics: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    thresholds = rules["fluency_thresholds"]
    rate = float(metrics.get("speaking_rate_per_min", 0) or 0)
    lower_rate, upper_rate = thresholds["speaking_rate_target"]
    if rate <= 0:
        pace_score = 0
    elif lower_rate <= rate <= upper_rate:
        pace_score = 10
    elif rate < lower_rate:
        pace_score = max(2, round(10 * rate / lower_rate))
    else:
        pace_score = max(2, round(10 * upper_rate / rate))

    pause_ratio = float(metrics.get("pause_ratio", 0) or 0)
    pause_levels = thresholds["pause_ratio_levels"]
    if pause_ratio <= pause_levels[0]:
        pause_score = 15
    elif pause_ratio <= pause_levels[1]:
        pause_score = 12
    elif pause_ratio <= pause_levels[2]:
        pause_score = 9
    else:
        pause_score = 6
    pause_score = max(0, pause_score - min(5, int(metrics.get("long_pause_count", 0)) * 2))

    speech_units = int(metrics.get("speech_units", 0) or 0)
    filler_count = int(metrics.get("filler_count", 0) or 0)
    filler_rate = filler_count / speech_units * 100 if speech_units else 0
    filler_duration_score = 15 - min(7, round(filler_rate * 1.5))
    duration = float(metrics.get("total_duration_sec", 0) or 0)
    duration_min, duration_max = question.duration_sec
    if duration < duration_min or duration > duration_max:
        filler_duration_score -= 4
    filler_duration_score = max(0, filler_duration_score)

    return {
        "score": pace_score + pause_score + filler_duration_score,
        "components": {
            "pace": {
                "score": pace_score,
                "max_score": 10,
                "raw": rate,
                "basis": f"暂用 {lower_rate}–{upper_rate} 表达单位/分钟作为开发区间，待人工数据校准",
            },
            "pause": {
                "score": pause_score,
                "max_score": 15,
                "raw": {
                    "pause_ratio": pause_ratio,
                    "long_pause_count": int(metrics.get("long_pause_count", 0) or 0),
                },
                "basis": "依据停顿占比和长停顿次数计算，阈值待人工标注校准",
            },
            "filler_duration": {
                "score": filler_duration_score,
                "max_score": 15,
                "raw": {
                    "filler_count": filler_count,
                    "filler_per_100_units": round(filler_rate, 2),
                    "duration_sec": duration,
                    "suggested_duration_sec": list(question.duration_sec),
                },
                "basis": "语气词只做频次提醒；回答时长与题目建议范围比较",
            },
        },
    }


def _build_feedback(
    question: Question,
    keyword_analysis: dict[str, Any],
    structure: dict[str, Any],
    evidence: dict[str, Any],
    fluency: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    strengths = []
    suggestions = []

    hit_items = [item for item in keyword_analysis["items"] if item["hit"]]
    if hit_items:
        strengths.append(
            {
                "title": f"已覆盖 {len(hit_items)} 个题目要点",
                "evidence": hit_items[0]["evidence"] or "、".join(item["point"] for item in hit_items[:3]),
            }
        )
    present_structure = [item for item in structure["dimensions"] if item["present"]]
    if present_structure:
        strengths.append(
            {
                "title": f"{structure['label']}已有基础",
                "evidence": present_structure[0]["evidence"] or present_structure[0]["label"],
            }
        )

    missing_points = [item["point"] for item in keyword_analysis["items"] if not item["hit"]]
    if missing_points:
        suggestions.append(
            {
                "priority": 1,
                "title": "补充题目关键要点",
                "reason": "当前未检测到：" + "、".join(missing_points[:3]),
                "action": "选取最重要的 1–2 点补充具体事实，不要为了得分堆砌关键词。",
            }
        )
    missing_structure = [item["label"] for item in structure["dimensions"] if not item["present"]]
    if missing_structure:
        suggestions.append(
            {
                "priority": 2,
                "title": f"完善{structure['label']}",
                "reason": "未检测到：" + "、".join(missing_structure),
                "action": "按“背景/目标—我的行动—结果或验证”的顺序重新组织回答。",
            }
        )
    missing_evidence = [item["label"] for item in evidence["dimensions"] if not item["present"]]
    if missing_evidence:
        suggestions.append(
            {
                "priority": 3,
                "title": "增加可核验的事实",
                "reason": "未检测到：" + "、".join(missing_evidence),
                "action": "说明自己实际做了什么及结果；没有可靠数字时可描述验收结果，不能编造数据。",
            }
        )
    pause = fluency["components"]["pause"]
    if pause["score"] < 12:
        suggestions.append(
            {
                "priority": 4,
                "title": "先处理最长的停顿",
                "reason": f"当前停顿占比为 {pause['raw']['pause_ratio']:.1%}，长停顿 {pause['raw']['long_pause_count']} 次",
                "action": "根据时间轴定位停顿前后的内容，提前准备该段的关键词提纲。",
            }
        )
    pace = fluency["components"]["pace"]
    if pace["score"] < 8:
        suggestions.append(
            {
                "priority": 5,
                "title": "调整表达节奏",
                "reason": f"当前有效语速为 {pace['raw']} 表达单位/分钟",
                "action": "再次回答时用短句分层表达，并与个人后续样本趋势比较。",
            }
        )

    if not strengths:
        strengths.append(
            {
                "title": "已完成一次可复盘的回答",
                "evidence": "当前报告已保留转写、原始语音指标和规则依据。",
            }
        )
    if not suggestions:
        suggestions.append(
            {
                "priority": 1,
                "title": "保持结构并继续精炼",
                "reason": "当前规则已经检测到主要要点、结构和事实证据",
                "action": "下一次在不删除关键事实的前提下压缩重复表达，并用人工反馈复核报告。",
            }
        )
    return strengths[:2], sorted(suggestions, key=lambda item: item["priority"])[:3]


def build_analysis_report(
    question: Question,
    transcript: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    rules = load_analysis_rules()
    keyword_analysis = _keyword_analysis(question, transcript, rules)
    structure = _structure_analysis(question, transcript, rules)
    evidence = _evidence_analysis(question, transcript, keyword_analysis, rules)
    fluency = _fluency_scores(question, metrics, rules)

    relevance_score = round(keyword_analysis["ratio"] * 20)
    content_score = relevance_score + structure["score"] + evidence["score"]
    total_score = content_score + fluency["score"]
    strengths, suggestions = _build_feedback(
        question, keyword_analysis, structure, evidence, fluency
    )
    summary = (
        f"回答命中 {keyword_analysis['hit_count']}/{keyword_analysis['total']} 个题目要点，"
        f"{structure['label']}完成 {structure['present_count']}/{structure['total']} 项。"
    )
    return {
        "engine_version": rules["version"],
        "calibration_status": rules["status"],
        "disclaimer": "本报告是离线规则基线，只用于个人训练；固定阈值尚未经过人工数据校准，不构成录用判断。",
        "summary": summary,
        "scores": {
            "total": total_score,
            "content": content_score,
            "fluency": fluency["score"],
            "relevance": relevance_score,
            "structure": structure["score"],
            "evidence": evidence["score"],
            "components": {
                "relevance": {
                    "score": relevance_score,
                    "max_score": 20,
                    "basis": "题目要点及同义线索命中比例",
                },
                "structure": {
                    "score": structure["score"],
                    "max_score": 20,
                    "basis": structure["label"] + "四项线索，每项 5 分",
                },
                "evidence": {
                    "score": evidence["score"],
                    "max_score": 20,
                    "basis": "职责/细节、行动、结果/验证、量化事实，每项 5 分",
                },
                **fluency["components"],
            },
        },
        "radar": {
            "题目相关": relevance_score * 5,
            "结构完整": structure["score"] * 5,
            "事实成果": evidence["score"] * 5,
            "表达流畅": round(fluency["score"] / 40 * 100),
        },
        "keyword_coverage": keyword_analysis,
        "structure_analysis": structure,
        "evidence_analysis": evidence,
        "strengths": strengths,
        "suggestions": suggestions,
        "pause_timeline": metrics.get("pauses", []),
    }
