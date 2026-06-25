import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "backend" / "data"
REFERENCE_RULES_PATH = DATA_DIR / "reference_rules.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def normalize_named_collection(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        return {
            item.get("name"): item
            for item in data
            if isinstance(item, dict) and item.get("name")
        }

    if isinstance(data, dict):
        return data

    return {}


def score_deviation(current: Any, reference: Any) -> int:
    if current == reference:
        return 0

    if current is None or reference is None:
        return 100

    if not isinstance(current, type(reference)):
        return 80

    if isinstance(current, dict):
        keys = set(current) | set(reference)
        if not keys:
            return 0

        field_scores = [
            score_deviation(current.get(key), reference.get(key))
            for key in keys
        ]
        return round(sum(field_scores) / len(field_scores))

    if isinstance(current, list):
        current_set = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in current}
        reference_set = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in reference}
        union = current_set | reference_set
        if not union:
            return 0

        difference = current_set ^ reference_set
        ratio = len(difference) / len(union)
        return round(ratio * 70)

    return 30


def classify_deviation(score: int) -> str:
    if score == 0:
        return "完全一致"
    if score <= 30:
        return "小偏差"
    if score <= 60:
        return "中偏差"
    return "严重偏差"


def build_deviation_report(section: str, filename: str, reference_rules: dict[str, Any]) -> list[dict[str, Any]]:
    current_path = DATA_DIR / filename
    current_data = normalize_named_collection(load_json(current_path)) if current_path.exists() else {}
    reference_data = normalize_named_collection(reference_rules.get(section, {}))
    names = sorted(set(current_data) | set(reference_data))
    report = []

    for name in names:
        score = score_deviation(current_data.get(name), reference_data.get(name))
        report.append({
            "name": name,
            "deviation_score": score,
            "level": classify_deviation(score),
        })

    return report


def build_meta_bias_report(reference_rules: dict[str, Any]) -> list[dict[str, Any]]:
    current_meta = normalize_named_collection(load_json(DATA_DIR / "meta_tier.json"))
    reference_meta = normalize_named_collection(reference_rules.get("meta_tier", {}))
    report = []

    for tier in sorted(set(current_meta) | set(reference_meta)):
        score = score_deviation(current_meta.get(tier), reference_meta.get(tier))
        report.append({
            "tier": tier,
            "deviation_score": score,
            "level": classify_deviation(score),
        })

    return report


def build_report() -> dict[str, Any]:
    if not REFERENCE_RULES_PATH.exists():
        return {
            "overall_deviation_score": 0,
            "champions_deviation": [],
            "traits_deviation": [],
            "items_deviation": [],
            "meta_bias_report": [
                {
                    "warning": f"reference_rules.json not found: {REFERENCE_RULES_PATH}"
                }
            ],
        }

    reference_rules = load_json(REFERENCE_RULES_PATH)
    champions_deviation = build_deviation_report(
        "champions",
        "champions.json",
        reference_rules,
    )
    traits_deviation = build_deviation_report(
        "traits",
        "traits.json",
        reference_rules,
    )
    items_deviation = build_deviation_report(
        "items",
        "items.json",
        reference_rules,
    )
    meta_bias_report = build_meta_bias_report(reference_rules)

    scores = [
        item["deviation_score"]
        for group in [champions_deviation, traits_deviation, items_deviation, meta_bias_report]
        for item in group
        if "deviation_score" in item
    ]
    overall_deviation_score = round(sum(scores) / len(scores)) if scores else 0

    return {
        "overall_deviation_score": overall_deviation_score,
        "champions_deviation": champions_deviation,
        "traits_deviation": traits_deviation,
        "items_deviation": items_deviation,
        "meta_bias_report": meta_bias_report,
    }


def main() -> None:
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
