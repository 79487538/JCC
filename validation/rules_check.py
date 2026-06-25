import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def compare_collection(current: Any, reference: Any) -> list[dict[str, Any]]:
    current_map = normalize_named_collection(current)
    reference_map = normalize_named_collection(reference)
    mismatches = []

    for name in sorted(reference_map.keys() - current_map.keys()):
        mismatches.append({
            "name": name,
            "type": "missing_in_current",
            "expected": reference_map[name],
            "actual": None,
        })

    for name in sorted(current_map.keys() - reference_map.keys()):
        mismatches.append({
            "name": name,
            "type": "extra_in_current",
            "expected": None,
            "actual": current_map[name],
        })

    for name in sorted(current_map.keys() & reference_map.keys()):
        if current_map[name] != reference_map[name]:
            mismatches.append({
                "name": name,
                "type": "value_mismatch",
                "expected": reference_map[name],
                "actual": current_map[name],
            })

    return mismatches


def build_report() -> dict[str, Any]:
    warnings = []
    mismatch_report = {
        "champions": [],
        "traits": [],
        "items": [],
        "meta_tier": [],
    }

    if not REFERENCE_RULES_PATH.exists():
        warnings.append(f"reference_rules.json not found: {REFERENCE_RULES_PATH}")
        return {
            "error_count": 0,
            "warnings": warnings,
            "mismatch_report": mismatch_report,
        }

    reference_rules = load_json(REFERENCE_RULES_PATH)
    checks = {
        "champions": "champions.json",
        "traits": "traits.json",
        "items": "items.json",
        "meta_tier": "meta_tier.json",
    }

    for section, filename in checks.items():
        current_path = DATA_DIR / filename
        if not current_path.exists():
            warnings.append(f"rules file not found: {current_path}")
            mismatch_report[section].append({
                "name": filename,
                "type": "missing_file",
                "expected": reference_rules.get(section),
                "actual": None,
            })
            continue

        current_data = load_json(current_path)
        reference_data = reference_rules.get(section)
        if reference_data is None:
            warnings.append(f"reference section not found: {section}")
            continue

        mismatch_report[section] = compare_collection(current_data, reference_data)

    error_count = sum(len(items) for items in mismatch_report.values())
    return {
        "error_count": error_count,
        "warnings": warnings,
        "mismatch_report": mismatch_report,
    }


def main() -> None:
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
