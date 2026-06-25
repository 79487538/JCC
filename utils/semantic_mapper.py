MAPPING_TABLE = {
    "无尽之刃": ["Infinity Edge", "InfinityEdge", "IE", "无尽"],
    "珠光护手": ["Jeweled Gauntlet", "JeweledGauntlet", "JG"],
}


def normalize_name(name: str) -> str:
    normalized = str(name).strip()
    compact = normalized.replace(" ", "").lower()

    for standard_name, aliases in MAPPING_TABLE.items():
        if normalized == standard_name:
            return standard_name

        for alias in aliases:
            alias_text = alias.strip()
            if normalized.lower() == alias_text.lower():
                return standard_name
            if compact == alias_text.replace(" ", "").lower():
                return standard_name

    return normalized
