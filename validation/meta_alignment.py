import json
from pathlib import Path
from typing import Any

import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from backend.main import analyze_game_state  # noqa: E402
from updater.collector import fetch_all_sources  # noqa: E402
from utils.semantic_mapper import normalize_name  # noqa: E402


CACHED_META_PATH = PROJECT_ROOT / "updater" / "cached_meta.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def score_overlap(current: set[str], reference: set[str]) -> int:
    if not reference:
        return 100

    return round(len(current & reference) / len(reference) * 100)


def extract_names(items: list[dict[str, Any]], key: str = "name") -> set[str]:
    return {
        normalize_name(item[key])
        for item in items
        if isinstance(item, dict) and item.get(key)
    }


def build_probe_board(cached_meta: dict[str, Any]) -> list[str]:
    champions = cached_meta.get("champions", [])
    return [
        normalize_name(champion["name"])
        for champion in champions
        if isinstance(champion, dict) and champion.get("name")
    ]


def validate_meta_alignment() -> dict[str, Any]:
    collector_data = fetch_all_sources()
    cached_meta = load_json(CACHED_META_PATH)
    conflicts = []

    collector_champions = extract_names(collector_data.get("champions", []))
    collector_traits = extract_names(collector_data.get("traits", []))
    collector_items = extract_names(collector_data.get("items", []))

    reference_champions = extract_names(cached_meta.get("champions", []))
    reference_traits = extract_names(cached_meta.get("traits", []))
    reference_items = extract_names(cached_meta.get("items", []))
    reference_meta = {
        item.get("comp")
        for item in cached_meta.get("meta", [])
        if isinstance(item, dict) and item.get("comp")
    }

    probe_board = build_probe_board(cached_meta)
    decision = analyze_game_state(
        level=7,
        gold=32,
        hp=56,
        board=probe_board,
    )
    strategy = decision.get("strategy", "")

    for champion in reference_champions:
        if champion not in strategy and champion not in probe_board:
            conflicts.append({
                "type": "meta_champion_not_recommended",
                "target": champion,
                "penalty": 15,
            })

    low_tier_champions = {
        item.get("name")
        for item in collector_data.get("champions", [])
        if item.get("tier") in ["B", "C"] and item.get("name")
    }
    for champion in low_tier_champions:
        if champion in strategy:
            conflicts.append({
                "type": "low_tier_champion_high_weight",
                "target": champion,
                "penalty": 15,
            })

    for trait in reference_traits:
        if trait not in strategy and all(trait not in comp for comp in reference_meta):
            conflicts.append({
                "type": "trait_not_aligned_with_strategy",
                "target": trait,
                "penalty": 10,
            })

    meta_accuracy = {
        "champions": score_overlap(collector_champions, reference_champions),
        "traits": score_overlap(collector_traits, reference_traits),
        "items": score_overlap(collector_items, reference_items),
    }
    base_score = round(sum(meta_accuracy.values()) / len(meta_accuracy))
    penalty = sum(conflict["penalty"] for conflict in conflicts)
    alignment_score = max(0, min(100, base_score - penalty))

    return {
        "alignment_score": alignment_score,
        "conflicts": conflicts,
        "meta_accuracy": meta_accuracy,
    }


def main() -> None:
    print(json.dumps(validate_meta_alignment(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
