import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from data_provider.provider import LiveProvider  # noqa: E402


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def get_input_state(decision_output: dict[str, Any], input_state: dict[str, Any] | None) -> dict[str, Any]:
    if input_state is not None:
        return input_state

    decision_log = decision_output.get("decision_log", {})
    return decision_log.get("input", {})


def get_stage_key(stage: str) -> str:
    if stage == "前期":
        return "early"
    if stage == "后期":
        return "late"
    return "mid"


def evaluate_stage_strategy(decision_output: dict[str, Any]) -> int:
    stage_key = get_stage_key(decision_output.get("stage", ""))
    strategy = decision_output.get("strategy", "")
    explanation = decision_output.get("explanation", "")
    priority = decision_output.get("priority", [])
    stage_focus = decision_output.get("stage_focus", "")
    stage_action = decision_output.get("stage_action", "")

    stage_strategy_path = DATA_DIR / "stage_strategy.json"
    if stage_strategy_path.exists():
        stage_rules = load_json(stage_strategy_path)
        stage_rule = stage_rules.get(stage_key, {})
        stage_focus = stage_focus or stage_rule.get("focus", "")
        stage_action = stage_action or stage_rule.get("action", "")

    score = 45
    if stage_focus and (stage_focus in priority[:2] or stage_focus in strategy):
        score += 25
    if stage_action and (stage_action in strategy or stage_action in explanation):
        score += 20
    if stage_key == "early" and ("经济" in strategy or "经济" in priority[:2]):
        score += 10
    if stage_key == "mid" and ("战力" in strategy or "稳" in strategy or "D" in strategy):
        score += 10
    if stage_key == "late" and ("升" in strategy or "主C" in strategy or "强势" in strategy):
        score += 10

    return clamp_score(score)


def evaluate_human_likeness(
    decision_output: dict[str, Any],
    input_state: dict[str, Any],
    strategy_reasonableness: int,
) -> int:
    strategy = decision_output.get("strategy", "")
    priority = decision_output.get("priority", [])
    learning_signal = decision_output.get("learning_signal", {})
    strategy_score = decision_output.get("strategy_score", 0)
    stage_key = get_stage_key(decision_output.get("stage", ""))
    hp = input_state.get("hp", 0)
    gold = input_state.get("gold", 0)

    score = strategy_reasonableness * 0.45 + strategy_score * 0.25 + 25

    if hp < 40:
        score += 15 if priority[:1] == ["战力"] or "战力" in strategy else -25
    elif hp >= 70:
        score += 10 if "经济" in strategy or "升级" in priority[:2] else -5

    if gold >= 50:
        score += 12 if ("经济" in strategy or "升级" in priority[:2]) else -10
    elif gold < 30:
        score += 12 if ("战力" in strategy or priority[:1] == ["战力"]) else -15

    if stage_key == "mid" and ("稳" in strategy or "D" in strategy or "节奏" in strategy):
        score += 8
    if stage_key == "late" and ("主C" in strategy or "升" in strategy or "强势" in strategy):
        score += 8

    if learning_signal.get("should_adjust") and strategy_score < 60:
        score += 5
    if not learning_signal.get("should_adjust") and strategy_score >= 80:
        score += 5

    return clamp_score(score)


def evaluate_meta_alignment(decision_output: dict[str, Any]) -> int:
    skill_debug = decision_output.get("skill_debug", {})
    meta_debug = skill_debug.get("meta_debug", {})
    detected_meta = meta_debug.get("detected_meta", "B")

    try:
        live_packet = LiveProvider().get_stable_data()
    except Exception:
        live_packet = {
            "data_quality_score": 0,
            "source_scores": {},
            "selected_source": "cache",
        }

    selected_source = live_packet.get("selected_source", "cache")
    source_scores = live_packet.get("source_scores", {})
    selected_source_score = source_scores.get(selected_source, 60 if selected_source == "cache" else 0)
    data_quality_score = live_packet.get("data_quality_score", 0)

    tier_score = {
        "S": 95,
        "A": 82,
        "B": 62,
    }.get(detected_meta, 55)

    score = tier_score * 0.55 + selected_source_score * 0.25 + data_quality_score * 0.2
    return clamp_score(score)


def evaluate_economy_consistency(
    decision_output: dict[str, Any],
    input_state: dict[str, Any],
) -> int:
    strategy = decision_output.get("strategy", "")
    priority = decision_output.get("priority", [])
    stage_key = get_stage_key(decision_output.get("stage", ""))
    gold = input_state.get("gold", 0)
    hp = input_state.get("hp", 0)

    score = 65
    if gold >= 50:
        score += 25 if ("经济" in strategy or "升级" in priority[:2]) else -20
    elif gold < 30:
        score += 20 if ("战力" in strategy or priority[:1] == ["战力"]) else -20
    else:
        score += 10 if ("稳" in strategy or "节奏" in strategy or priority[:2]) else 0

    if hp < 40:
        score += 15 if ("战力" in strategy or priority[:1] == ["战力"]) else -25
    if stage_key == "early" and "经济" in priority[:2]:
        score += 8
    if stage_key == "mid" and "战力" in priority[:2]:
        score += 8
    if stage_key == "late" and ("升级" in priority[:2] or "转型" in priority[:2]):
        score += 8

    return clamp_score(score)


def evaluate_item_match(decision_output: dict[str, Any]) -> int:
    decision_log = decision_output.get("decision_log", {})
    lineup_analysis = decision_log.get("process", {}).get("lineup_analysis", {})
    loaded_items = lineup_analysis.get("items_loaded", [])
    strategy = decision_output.get("strategy", "")

    if not loaded_items:
        return 60

    score = 70
    if any(item for item in loaded_items if item in strategy):
        score += 20
    if "主C" in strategy and any("刃" in item or "杀手" in item or "护手" in item for item in loaded_items):
        score += 10
    if "前排" in strategy and any("甲" in item or "救赎" in item for item in loaded_items):
        score += 10

    return clamp_score(score)


def evaluate_trust(
    decision_output: dict[str, Any],
    input_state: dict[str, Any] | None = None,
) -> dict[str, int]:
    resolved_input = get_input_state(decision_output, input_state)
    strategy_reasonableness = evaluate_stage_strategy(decision_output)
    human_likeness_score = evaluate_human_likeness(
        decision_output,
        resolved_input,
        strategy_reasonableness,
    )
    meta_alignment_score = evaluate_meta_alignment(decision_output)
    economy_consistency = evaluate_economy_consistency(decision_output, resolved_input)
    item_match_score = evaluate_item_match(decision_output)

    trust_score = (
        strategy_reasonableness * 0.25
        + human_likeness_score * 0.3
        + meta_alignment_score * 0.2
        + economy_consistency * 0.15
        + item_match_score * 0.1
    )

    return {
        "trust_score": clamp_score(trust_score),
        "human_likeness_score": human_likeness_score,
        "meta_alignment_score": meta_alignment_score,
        "economy_consistency": economy_consistency,
    }


def evaluate_current_system(
    level: int = 7,
    gold: int = 32,
    hp: int = 56,
    board: list[str] | None = None,
) -> dict[str, int]:
    from backend.main import analyze_game_state

    board = board or ["卡莎", "慎"]
    decision_output = analyze_game_state(level=level, gold=gold, hp=hp, board=board)
    return evaluate_trust(
        decision_output,
        {
            "level": level,
            "gold": gold,
            "hp": hp,
            "board": board,
        },
    )


def main() -> None:
    print(json.dumps(evaluate_current_system(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
