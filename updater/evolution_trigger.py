import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from collector import fetch_all_sources
    from normalizer import normalize
    from updater import update_rules
except ModuleNotFoundError:
    from updater.collector import fetch_all_sources
    from updater.normalizer import normalize
    from updater.updater import update_rules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
EVOLUTION_STATE_PATH = DATA_DIR / "evolution_state.json"
COOLDOWN_SECONDS = 10 * 60
DEFAULT_CALL_THRESHOLD = 50


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def load_state() -> dict[str, Any]:
    return load_json(
        EVOLUTION_STATE_PATH,
        {
            "call_count": 0,
            "last_update": "",
            "last_meta_score": 0,
        },
    )


def save_state(state: dict[str, Any]) -> None:
    write_json(EVOLUTION_STATE_PATH, state)


def in_cooldown(last_update: str) -> bool:
    if not last_update:
        return False

    try:
        last_update_time = datetime.fromisoformat(last_update)
    except ValueError:
        return False

    return (utc_now() - last_update_time).total_seconds() < COOLDOWN_SECONDS


def average_strategy_score(strategy_scores: list[float]) -> float:
    if not strategy_scores:
        return 0

    return sum(strategy_scores) / len(strategy_scores)


def should_trigger(
    state: dict[str, Any],
    champion_deviation: float = 0,
    meta_shift_detected: bool = False,
    strategy_scores: list[float] | None = None,
    previous_average_strategy_score: float | None = None,
    call_threshold: int = DEFAULT_CALL_THRESHOLD,
) -> tuple[bool, list[str]]:
    reasons = []
    strategy_scores = strategy_scores or []
    state["call_count"] = int(state.get("call_count", 0)) + 1

    if champion_deviation > 20:
        reasons.append("champion deviation > 20%")

    if meta_shift_detected:
        reasons.append("meta shift detected")

    if previous_average_strategy_score is not None and strategy_scores:
        current_average = average_strategy_score(strategy_scores)
        if previous_average_strategy_score - current_average > 10:
            reasons.append("strategy_score average dropped > 10%")

    if state["call_count"] >= call_threshold:
        reasons.append(f"call_count reached {call_threshold}")

    return bool(reasons), reasons


def run_evolution_check(
    champion_deviation: float = 0,
    meta_shift_detected: bool = False,
    strategy_scores: list[float] | None = None,
    previous_average_strategy_score: float | None = None,
    call_threshold: int = DEFAULT_CALL_THRESHOLD,
) -> dict[str, Any]:
    state = load_state()
    triggered, reasons = should_trigger(
        state=state,
        champion_deviation=champion_deviation,
        meta_shift_detected=meta_shift_detected,
        strategy_scores=strategy_scores,
        previous_average_strategy_score=previous_average_strategy_score,
        call_threshold=call_threshold,
    )

    if not triggered:
        save_state(state)
        return {
            "triggered": False,
            "cooldown": False,
            "reasons": [],
            "update_result": None,
            "state": state,
        }

    if in_cooldown(state.get("last_update", "")):
        save_state(state)
        return {
            "triggered": True,
            "cooldown": True,
            "reasons": reasons,
            "update_result": None,
            "state": state,
        }

    raw_data = fetch_all_sources()
    normalized_data = normalize(raw_data)
    update_result = update_rules(normalized_data)

    if update_result.get("success"):
        state["call_count"] = 0
        state["last_update"] = utc_now().isoformat()
        state["last_meta_score"] = max(0, 100 - champion_deviation)

    save_state(state)
    return {
        "triggered": True,
        "cooldown": False,
        "reasons": reasons,
        "update_result": update_result,
        "state": state,
    }


if __name__ == "__main__":
    print(json.dumps(run_evolution_check(), ensure_ascii=False, indent=2))
