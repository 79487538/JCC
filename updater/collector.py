import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


try:
    import requests
except ImportError:  # pragma: no cover - optional runtime dependency
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional runtime dependency
    BeautifulSoup = None


UPDATER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = UPDATER_DIR.parents[0]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.semantic_mapper import normalize_name  # noqa: E402
from data_provider.provider import create_provider  # noqa: E402

CACHED_META_PATH = UPDATER_DIR / "cached_meta.json"
EMPTY_SOURCE_RESULT = {
    "champions": [],
    "traits": [],
    "items": [],
    "meta": [],
}


class BaseSource:
    name = "BaseSource"

    def get(self, url: str) -> str:
        if requests is None:
            raise RuntimeError("requests is not installed")

        response = requests.get(
            url,
            timeout=8,
            headers={
                "User-Agent": "JCC-AI-Rule-Updater/1.0",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            },
        )
        response.raise_for_status()
        return response.text

    def empty(self) -> dict[str, list[dict[str, Any]]]:
        return {key: [] for key in EMPTY_SOURCE_RESULT}

    def fetch(self) -> dict[str, list[dict[str, Any]]]:
        return self.empty()


class MetaTFTSource(BaseSource):
    name = "MetaTFTSource"
    url = "https://www.metatft.com/comps"

    def fetch(self) -> dict[str, list[dict[str, Any]]]:
        html = self.get(self.url)
        comps = extract_json_like_comps(html)
        return {
            "champions": extract_champions_from_comps(comps, self.name),
            "traits": extract_traits_from_comps(comps, self.name),
            "items": extract_items_from_comps(comps, self.name),
            "meta": extract_meta_from_comps(comps, self.name),
        }


class TacticsToolsSource(BaseSource):
    name = "TacticsToolsSource"
    url = "https://tactics.tools/team-compositions"

    def fetch(self) -> dict[str, list[dict[str, Any]]]:
        html = self.get(self.url)
        comps = extract_json_like_comps(html)
        return {
            "champions": extract_champions_from_comps(comps, self.name),
            "traits": extract_traits_from_comps(comps, self.name),
            "items": extract_items_from_comps(comps, self.name),
            "meta": extract_meta_from_comps(comps, self.name),
        }


class DatatftScraper(BaseSource):
    name = "DatatftScraper"
    url = "https://www.data-tft.com/comps"

    def fetch(self) -> dict[str, list[dict[str, Any]]]:
        html = self.get(self.url)
        comps = []

        if BeautifulSoup is not None:
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script"):
                script_text = script.string or script.get_text() or ""
                comps.extend(extract_json_like_comps(script_text))
        else:
            comps = extract_json_like_comps(html)

        return {
            "champions": extract_champions_from_comps(comps, self.name),
            "traits": extract_traits_from_comps(comps, self.name),
            "items": extract_items_from_comps(comps, self.name),
            "meta": extract_meta_from_comps(comps, self.name),
        }


class MockFallbackSource(BaseSource):
    name = "MockFallbackSource"

    def fetch(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "champions": [
                {
                    "name": "卡莎",
                    "cost": 4,
                    "tier": "S",
                    "source": self.name,
                }
            ],
            "traits": [
                {
                    "name": "挑战者",
                    "tier": "S",
                    "source": self.name,
                }
            ],
            "items": [
                {
                    "name": "无尽之刃",
                    "tier": "S",
                    "source": self.name,
                }
            ],
            "meta": [
                {
                    "comp": "卡莎体系",
                    "tier": "S",
                    "source": self.name,
                },
                {
                    "comp": "挑战者体系",
                    "tier": "S",
                    "source": self.name,
                },
            ],
        }


def extract_json_like_comps(text: str) -> list[dict[str, Any]]:
    candidates = []
    next_data_match = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        text,
        re.DOTALL,
    )
    if next_data_match:
        candidates.append(next_data_match.group(1))

    candidates.extend(re.findall(r"(\{[^{}]*(?:comps|champions|traits|items)[^{}]*\})", text))
    parsed = []

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        parsed.extend(flatten_comp_objects(data))

    return parsed


def flatten_comp_objects(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        results = []
        if any(key in data for key in ["comp", "name", "tier", "champions", "traits", "items"]):
            results.append(data)
        for value in data.values():
            results.extend(flatten_comp_objects(value))
        return results

    if isinstance(data, list):
        results = []
        for item in data:
            results.extend(flatten_comp_objects(item))
        return results

    return []


def extract_champions_from_comps(comps: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    champions = []
    for comp in comps:
        for champion in comp.get("champions", []):
            if isinstance(champion, str):
                champions.append({"name": champion, "source": source})
            elif isinstance(champion, dict) and champion.get("name"):
                champions.append({**champion, "source": source})
    return champions


def extract_traits_from_comps(comps: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    traits = []
    for comp in comps:
        for trait in comp.get("traits", []):
            if isinstance(trait, str):
                traits.append({"name": trait, "source": source})
            elif isinstance(trait, dict) and trait.get("name"):
                traits.append({**trait, "source": source})
    return traits


def extract_items_from_comps(comps: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    items = []
    for comp in comps:
        for item in comp.get("items", []):
            if isinstance(item, str):
                items.append({"name": item, "source": source})
            elif isinstance(item, dict) and item.get("name"):
                items.append({**item, "source": source})
    return items


def extract_meta_from_comps(comps: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    meta = []
    for comp in comps:
        comp_name = comp.get("comp") or comp.get("name")
        if comp_name:
            meta.append({
                "comp": comp_name,
                "tier": comp.get("tier", "B"),
                "source": source,
            })
    return meta


def load_cached_meta() -> dict[str, list[dict[str, Any]]]:
    if not CACHED_META_PATH.exists():
        return MockFallbackSource().fetch()

    with CACHED_META_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return {
        "champions": data.get("champions", []),
        "traits": data.get("traits", []),
        "items": data.get("items", []),
        "meta": data.get("meta", []),
    }


def dedupe(items: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    seen = {}
    for item in items:
        if item.get("name"):
            item = {**item, "name": normalize_name(item["name"])}
        if item.get("comp"):
            item = {**item, "comp": normalize_name(item["comp"])}

        key = item.get(key_name) or item.get("name")
        if not key:
            continue
        if key not in seen:
            seen[key] = item
    return list(seen.values())


def add_backward_compatible_keys(data: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    data["champions_raw"] = data["champions"]
    data["traits_raw"] = data["traits"]
    data["items_raw"] = data["items"]
    data["meta_raw"] = data["meta"]
    return data


def fetch_all_sources() -> dict[str, list[dict[str, Any]]]:
    provider = create_provider()
    result = {
        "champions": provider.get_champions(),
        "traits": provider.get_traits(),
        "items": provider.get_items(),
        "meta": provider.get_meta(),
    }

    result = {
        "champions": dedupe(result["champions"], "name"),
        "traits": dedupe(result["traits"], "name"),
        "items": dedupe(result["items"], "name"),
        "meta": dedupe(result["meta"], "comp"),
    }
    return add_backward_compatible_keys(result)


if __name__ == "__main__":
    print(json.dumps(fetch_all_sources(), ensure_ascii=False, indent=2))
