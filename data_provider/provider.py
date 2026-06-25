import json
import hashlib
import re
from pathlib import Path
from typing import Any

from utils.semantic_mapper import normalize_name


try:
    import requests
except ImportError:  # pragma: no cover - optional runtime dependency
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional runtime dependency
    BeautifulSoup = None


DATA_MODE = "mock"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHED_META_PATH = PROJECT_ROOT / "updater" / "cached_meta.json"
STABLE_META_CACHE_PATH = PROJECT_ROOT / "updater" / "stable_meta_cache.json"
LIVE_PROVIDER_LOG_PATH = PROJECT_ROOT / "updater" / "live_provider_errors.log"


class DataProvider:
    def get_champions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_traits(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_items(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_meta(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class MockProvider(DataProvider):
    def get_champions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "卡莎",
                "cost": 4,
                "tier": "S",
                "source": "MockProvider",
            }
        ]

    def get_traits(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "挑战者",
                "tier": "S",
                "source": "MockProvider",
            }
        ]

    def get_items(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "无尽之刃",
                "tier": "S",
                "source": "MockProvider",
            }
        ]

    def get_meta(self) -> list[dict[str, Any]]:
        return [
            {
                "comp": "卡莎体系",
                "tier": "S",
                "source": "MockProvider",
            },
            {
                "comp": "挑战者体系",
                "tier": "S",
                "source": "MockProvider",
            },
        ]


class CachedProvider(DataProvider):
    def __init__(self, cache_path: Path = CACHED_META_PATH) -> None:
        self.cache_path = cache_path
        self.cache_data = self.load_cache()

    def load_cache(self) -> dict[str, list[dict[str, Any]]]:
        if not self.cache_path.exists():
            mock = MockProvider()
            return {
                "champions": mock.get_champions(),
                "traits": mock.get_traits(),
                "items": mock.get_items(),
                "meta": mock.get_meta(),
            }

        with self.cache_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def get_champions(self) -> list[dict[str, Any]]:
        return self.cache_data.get("champions", [])

    def get_traits(self) -> list[dict[str, Any]]:
        return self.cache_data.get("traits", [])

    def get_items(self) -> list[dict[str, Any]]:
        return self.cache_data.get("items", [])

    def get_meta(self) -> list[dict[str, Any]]:
        return self.cache_data.get("meta", [])


class LiveProvider(DataProvider):
    sources = [
        ("metatft", "MetaTFT", "https://www.metatft.com/comps", 40),
        ("tactics", "TacticsTools", "https://tactics.tools/team-compositions", 30),
        ("datatft", "DataTFT", "https://www.data-tft.com/comps", 30),
    ]

    def __init__(self, fallback_provider: DataProvider | None = None) -> None:
        self.fallback_provider = fallback_provider or CachedProvider()
        self._live_data: dict[str, list[dict[str, Any]]] | None = None
        self._stable_packet: dict[str, Any] | None = None
        self.failure_count = 0
        self.data_quality_score = 0

    def get_champions(self) -> list[dict[str, Any]]:
        return self.load_live_data()["champions"]

    def get_traits(self) -> list[dict[str, Any]]:
        return self.load_live_data()["traits"]

    def get_items(self) -> list[dict[str, Any]]:
        return self.load_live_data()["items"]

    def get_meta(self) -> list[dict[str, Any]]:
        return self.load_live_data()["meta"]

    def load_live_data(self) -> dict[str, list[dict[str, Any]]]:
        if self._live_data is not None:
            return self._live_data

        stable_packet = self.get_stable_data()
        self._live_data = stable_packet["data"]
        return self._live_data

    def get_stable_data(self) -> dict[str, Any]:
        if self._stable_packet is not None:
            return self._stable_packet

        stable_cache = self.load_stable_cache()
        failure_counts = stable_cache.get("failure_counts", {})
        mismatch_rates = stable_cache.get("mismatch_rates", {})
        source_scores = {"metatft": 0, "tactics": 0, "datatft": 0}
        source_payloads: dict[str, dict[str, list[dict[str, Any]]]] = {}

        if requests is None:
            self.log_failure("requests is not installed")
            data = self.choose_cached_stable_data(stable_cache)
            self._stable_packet = self.build_stable_packet(data, source_scores, "cache")
            return self._stable_packet

        reference_data = self.choose_cached_stable_data(stable_cache)

        for source_id, source_name, url, base_score in self.sources:
            try:
                html = self.fetch_with_retry(url)
                source_data = self.normalize_and_dedupe(self.parse_source(source_name, html))
                if not has_source_data(source_data):
                    raise RuntimeError("source returned no usable data")

                source_payloads[source_id] = source_data
                failure_counts[source_id] = 0
                mismatch_rate = calculate_mismatch_rate(source_data, reference_data)
                mismatch_rates[source_id] = mismatch_rate

                score = 100
                if mismatch_rate > 0.2:
                    score = int(score * 0.5)
                source_scores[source_id] = score
            except Exception as exc:
                failure_counts[source_id] = failure_counts.get(source_id, 0) + 1
                self.log_failure(f"{source_name} failed: {exc}")
                continue

        for source_id, *_ in self.sources:
            if failure_counts.get(source_id, 0) > 3:
                source_scores[source_id] = int(source_scores[source_id] * 0.5)

        selected_source = select_best_source(source_scores, source_payloads)
        if selected_source == "cache":
            selected_data = reference_data
        else:
            selected_data = fill_missing_data(source_payloads[selected_source], reference_data)

        self._stable_packet = self.build_stable_packet(
            selected_data,
            source_scores,
            selected_source,
            failure_counts,
            mismatch_rates,
        )
        self.save_stable_cache(self._stable_packet, failure_counts, mismatch_rates)
        return self._stable_packet

    def build_stable_packet(
        self,
        data: dict[str, list[dict[str, Any]]],
        source_scores: dict[str, int],
        selected_source: str,
        failure_counts: dict[str, int] | None = None,
        mismatch_rates: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        self.data_quality_score = calculate_data_quality_score(source_scores)
        return {
            "data": data,
            "data_quality_score": self.data_quality_score,
            "source_scores": source_scores,
            "selected_source": selected_source,
            "version_hash": make_data_hash(data),
            "failure_counts": failure_counts or {"metatft": 0, "tactics": 0, "datatft": 0},
            "mismatch_rates": mismatch_rates or {"metatft": 0, "tactics": 0, "datatft": 0},
        }

    def fetch_with_retry(self, url: str) -> str:
        last_error = None
        for _ in range(2):
            try:
                response = requests.get(
                    url,
                    timeout=5,
                    headers={
                        "User-Agent": "JCC-AI-LiveProvider/1.0",
                        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                    },
                )
                response.raise_for_status()
                return response.text
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = exc

        raise RuntimeError(last_error)

    def parse_source(self, source_name: str, text: str) -> dict[str, list[dict[str, Any]]]:
        json_objects = extract_json_like_objects(text)
        if not json_objects and BeautifulSoup is not None:
            soup = BeautifulSoup(text, "html.parser")
            for script in soup.find_all("script"):
                script_text = script.string or script.get_text() or ""
                json_objects.extend(extract_json_like_objects(script_text))

        return {
            "champions": extract_entries(json_objects, "champions", "name", source_name),
            "traits": extract_entries(json_objects, "traits", "name", source_name),
            "items": extract_entries(json_objects, "items", "name", source_name),
            "meta": extract_meta_entries(json_objects, source_name),
        }

    def normalize_and_dedupe(
        self,
        data: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "champions": dedupe_by_name(data["champions"], "name"),
            "traits": dedupe_by_name(data["traits"], "name"),
            "items": dedupe_by_name(data["items"], "name"),
            "meta": dedupe_by_name(data["meta"], "comp"),
        }

    def fallback_data(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "champions": self.fallback_provider.get_champions(),
            "traits": self.fallback_provider.get_traits(),
            "items": self.fallback_provider.get_items(),
            "meta": self.fallback_provider.get_meta(),
        }

    def load_stable_cache(self) -> dict[str, Any]:
        if not STABLE_META_CACHE_PATH.exists():
            return {
                "version_hash": "",
                "last_stable_data": self.fallback_data(),
                "source_scores": {"metatft": 0, "tactics": 0, "datatft": 0},
                "failure_counts": {"metatft": 0, "tactics": 0, "datatft": 0},
                "mismatch_rates": {"metatft": 0, "tactics": 0, "datatft": 0},
                "selected_source": "cache",
            }

        with STABLE_META_CACHE_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)

    def save_stable_cache(
        self,
        stable_packet: dict[str, Any],
        failure_counts: dict[str, int],
        mismatch_rates: dict[str, float],
    ) -> None:
        STABLE_META_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "version_hash": stable_packet["version_hash"],
            "last_stable_data": stable_packet["data"],
            "source_scores": stable_packet["source_scores"],
            "failure_counts": failure_counts,
            "mismatch_rates": mismatch_rates,
            "selected_source": stable_packet["selected_source"],
        }
        with STABLE_META_CACHE_PATH.open("w", encoding="utf-8") as file:
            json.dump(cache_data, file, ensure_ascii=False, indent=2)

    def choose_cached_stable_data(
        self,
        stable_cache: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        stable_data = stable_cache.get("last_stable_data") or {}
        if has_source_data(stable_data):
            return {
                "champions": stable_data.get("champions", []),
                "traits": stable_data.get("traits", []),
                "items": stable_data.get("items", []),
                "meta": stable_data.get("meta", []),
            }
        return self.fallback_data()

    def log_failure(self, message: str) -> None:
        self.failure_count += 1
        LIVE_PROVIDER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LIVE_PROVIDER_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(f"{message}\n")


def extract_json_like_objects(text: str) -> list[dict[str, Any]]:
    candidates = []
    next_data_match = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        text,
        re.DOTALL,
    )
    if next_data_match:
        candidates.append(next_data_match.group(1))

    candidates.extend(re.findall(r"(\{[^{}]*(?:champions|traits|items|comps)[^{}]*\})", text))
    objects = []

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        objects.extend(flatten_objects(parsed))

    return objects


def flatten_objects(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        results = []
        if any(key in data for key in ["champions", "traits", "items", "comp", "name", "tier"]):
            results.append(data)
        for value in data.values():
            results.extend(flatten_objects(value))
        return results

    if isinstance(data, list):
        results = []
        for item in data:
            results.extend(flatten_objects(item))
        return results

    return []


def extract_entries(
    objects: list[dict[str, Any]],
    collection_key: str,
    name_key: str,
    source_name: str,
) -> list[dict[str, Any]]:
    entries = []
    for obj in objects:
        for entry in obj.get(collection_key, []):
            if isinstance(entry, str):
                entries.append({
                    name_key: normalize_name(entry),
                    "source": source_name,
                })
            elif isinstance(entry, dict) and entry.get(name_key):
                normalized = dict(entry)
                normalized[name_key] = normalize_name(normalized[name_key])
                normalized["source"] = source_name
                entries.append(normalized)
    return entries


def extract_meta_entries(objects: list[dict[str, Any]], source_name: str) -> list[dict[str, Any]]:
    entries = []
    for obj in objects:
        comp_name = obj.get("comp") or obj.get("name")
        if comp_name:
            entries.append({
                "comp": normalize_name(comp_name),
                "tier": obj.get("tier", "B"),
                "source": source_name,
            })
    return entries


def dedupe_by_name(items: list[dict[str, Any]], name_key: str) -> list[dict[str, Any]]:
    deduped = {}
    for item in items:
        name = item.get(name_key)
        if not name:
            continue
        normalized_name = normalize_name(name)
        normalized_item = {**item, name_key: normalized_name}
        deduped.setdefault(normalized_name, normalized_item)
    return list(deduped.values())


def has_source_data(data: dict[str, list[dict[str, Any]]]) -> bool:
    return any(data.get(key) for key in ["champions", "traits", "items", "meta"])


def fill_missing_data(
    source_data: dict[str, list[dict[str, Any]]],
    fallback_data: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "champions": source_data.get("champions") or fallback_data.get("champions", []),
        "traits": source_data.get("traits") or fallback_data.get("traits", []),
        "items": source_data.get("items") or fallback_data.get("items", []),
        "meta": source_data.get("meta") or fallback_data.get("meta", []),
    }


def select_best_source(
    source_scores: dict[str, int],
    source_payloads: dict[str, dict[str, list[dict[str, Any]]]],
) -> str:
    usable_scores = {
        source_id: score
        for source_id, score in source_scores.items()
        if source_id in source_payloads and score > 0
    }
    if not usable_scores:
        return "cache"
    return max(usable_scores, key=usable_scores.get)


def calculate_mismatch_rate(
    source_data: dict[str, list[dict[str, Any]]],
    reference_data: dict[str, list[dict[str, Any]]],
) -> float:
    rates = []
    for key, name_key in [
        ("champions", "name"),
        ("traits", "name"),
        ("items", "name"),
        ("meta", "comp"),
    ]:
        source_names = extract_name_set(source_data.get(key, []), name_key)
        reference_names = extract_name_set(reference_data.get(key, []), name_key)
        if not source_names or not reference_names:
            continue

        union = source_names | reference_names
        if not union:
            continue
        mismatch = union - (source_names & reference_names)
        rates.append(len(mismatch) / len(union))

    if not rates:
        return 0.0
    return round(sum(rates) / len(rates), 4)


def extract_name_set(items: list[dict[str, Any]], name_key: str) -> set[str]:
    names = set()
    for item in items:
        name = item.get(name_key)
        if name:
            names.add(normalize_name(str(name)))
    return names


def make_data_hash(data: dict[str, list[dict[str, Any]]]) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def calculate_data_quality_score(source_scores: dict[str, int]) -> int:
    source_weights = {
        "metatft": 40,
        "tactics": 30,
        "datatft": 30,
    }
    score = 0
    for source_id, weight in source_weights.items():
        score += weight * (source_scores.get(source_id, 0) / 100)
    return int(min(100, round(score)))


def create_provider(data_mode: str = DATA_MODE) -> DataProvider:
    mode = data_mode.lower()
    if mode == "mock":
        return MockProvider()
    if mode == "cache":
        return CachedProvider()
    if mode == "live":
        return LiveProvider()
    raise ValueError(f"Unsupported DATA_MODE: {data_mode}")
