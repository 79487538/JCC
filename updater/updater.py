import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.semantic_mapper import normalize_name  # noqa: E402

DATA_DIR = PROJECT_ROOT / "backend" / "data"
BACKUP_DIR = DATA_DIR / "backups"
VERSION_PATH = DATA_DIR / "version.json"

TARGET_FILES = {
    "champions": "champions.json",
    "traits": "traits.json",
    "items": "items.json",
    "meta_tier": "meta_tier.json",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def normalize_collection(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        return {
            normalize_name(item.get("name")): item
            for item in data
            if isinstance(item, dict) and item.get("name")
        }

    if isinstance(data, dict):
        return {
            normalize_name(key): value
            for key, value in data.items()
        }

    return {}


def calculate_diff(old_data: Any, new_data: Any) -> dict[str, list[str]]:
    old_map = normalize_collection(old_data)
    new_map = normalize_collection(new_data)

    added = sorted(new_map.keys() - old_map.keys())
    removed = sorted(old_map.keys() - new_map.keys())
    modified = sorted(
        key
        for key in old_map.keys() & new_map.keys()
        if old_map[key] != new_map[key]
    )

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
    }


def count_diff_items(diff: dict[str, list[str]]) -> int:
    return sum(len(items) for items in diff.values())


def calculate_diff_ratio(old_data: Any, new_data: Any, diff: dict[str, list[str]]) -> float:
    old_count = len(normalize_collection(old_data))
    new_count = len(normalize_collection(new_data))
    baseline = max(old_count, new_count, 1)
    return count_diff_items(diff) / baseline


def bump_patch_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return "1.0.1"

    major, minor, patch = [int(part) for part in parts]
    return f"{major}.{minor}.{patch + 1}"


def backup_current_files(timestamp: str) -> list[str]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_paths = []

    for filename in TARGET_FILES.values():
        source = DATA_DIR / filename
        if not source.exists():
            continue

        backup_path = BACKUP_DIR / f"{timestamp}_{filename}"
        backup_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        backup_paths.append(str(backup_path))

    return backup_paths


def build_change_summary(
    old_data_by_key: dict[str, Any],
    normalized_data: dict[str, Any],
) -> tuple[dict[str, dict[str, list[str]]], float]:
    diffs = {}
    ratios = []

    for key in TARGET_FILES:
        old_data = old_data_by_key.get(key, {})
        new_data = normalized_data.get(key, {})
        diff = calculate_diff(old_data, new_data)
        diffs[key] = diff
        ratios.append(calculate_diff_ratio(old_data, new_data, diff))

    max_diff_ratio = max(ratios) if ratios else 0
    return diffs, max_diff_ratio


def update_rules(normalized_data: dict[str, Any]) -> dict[str, Any]:
    missing_keys = [key for key in TARGET_FILES if key not in normalized_data]
    if missing_keys:
        return {
            "success": False,
            "manual_confirmation_required": False,
            "warning": f"normalized_data missing keys: {missing_keys}",
            "diff": {},
            "version": load_json(VERSION_PATH, {"version": "1.0.0"}),
        }

    old_data_by_key = {
        key: load_json(DATA_DIR / filename, {})
        for key, filename in TARGET_FILES.items()
    }
    diffs, max_diff_ratio = build_change_summary(old_data_by_key, normalized_data)

    if max_diff_ratio > 0.3:
        return {
            "success": False,
            "manual_confirmation_required": True,
            "warning": "Diff ratio exceeds 30%; automatic overwrite blocked.",
            "diff_ratio": round(max_diff_ratio, 4),
            "diff": diffs,
            "version": load_json(VERSION_PATH, {"version": "1.0.0"}),
        }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_paths = backup_current_files(timestamp)

    for key, filename in TARGET_FILES.items():
        write_json(DATA_DIR / filename, normalized_data[key])

    version_data = load_json(
        VERSION_PATH,
        {
            "version": "1.0.0",
            "last_update": "",
            "changes": [],
        },
    )
    new_version = bump_patch_version(version_data.get("version", "1.0.0"))
    change_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": new_version,
        "diff": diffs,
        "backup_paths": backup_paths,
    }

    version_data["version"] = new_version
    version_data["last_update"] = change_record["timestamp"]
    version_data.setdefault("changes", []).append(change_record)
    write_json(VERSION_PATH, version_data)

    return {
        "success": True,
        "manual_confirmation_required": False,
        "warning": None,
        "diff_ratio": round(max_diff_ratio, 4),
        "diff": diffs,
        "version": version_data,
    }


if __name__ == "__main__":
    import json as json_module
    from collector import fetch_all_sources
    from normalizer import normalize

    print(json_module.dumps(update_rules(normalize(fetch_all_sources())), ensure_ascii=False, indent=2))
