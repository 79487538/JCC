from typing import Any


DEFAULT_STAGE_POWER = {
    "early": 50,
    "mid": 60,
    "late": 70,
}

DEFAULT_STAGE_STRENGTH = {
    "early": 50,
    "mid": 60,
    "late": 70,
}

DEFAULT_ITEM_PRIORITY = {
    "early": 50,
    "mid": 70,
    "late": 80,
}


def normalize_champion(raw: dict[str, Any]) -> dict[str, Any]:
    tier = raw.get("tier", "B")
    cost = int(raw.get("cost", 1))
    role = raw.get("role") or ("主C" if cost >= 4 and tier == "S" else "功能")
    carry_type = raw.get("carry_type", "功能")

    stage_power = raw.get("stage_power") or {
        "early": max(20, 80 - cost * 12),
        "mid": min(90, 45 + cost * 10),
        "late": min(95, 35 + cost * 13),
    }

    return {
        "name": raw.get("name", ""),
        "cost": cost,
        "traits": raw.get("traits", []),
        "role": role,
        "tier": tier,
        "stage_power": stage_power,
        "carry_type": carry_type,
        "recommended_items": raw.get("recommended_items", []),
        "power_spike_level": str(raw.get("power_spike_level", min(9, cost + 4))),
        "synergy_notes": raw.get("synergy_notes", "待补充协同说明"),
    }


def normalize_trait(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": raw.get("name", ""),
        "breakpoints": raw.get("breakpoints", [2, 4, 6, 8]),
        "type": raw.get("type", "战斗"),
        "stage_strength": raw.get("stage_strength", DEFAULT_STAGE_STRENGTH),
        "core_carry_traits": raw.get("core_carry_traits", []),
        "win_condition": raw.get("win_condition", "羁绊成型并匹配核心输出位。"),
        "weakness": raw.get("weakness", "核心质量不足时强度下降。"),
    }


def normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": raw.get("name", ""),
        "components": raw.get("components", []),
        "tier": raw.get("tier", "B"),
        "best_users": raw.get("best_users", []),
        "bad_users": raw.get("bad_users", []),
        "carry_type_match": raw.get("carry_type_match", []),
        "situation_priority": raw.get("situation_priority", DEFAULT_ITEM_PRIORITY),
        "replacement_items": raw.get("replacement_items", []),
    }


def normalize_meta(raw_meta: list[dict[str, Any]]) -> dict[str, list[str]]:
    meta_tier = {
        "S": [],
        "A": [],
        "B": [],
    }

    for raw in raw_meta:
        tier = raw.get("tier", "B")
        if tier not in meta_tier:
            tier = "B"

        comp = raw.get("comp") or raw.get("name")
        if comp and comp not in meta_tier[tier]:
            meta_tier[tier].append(comp)

    return meta_tier


def strip_name_key(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in items:
        name = item.pop("name", "")
        if name:
            result[name] = item
    return result


def normalize(raw_data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    champions = [
        normalize_champion(raw)
        for raw in raw_data.get("champions_raw", [])
        if raw.get("name")
    ]
    traits = [
        normalize_trait(raw)
        for raw in raw_data.get("traits_raw", [])
        if raw.get("name")
    ]
    items = [
        normalize_item(raw)
        for raw in raw_data.get("items_raw", [])
        if raw.get("name")
    ]

    return {
        "champions": champions,
        "traits": strip_name_key(traits),
        "items": strip_name_key(items),
        "meta_tier": normalize_meta(raw_data.get("meta_raw", [])),
    }


if __name__ == "__main__":
    import json
    from collector import fetch_all_sources

    print(json.dumps(normalize(fetch_all_sources()), ensure_ascii=False, indent=2))
