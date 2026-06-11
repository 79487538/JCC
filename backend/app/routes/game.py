import json
from typing import Any, Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AIUsageLog
from app.utils import ALGORITHM, SECRET_KEY
from ai_provider import call_ai_model, get_default_ai_provider, parse_ai_json

router = APIRouter(prefix="/api/game")


class GameAnalyzeRequest(BaseModel):
    level: int
    gold: int
    hp: int
    round: str
    shop: List[str]
    board: List[str]
    bench: List[str]
    items: List[str]
    god_choices: List[str]
    selected_gods: List[str]
    main_god: Optional[str] = None
    preferred_model: Optional[str] = "auto"
    streak: Optional[int] = None
    streak_type: Optional[str] = None
    token: Optional[str] = None
    license_key: Optional[str] = None


S17_CORE_HEROES = {
    "卡莎": {"priority": 100, "reason": "S17 星神体系可作为攻速法系核心"},
    "阿狸": {"priority": 90, "reason": "当前阵容可作为中期输出过渡"},
    "慎": {"priority": 80, "reason": "补充前排坦度和控制，保护后排输出"},
    "妮蔻": {"priority": 70, "reason": "可增强阵容控制和承伤能力"},
    "亚索": {"priority": 60, "reason": "可作为前中期物理输出过渡"},
}

S17_GOD_RULES = {
    "索拉卡": "提供回复和容错，适合血量健康时稳定运营",
    "锤石": "提升前排和控制能力，适合保血或补坦度",
}

ITEM_RECIPES = [
    {
        "components": ["大棒", "反曲弓"],
        "item": "鬼索狂暴之刃",
        "target": "卡莎",
        "reason": "合成鬼索狂暴之刃",
    },
    {
        "components": ["锁子甲", "反曲弓"],
        "item": "泰坦的坚决",
        "target": "亚索",
        "reason": "提升前排输出英雄的持续作战能力",
    },
    {
        "components": ["大棒", "锁子甲"],
        "item": "冕卫",
        "target": "慎",
        "reason": "增强前排坦度并补充法强收益",
    },
]


def normalize_unit_name(unit: str) -> str:
    return unit.rstrip("0123456789")


def has_unit(units: List[str], name: str) -> bool:
    return any(normalize_unit_name(unit) == name for unit in units)


def parse_round(round_text: str):
    try:
        stage, turn = round_text.split("-", 1)
        return int(stage), int(turn)
    except ValueError:
        return 0, 0


def infer_streak(payload: GameAnalyzeRequest) -> str:
    if payload.streak_type in {"win", "loss"}:
        return payload.streak_type
    if payload.streak is not None:
        if payload.streak >= 3 and payload.hp >= 60:
            return "win"
        if payload.streak <= -3 or payload.hp < 45:
            return "loss"
    if payload.hp >= 70 and payload.gold >= 30:
        return "win"
    if payload.hp < 50:
        return "loss"
    return "neutral"


def is_key_round(round_text: str) -> bool:
    stage, turn = parse_round(round_text)
    return (stage, turn) in {(3, 2), (3, 5), (4, 1), (4, 2), (5, 1)}


def select_model(payload: GameAnalyzeRequest) -> str:
    preferred = (payload.preferred_model or "auto").strip().lower()
    if preferred == "auto":
        configured_provider = get_default_ai_provider()
        if configured_provider != "auto":
            preferred = configured_provider

    high_pressure = payload.hp < 40 or is_key_round(payload.round)
    if preferred == "auto":
        return "qwen-max" if high_pressure else "deepseek-v4-flash"
    if preferred == "deepseek":
        return "deepseek-r1" if high_pressure else "deepseek-v4-flash"
    if preferred == "qwen":
        return "qwen-max" if high_pressure else "qwen-plus"
    if preferred == "openai":
        return "gpt-4o" if high_pressure else "gpt-4o-mini"
    if preferred in {"apirouter", "openrouter"}:
        return "apirouter-auto"
    if preferred == "aipower":
        return "aipower-auto"
    return preferred


def recommend_buy(payload: GameAnalyzeRequest):
    shop_core_heroes = [hero for hero in payload.shop if hero in S17_CORE_HEROES]
    return [
        {
            "action": "buy",
            "target": hero,
            "reason": S17_CORE_HEROES[hero]["reason"],
        }
        for hero in sorted(
            shop_core_heroes,
            key=lambda item: S17_CORE_HEROES[item]["priority"],
            reverse=True,
        )[:2]
    ]


def recommend_tempo(payload: GameAnalyzeRequest):
    streak = infer_streak(payload)
    recommendations = []

    if payload.hp < 40:
        return [
            {
                "action": "stabilize",
                "target": "保血搜牌",
                "reason": "血量低于40，优先提升即时战力避免被入太多",
            }
        ]

    if streak == "loss":
        recommendations.append(
            {
                "action": "economy",
                "target": "吃利息后小搜",
                "reason": "连败或血量偏低，保留经济同时准备补强",
            }
        )
    elif streak == "win":
        recommendations.append(
            {
                "action": "economy",
                "target": "存钱到50",
                "reason": "血量健康且节奏领先，经济优先",
            }
        )
    else:
        recommendations.append(
            {"action": "economy", "target": "存钱到50", "reason": "血量健康，经济优先"}
        )

    stage, turn = parse_round(payload.round)
    should_level = (payload.gold >= 50 and payload.level < 8) or (
        payload.gold >= 32 and payload.level == 6 and (stage, turn) >= (3, 5)
    )
    if should_level:
        reason = "金币充足，建议升人口提升阵容上限"
        if payload.level == 6:
            reason = "金币充足，建议升 7 提升人口"
        recommendations.append({"action": "level_up", "reason": reason})

    return recommendations


def recommend_items(payload: GameAnalyzeRequest):
    item_set = set(payload.items)
    carry_priority = ["卡莎", "阿狸", "亚索", "慎"]

    for recipe in ITEM_RECIPES:
        if set(recipe["components"]).issubset(item_set):
            target = recipe["target"]
            if not has_unit(payload.board + payload.bench + payload.shop, target):
                target = next(
                    (
                        hero
                        for hero in carry_priority
                        if has_unit(payload.board + payload.bench + payload.shop, hero)
                    ),
                    recipe["target"],
                )
            return {
                "action": "equip",
                "target": target,
                "item": "+".join(recipe["components"]),
                "reason": recipe["reason"],
            }
    return None


def recommend_god(payload: GameAnalyzeRequest):
    if payload.main_god:
        return {
            "action": "god",
            "target": payload.main_god,
            "reason": "已确定主神，后续围绕主神强化和阵容羁绊补强",
        }

    available = [god for god in payload.god_choices if god in S17_GOD_RULES]
    if not available:
        return None

    if payload.hp < 45 and "锤石" in available:
        god = "锤石"
    elif "索拉卡" in payload.selected_gods:
        god = "索拉卡"
    else:
        god = available[0]

    return {"action": "god", "target": god, "reason": S17_GOD_RULES[god]}


def build_rule_recommendations(payload: GameAnalyzeRequest):
    recommendations = []
    recommendations.extend(recommend_buy(payload))
    recommendations.extend(recommend_tempo(payload))

    item_recommendation = recommend_items(payload)
    if item_recommendation:
        recommendations.append(item_recommendation)

    god_recommendation = recommend_god(payload)
    if god_recommendation:
        recommendations.append(god_recommendation)

    return recommendations


def parse_ai_recommendations(content: str):
    if not content:
        return []
    data = parse_ai_json(content)
    if isinstance(data, dict) and isinstance(data.get("recommendations"), list):
        return [item for item in data["recommendations"] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def build_ai_input(payload: GameAnalyzeRequest, rule_recommendations: List[Dict[str, Any]]):
    return {
        "task": "根据 S17 星神版本局势，在已有规则建议基础上补充最多2条高价值策略建议。",
        "constraints": ["不调用游戏客户端", "不注入", "不读取内存", "只返回 JSON"],
        "game_state": payload.model_dump(),
        "rule_recommendations": rule_recommendations,
        "output_schema": {
            "recommendations": [
                {"action": "buy|economy|level_up|equip|god|stabilize", "target": "", "item": "", "reason": ""}
            ]
        },
    }


def get_user_id_from_token(token: Optional[str]):
    if not token:
        return None
    try:
        token_data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(token_data.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        return None


def write_ai_usage_log(
    db: Session,
    payload: GameAnalyzeRequest,
    model_used: str,
    estimated_cost_usd: float,
    ai_status: str,
):
    try:
        db.add(
            AIUsageLog(
                user_id=get_user_id_from_token(payload.token),
                license_key=payload.license_key,
                model_used=model_used,
                estimated_cost_usd=estimated_cost_usd or 0,
                ai_status=ai_status,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


@router.post("/analyze")
def analyze_game(payload: GameAnalyzeRequest, db: Session = Depends(get_db)):
    rule_recommendations = build_rule_recommendations(payload)
    selected_model = select_model(payload)
    ai_result = call_ai_model(
        selected_model,
        build_ai_input(payload, rule_recommendations),
        output_estimate=700,
    )

    recommendations = rule_recommendations
    ai_status = ai_result["ai_status"]
    ai_error = ai_result["error"]

    if ai_result["ai_status"] == "success":
        try:
            ai_recommendations = parse_ai_recommendations(ai_result["content"])
            if ai_recommendations:
                recommendations = rule_recommendations + ai_recommendations
            else:
                ai_status = "failed"
                ai_error = "AI response did not contain recommendations"
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            ai_status = "failed"
            ai_error = f"invalid AI JSON response: {exc}"

    write_ai_usage_log(
        db,
        payload,
        ai_result["model_used"],
        ai_result["cost_estimate_usd"],
        ai_status,
    )

    return {
        "status": "ok",
        "recommendations": recommendations,
        "model_used": ai_result["model_used"],
        "estimated_cost_usd": ai_result["cost_estimate_usd"],
        "ai_status": ai_status,
        "ai_error": ai_error,
    }
