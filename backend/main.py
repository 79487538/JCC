import base64
import json
import logging
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel


app = FastAPI()
DATA_DIR = Path(__file__).resolve().parent / "data"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
APP_LOG_PATH = LOG_DIR / "app.log"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from ai.ai_explainer import enhance_explanation  # noqa: E402
from utils.semantic_mapper import normalize_name  # noqa: E402

logger = logging.getLogger("jcc-ai")
logger.setLevel(logging.INFO)
if not logger.handlers:
    file_handler = logging.FileHandler(APP_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(file_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STRATEGY_CONSISTENCY_CACHE: dict[str, str] = {}
STRATEGY_ANCHOR_CACHE: dict[str, dict[str, Any]] = {}
OCR_PREVIOUS_FRAME: dict[str, Any] | None = None
OCR_CONFIDENCE_THRESHOLD = 0.7
OCR_FRAME_HISTORY: list[dict[str, Any]] = []
OCR_LOCKED_FRAME: dict[str, Any] | None = None
OCR_LAST_SCREEN_SIZE: tuple[int, int] | None = None
OCR_PREPROCESS_SCALE = 1.8
OCR_BASE_RESOLUTION = (1920, 1080)
OCR_BASE_ROI_PIXELS = {
    "level": (75, 32, 345, 140),
    "gold": (750, 930, 1018, 1058),
    "hp": (38, 930, 307, 1058),
    "board": (345, 626, 1651, 896),
    "bench": (230, 907, 1690, 1070),
}


class AnalyzeRequest(BaseModel):
    level: int
    gold: int
    hp: int
    board: List[Any]


class OCRMockRequest(BaseModel):
    image_id: str


class OCRImageRequest(BaseModel):
    image_base64: str | None = None
    image_path: str | None = None


class FeedbackRequest(BaseModel):
    strategy: str
    user_action: str
    result: str
    comment: str = ""


def api_success(data: Any) -> dict[str, Any]:
    return {
        "success": True,
        "data": data,
        "error": None,
    }


def api_error(message: str) -> dict[str, Any]:
    return {
        "success": False,
        "data": None,
        "error": message,
    }


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Any) -> Any:
    should_log = request.url.path.startswith(("/analyze", "/ocr"))
    if should_log:
        logger.info("request start path=%s method=%s", request.url.path, request.method)

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request error path=%s method=%s", request.url.path, request.method)
        raise

    if should_log:
        logger.info(
            "request end path=%s method=%s status=%s",
            request.url.path,
            request.method,
            response.status_code,
        )
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Any, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=api_error("请求参数格式错误"))


@app.exception_handler(Exception)
async def general_exception_handler(request: Any, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content=api_error(str(exc)))


def load_json_file(filename: str) -> Any:
    with (DATA_DIR / filename).open("r", encoding="utf-8") as file:
        return json.load(file)


def get_mock_game_state() -> dict[str, Any]:
    return {
        "level": 7,
        "gold": 32,
        "hp": 56,
        "board": ["卡莎", "慎", "阿狸"],
    }


def parse_first_int(text: str, patterns: list[str], default: int) -> int:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return default


def parse_board_from_ocr_text(text: str) -> list[str]:
    champions = load_json_file("champions.json")
    champion_names = [champion["name"] for champion in champions]
    board = [name for name in champion_names if name in text]

    board_match = re.search(
        r"(?:board|阵容|棋子)[:：]\s*([^\n\r]+)",
        text,
        re.IGNORECASE,
    )
    if board_match:
        candidates = re.split(r"[,，、\s]+", board_match.group(1).strip())
        for candidate in candidates:
            if candidate and candidate not in board:
                board.append(candidate)

    return board


def preprocess_ocr_image(image: Any) -> Any:
    from PIL import ImageFilter, ImageOps

    width, height = image.size
    image = image.convert("L")
    image = image.resize((int(width * OCR_PREPROCESS_SCALE), int(height * OCR_PREPROCESS_SCALE)))
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.MedianFilter(size=3))
    image = image.point(lambda pixel: 255 if pixel > 150 else 0)
    image = image.filter(ImageFilter.SHARPEN)
    return image


def get_adaptive_roi_pixels(
    field_name: str,
    screen_size: tuple[int, int],
    processed_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    screen_width, screen_height = screen_size
    processed_width, processed_height = processed_size
    base_width, base_height = OCR_BASE_RESOLUTION
    scale_x = screen_width / base_width
    scale_y = screen_height / base_height
    preprocess_x = processed_width / screen_width
    preprocess_y = processed_height / screen_height
    left, top, right, bottom = OCR_BASE_ROI_PIXELS[field_name]
    roi = (
        int(left * scale_x * preprocess_x),
        int(top * scale_y * preprocess_y),
        int(right * scale_x * preprocess_x),
        int(bottom * scale_y * preprocess_y),
    )
    return clamp_roi(roi, processed_size)


def clamp_roi(
    roi: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    width, height = image_size
    left, top, right, bottom = roi
    left = max(0, min(width - 1, left))
    top = max(0, min(height - 1, top))
    right = max(left + 1, min(width, right))
    bottom = max(top + 1, min(height, bottom))
    return left, top, right, bottom


def crop_roi_pixels(image: Any, roi: tuple[int, int, int, int]) -> Any:
    return image.crop(roi)


def crop_roi(image: Any, roi: tuple[float, float, float, float]) -> Any:
    width, height = image.size
    left, top, right, bottom = roi
    return image.crop((
        int(width * left),
        int(height * top),
        int(width * right),
        int(height * bottom),
    ))


def ocr_region(image: Any, field_type: str) -> dict[str, Any]:
    import pytesseract
    from pytesseract import Output

    if field_type == "number":
        config = "--psm 7 -c tessedit_char_whitelist=0123456789"
        lang = "eng"
    else:
        config = "--psm 6"
        lang = "chi_sim+eng"

    data = pytesseract.image_to_data(
        image,
        lang=lang,
        config=config,
        output_type=Output.DICT,
        timeout=3,
    )
    words = []
    confidences = []
    for text, confidence in zip(data.get("text", []), data.get("conf", [])):
        text = str(text).strip()
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = -1

        if text:
            words.append(text)
        if confidence_value >= 0:
            confidences.append(confidence_value / 100)

    confidence = sum(confidences) / len(confidences) if confidences else 0
    return {
        "text": " ".join(words).strip(),
        "confidence": round(max(0, min(1, confidence)), 3),
    }


def parse_int_ocr_field(field: dict[str, Any], default: int | None = None) -> int | None:
    match = re.search(r"\d+", field.get("text", ""))
    if match:
        return int(match.group(0))
    return default


def parse_board_ocr_fields(board_field: dict[str, Any], bench_field: dict[str, Any]) -> list[str]:
    merged_text = f"{board_field.get('text', '')} {bench_field.get('text', '')}".strip()
    return fuzzy_match_board_champions(
        merged_text,
        max(board_field.get("confidence", 0), bench_field.get("confidence", 0)),
    )


def levenshtein_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            insert_cost = current[right_index - 1] + 1
            delete_cost = previous[right_index] + 1
            replace_cost = previous[right_index - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def fuzzy_match_board_champions(text: str, confidence: float) -> list[str]:
    if confidence < 0.35:
        return []

    champions = load_json_file("champions.json")
    champion_names = [normalize_name(champion["name"]) for champion in champions if champion.get("name")]
    champion_set = set(champion_names)
    raw_tokens = re.split(r"[\s,，、;；|/\\\[\](){}<>:：]+", text)
    candidates = []
    for token in raw_tokens:
        normalized = normalize_name(token.strip())
        if len(normalized) <= 1:
            continue
        if not re.search(r"[\w\u4e00-\u9fff]", normalized):
            continue
        candidates.append(normalized)

    matched = []
    for candidate in candidates:
        if candidate in champion_set:
            matched.append(candidate)
            continue

        best_name = None
        best_distance = 99
        for champion_name in champion_names:
            distance = levenshtein_distance(candidate, champion_name)
            if distance < best_distance:
                best_name = champion_name
                best_distance = distance

        if best_name and best_distance <= 2:
            matched.append(best_name)

    deduped = []
    for name in matched:
        if name not in deduped:
            deduped.append(name)
    return deduped


def validate_ocr_game_state(data: dict[str, Any]) -> bool:
    if not isinstance(data.get("level"), int):
        return False
    if not isinstance(data.get("gold"), int):
        return False
    if not isinstance(data.get("hp"), int):
        return False
    if not isinstance(data.get("board"), list):
        return False
    if not 1 <= data["level"] <= 10:
        return False
    if not 0 <= data["gold"] <= 999:
        return False
    if not 0 <= data["hp"] <= 100:
        return False
    return True


def compact_game_state(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "level": data.get("level"),
        "gold": data.get("gold"),
        "hp": data.get("hp"),
        "board": data.get("board", []),
    }


def calculate_frame_similarity(current: dict[str, Any], previous: dict[str, Any]) -> float:
    score = 0.0
    if current.get("level") == previous.get("level"):
        score += 0.25
    if abs((current.get("gold") or 0) - (previous.get("gold") or 0)) <= 3:
        score += 0.2
    if abs((current.get("hp") or 0) - (previous.get("hp") or 0)) <= 5:
        score += 0.25

    current_board = set(current.get("board", []))
    previous_board = set(previous.get("board", []))
    if not current_board and not previous_board:
        score += 0.3
    elif current_board or previous_board:
        score += 0.3 * (len(current_board & previous_board) / len(current_board | previous_board))

    return round(max(0, min(1, score)), 3)


def update_stable_frame_cache(data: dict[str, Any]) -> dict[str, Any]:
    global OCR_FRAME_HISTORY, OCR_LOCKED_FRAME

    current = compact_game_state(data)
    previous = OCR_FRAME_HISTORY[-1] if OCR_FRAME_HISTORY else None
    frame_stability = calculate_frame_similarity(current, previous) if previous else 0
    re_verify = bool(previous and frame_stability < 0.45)

    OCR_FRAME_HISTORY.append(current)
    OCR_FRAME_HISTORY = OCR_FRAME_HISTORY[-3:]

    if len(OCR_FRAME_HISTORY) >= 2:
        last_two_stable = calculate_frame_similarity(OCR_FRAME_HISTORY[-1], OCR_FRAME_HISTORY[-2]) >= 0.85
    else:
        last_two_stable = False

    if len(OCR_FRAME_HISTORY) == 3:
        pair_scores = [
            calculate_frame_similarity(OCR_FRAME_HISTORY[0], OCR_FRAME_HISTORY[1]),
            calculate_frame_similarity(OCR_FRAME_HISTORY[1], OCR_FRAME_HISTORY[2]),
        ]
        if min(pair_scores) >= 0.9:
            OCR_LOCKED_FRAME = OCR_FRAME_HISTORY[-1]
            frame_stability = 1

    return {
        "frame_stability": round(1 if OCR_LOCKED_FRAME == current else max(frame_stability, 0.85 if last_two_stable else 0), 3),
        "re_verify": re_verify,
        "locked": OCR_LOCKED_FRAME == current,
    }


def calculate_confidence_avg(ocr_fields: dict[str, Any]) -> float:
    confidences = [
        field_data.get("confidence", 0)
        for field_data in ocr_fields.values()
        if isinstance(field_data, dict)
    ]
    if not confidences:
        return 0
    return round(sum(confidences) / len(confidences), 3)


def build_ocr_health(status: str, confidence_avg: float, frame_stability: float) -> dict[str, Any]:
    return {
        "status": status,
        "confidence_avg": round(max(0, min(1, confidence_avg)), 3),
        "frame_stability": round(max(0, min(1, frame_stability)), 3),
    }


def build_degraded_ocr_result(
    reason: str,
    ocr_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if OCR_PREVIOUS_FRAME is None:
        raise RuntimeError(reason)

    fields = ocr_fields or {}
    confidence_avg = calculate_confidence_avg(fields)
    data = dict(OCR_PREVIOUS_FRAME)
    data["ocr_fields"] = fields
    data["needs_confirm"] = False
    data["degraded_mode"] = True
    data["degraded_reason"] = reason
    data["low_confidence_fields"] = list(fields.keys())
    data["ocr_health"] = build_ocr_health("degraded", confidence_avg, 1)
    return data


def apply_ocr_fallback(data: dict[str, Any], ocr_fields: dict[str, Any]) -> dict[str, Any]:
    global OCR_PREVIOUS_FRAME

    confidence_avg = calculate_confidence_avg(ocr_fields)
    low_confidence_fields = [
        field_name
        for field_name, field_data in ocr_fields.items()
        if field_data.get("confidence", 0) < OCR_CONFIDENCE_THRESHOLD
    ]

    if ocr_fields and all(
        field_data.get("confidence", 0) < 0.5
        for field_data in ocr_fields.values()
    ):
        return build_degraded_ocr_result("OCR confidence below production threshold", ocr_fields)

    needs_confirm = bool(low_confidence_fields)
    degraded_mode = False
    if needs_confirm and OCR_PREVIOUS_FRAME is not None:
        for field_name in ["level", "gold", "hp", "board"]:
            if field_name in low_confidence_fields:
                data[field_name] = OCR_PREVIOUS_FRAME[field_name]
        needs_confirm = False
        degraded_mode = True

    stability = {"frame_stability": 0, "re_verify": False, "locked": False}
    if validate_ocr_game_state(data):
        stability = update_stable_frame_cache(data)
        if stability["re_verify"]:
            needs_confirm = True

    data["ocr_fields"] = ocr_fields
    data["needs_confirm"] = needs_confirm
    data["degraded_mode"] = degraded_mode
    data["low_confidence_fields"] = low_confidence_fields
    data["re_verify"] = stability["re_verify"]
    data["locked_state"] = stability["locked"]
    if needs_confirm:
        status = "degraded" if OCR_PREVIOUS_FRAME is not None else "failed"
    elif degraded_mode:
        status = "degraded"
    else:
        status = "stable"
    data["ocr_health"] = build_ocr_health(
        status,
        confidence_avg,
        stability["frame_stability"],
    )

    if validate_ocr_game_state(data) and not needs_confirm:
        OCR_PREVIOUS_FRAME = {
            "level": data["level"],
            "gold": data["gold"],
            "hp": data["hp"],
            "board": data["board"],
        }

    return data


def legacy_extract_game_state_from_image(image_path: str) -> dict[str, Any]:
    try:
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("OCR依赖未安装，请安装 pillow 和 pytesseract") from exc

    image = Image.open(image_path)
    text = pytesseract.image_to_string(image, lang="chi_sim+eng")

    level = parse_first_int(
        text,
        [
            r"(?:level|lv|等级)\D*(\d+)",
            r"(?:人口)\D*(\d+)",
        ],
        default=7,
    )
    gold = parse_first_int(
        text,
        [
            r"(?:gold|金币|经济)\D*(\d+)",
            r"(?:钱)\D*(\d+)",
        ],
        default=32,
    )
    hp = parse_first_int(
        text,
        [
            r"(?:hp|health|血量|生命)\D*(\d+)",
            r"(?:血)\D*(\d+)",
        ],
        default=56,
    )
    board = parse_board_from_ocr_text(text)

    return {
        "level": int(level),
        "gold": int(gold),
        "hp": int(hp),
        "board": [str(name) for name in board],
    }


def extract_game_state_from_image(image_path: str) -> dict[str, Any]:
    global OCR_LAST_SCREEN_SIZE

    try:
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        return build_degraded_ocr_result(f"OCR dependency missing: {exc}")

    try:
        image = Image.open(image_path)
        screen_size = image.size
        resolution_changed = OCR_LAST_SCREEN_SIZE is not None and OCR_LAST_SCREEN_SIZE != screen_size
        OCR_LAST_SCREEN_SIZE = screen_size
        processed_image = preprocess_ocr_image(image)
        roi_map = {
            field_name: get_adaptive_roi_pixels(field_name, screen_size, processed_image.size)
            for field_name in OCR_BASE_ROI_PIXELS
        }
        ocr_fields = {
            "level": ocr_region(crop_roi_pixels(processed_image, roi_map["level"]), "number"),
            "gold": ocr_region(crop_roi_pixels(processed_image, roi_map["gold"]), "number"),
            "hp": ocr_region(crop_roi_pixels(processed_image, roi_map["hp"]), "number"),
            "board": ocr_region(crop_roi_pixels(processed_image, roi_map["board"]), "text"),
            "bench": ocr_region(crop_roi_pixels(processed_image, roi_map["bench"]), "text"),
        }
        data = {
            "level": parse_int_ocr_field(ocr_fields["level"]),
            "gold": parse_int_ocr_field(ocr_fields["gold"]),
            "hp": parse_int_ocr_field(ocr_fields["hp"]),
            "board": parse_board_ocr_fields(ocr_fields["board"], ocr_fields["bench"]),
        }
        data = apply_ocr_fallback(data, ocr_fields)
        data["roi_debug"] = {
            "base_resolution": OCR_BASE_RESOLUTION,
            "screen_resolution": list(screen_size),
            "scale_x": round(screen_size[0] / OCR_BASE_RESOLUTION[0], 4),
            "scale_y": round(screen_size[1] / OCR_BASE_RESOLUTION[1], 4),
            "recalibrated": resolution_changed,
        }
        if not validate_ocr_game_state(data):
            raise ValueError("OCR structured output validation failed")

        return data
    except Exception as exc:
        return build_degraded_ocr_result(f"OCR failed: {exc}")


def save_base64_image_to_temp(image_base64: str) -> str:
    encoded = image_base64.split(",", 1)[-1]
    image_bytes = base64.b64decode(encoded)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_file.write(image_bytes)
    temp_file.close()
    return temp_file.name


def save_raw_image_to_temp(image_bytes: bytes) -> str:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_file.write(image_bytes)
    temp_file.close()
    return temp_file.name


def calculate_strategy_distance(strategy_a: str, strategy_b: str) -> float:
    if strategy_a == strategy_b:
        return 0.0

    tokens_a = {token.strip() for token in strategy_a.split("+") if token.strip()}
    tokens_b = {token.strip() for token in strategy_b.split("+") if token.strip()}
    if not tokens_a or not tokens_b:
        return 1.0

    overlap = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    similarity = overlap / union

    if similarity >= 0.7:
        return 0.3
    if similarity >= 0.4:
        return 0.6
    return 1.0


def append_feedback_log(payload: FeedbackRequest) -> dict[str, Any]:
    feedback_path = DATA_DIR / "feedback_log.json"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_strategy": payload.strategy,
        "user_action": payload.user_action,
        "user_result": payload.result,
        "comment": payload.comment,
    }

    if feedback_path.exists():
        with feedback_path.open("r", encoding="utf-8") as file:
            records = json.load(file)
            if not isinstance(records, list):
                records = []
    else:
        records = []

    records.append(record)
    with feedback_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    return record


def analyze_board(board: List[Any]) -> str:
    champions = load_json_file("champions.json")
    traits = load_json_file("traits.json")
    champion_map = {champion["name"]: champion for champion in champions}

    matched_champions = []
    trait_names = []
    unknown_names = []

    for piece in board:
        name = str(piece)
        champion = champion_map.get(name)
        if champion is None:
            unknown_names.append(name)
            continue

        matched_champions.append(
            f"{champion['name']}（{champion['cost']}费，羁绊：{'、'.join(champion['traits'])}）"
        )
        trait_names.extend(champion["traits"])

    trait_details = []
    for trait_name in sorted(set(trait_names)):
        effect = traits.get(trait_name, "暂无效果说明")
        trait_details.append(f"{trait_name}：{effect}")

    composition = (
        "、".join(matched_champions) if matched_champions else "暂无已匹配棋子"
    )
    trait_text = "；".join(trait_details) if trait_details else "暂无已匹配羁绊"
    unknown_text = (
        f"未匹配棋子：{'、'.join(unknown_names)}。" if unknown_names else ""
    )

    return f"当前阵容组成分析：{composition}。羁绊信息：{trait_text}。{unknown_text}"


def analyze_game_state(
    level: int,
    gold: int,
    hp: int,
    board: List[Any],
) -> dict[str, Any]:
    # 1. 数据解析层：读取规则库并把输入映射成可决策特征。
    champions = load_json_file("champions.json")
    traits = load_json_file("traits.json")
    items = load_json_file("items.json")
    augments = load_json_file("augments.json")
    meta_tiers = load_json_file("meta_tier.json")
    stage_strategy = load_json_file("stage_strategy.json")
    champion_map = {champion["name"]: champion for champion in champions}

    matched_champions = []
    unknown_names = []
    trait_names = []
    costs = []

    for piece in board:
        name = str(piece)
        champion = champion_map.get(name)
        if champion is None:
            unknown_names.append(name)
            continue

        matched_champions.append(champion)
        trait_names.extend(champion["traits"])
        costs.append(champion["cost"])

    high_cost_count = sum(1 for cost in costs if cost >= 4)
    low_cost_count = sum(1 for cost in costs if cost <= 2)
    trait_counter = Counter(trait_names)
    active_traits = [trait for trait, count in trait_counter.items() if count >= 2]
    board_match_rate = len(matched_champions) / len(board) if board else 0

    lineup_candidates = [f"{trait}体系" for trait in active_traits]
    lineup_candidates.extend(
        f"{champion['name']}体系"
        for champion in matched_champions
        if champion.get("role") == "主C"
    )
    lineup_direction = lineup_candidates[0] if lineup_candidates else "过渡阵容"

    current_meta_tier = "B"
    matched_meta_lineup = "过渡阵容"
    for tier in ["S", "A", "B"]:
        matched_lineups = [
            candidate for candidate in lineup_candidates if candidate in meta_tiers.get(tier, [])
        ]
        if matched_lineups:
            current_meta_tier = tier
            matched_meta_lineup = matched_lineups[0]
            break
    meta_strength_score = {"S": 20, "A": 10, "B": 0}.get(current_meta_tier, 0)

    if current_meta_tier in ["S", "A"]:
        meta_reason = f"{matched_meta_lineup}命中{current_meta_tier}级版本阵容。"
    else:
        meta_reason = "当前阵容未命中S/A版本强势阵容，更多属于过渡或低优先级方向。"

    # 2. 阶段识别层：由等级映射 stage_strategy。
    if level <= 5:
        stage = "前期"
        stage_key = "early"
    elif level <= 7:
        stage = "中期"
        stage_key = "mid"
    else:
        stage = "后期"
        stage_key = "late"

    current_stage_strategy = stage_strategy[stage_key]
    stage_focus = current_stage_strategy["focus"]
    stage_action = current_stage_strategy["action"]
    stage_reason = (
        f"等级为{level}，因此匹配{stage_key}阶段规则："
        f"重点是{stage_focus}，行动为{stage_action}。"
    )

    if stage_key == "late":
        augment_type = "转型类"
        augment_reason = "当前处于后期，优先考虑转型类强化来提升阵容上限。"
    elif gold >= 50:
        augment_type = "经济类"
        augment_reason = "金币达到50以上，优先模拟经济类强化来扩大运营空间。"
    elif hp < 40:
        augment_type = "战力类"
        augment_reason = "血量低于40，优先模拟战力类强化来提高即时战斗力。"
    elif stage_key == "early":
        augment_type = "经济类"
        augment_reason = "当前处于前期，阶段策略偏经济，因此优先模拟经济类强化。"
    else:
        augment_type = "战力类"
        augment_reason = "当前处于中期，阶段策略偏战力，因此优先模拟战力类强化。"

    augment_score = {"经济类": 15, "战力类": 15, "转型类": 20}[augment_type]
    augment_info = augments[augment_type]

    # 3. 经济/战力/阵容评分层：Skill 核心评分。
    economy_score = max(0, min(100, round(gold * 2)))
    hp_score = max(0, min(100, round(hp)))

    high_cost_score = min(40, high_cost_count * 20)
    trait_score = min(30, len(active_traits) * 15)
    match_score = round(board_match_rate * 20)
    base_comp_score = max(
        0,
        min(100, high_cost_score + trait_score + match_score),
    )
    comp_score = round(
        base_comp_score * 0.6 + meta_strength_score * 0.2 + augment_score * 0.2,
        2,
    )

    stage_weight_map = {
        "early": {"economy": 0.5, "hp": 0.2, "comp": 0.3},
        "mid": {"economy": 0.3, "hp": 0.4, "comp": 0.3},
        "late": {"economy": 0.2, "hp": 0.2, "comp": 0.6},
    }
    stage_weights = stage_weight_map[stage_key].copy()
    conflict_mode = (
        hp < 40
        and current_meta_tier == "S"
        and augment_type == "经济类"
    )
    weight_adjustments = {}

    if conflict_mode:
        original_hp_weight = stage_weights["hp"]
        original_economy_weight = stage_weights["economy"]
        stage_weights["hp"] *= 1.3
        stage_weights["economy"] *= 0.8
        weight_adjustments = {
            "hp_weight": {
                "from": original_hp_weight,
                "to": round(stage_weights["hp"], 4),
                "reason": "冲突模式触发，血量低时提高生存权重30%",
            },
            "economy_weight": {
                "from": original_economy_weight,
                "to": round(stage_weights["economy"], 4),
                "reason": "冲突模式触发，降低经济权重20%",
            },
        }

        total_weight = sum(stage_weights.values())
        stage_weights = {
            key: round(value / total_weight, 4)
            for key, value in stage_weights.items()
        }

    final_score = round(
        economy_score * stage_weights["economy"]
        + hp_score * stage_weights["hp"]
        + comp_score * stage_weights["comp"],
        2,
    )

    if final_score >= 75:
        game_strength = "强"
        risk_level = "low"
    elif final_score >= 50:
        game_strength = "一般"
        risk_level = "medium"
    else:
        game_strength = "弱"
        risk_level = "high"

    # 4. 决策融合层：按 final_score 和 stage_strategy 生成 Skill 策略。
    if stage_key == "early":
        if economy_score >= 70 and hp_score >= 50:
            strategy_parts = ["前期运营", "强经济", "保连胜/连败节奏"]
        elif hp_score < 40:
            strategy_parts = ["前期稳血", "少量补战力", "保经济底线"]
        else:
            strategy_parts = ["前期运营", "存钱发育", "观察转型"]
    elif stage_key == "mid":
        if hp_score < 40:
            strategy_parts = ["中期D牌稳血", "优先补战力"]
        elif comp_score >= economy_score and comp_score >= hp_score:
            strategy_parts = ["中期阵容提质", "围绕核心羁绊成型"]
        else:
            strategy_parts = ["中期稳节奏", "根据血量决定是否D牌"]
    else:
        if comp_score >= 65:
            strategy_parts = ["后期升人口", "找主C", "强化高meta阵容"]
        else:
            strategy_parts = ["后期升人口", "找主C", "转型S级阵容"]

    if lineup_direction != "过渡阵容" and not any("体系" in part for part in strategy_parts):
        strategy_parts.append(lineup_direction)

    strategy = " + ".join(strategy_parts)
    decision_axis_score = final_score
    factor_scores = {
        "skill": final_score,
        "meta": meta_strength_score * 0.3,
        "augment": augment_score * 0.2,
    }
    dominant_system = max(factor_scores, key=factor_scores.get)

    if decision_axis_score >= 70:
        decision_axis_type = "强势压制"
    elif decision_axis_score >= 40:
        decision_axis_type = "进攻调整"
    else:
        decision_axis_type = "稳健运营"

    forced_alignment_reason = ""
    if current_meta_tier == "S" and decision_axis_score > 70:
        decision_axis_type = "强势压制"
        forced_alignment_reason = "S级meta且主轴分超过70，强制收敛为强势压制型。"
    elif hp < 40:
        decision_axis_type = "进攻调整"
        forced_alignment_reason = "血量低于40，强制偏向战力优先策略。"
    elif gold > 50:
        decision_axis_type = "稳健运营"
        forced_alignment_reason = "金币高于50，强制偏向经济优先策略。"

    if decision_axis_type == "强势压制":
        alignment_label = "强势压制型"
    elif decision_axis_type == "进攻调整":
        alignment_label = "进攻调整型"
    else:
        alignment_label = "稳健运营型"

    if alignment_label not in strategy:
        strategy = f"{alignment_label} + {strategy}"

    fusion_reason = (
        f"decision_axis_score={decision_axis_score}，由阵容{comp_score}、"
        f"meta_bonus={meta_strength_score}、augment_score={augment_score}融合得到；"
        f"主导系统为{dominant_system}，最终收敛为{decision_axis_type}。"
        f"{forced_alignment_reason}"
    )
    decision_axis = {
        "score": decision_axis_score,
        "type": decision_axis_type,
        "dominant_factor": dominant_system,
    }

    priority_scores = {
        "经济": economy_score + (10 if stage_key == "early" else 0),
        "战力": hp_score + (10 if stage_key == "mid" else 0),
        "升级": economy_score + (10 if stage_key == "late" else 0),
        "转型": comp_score + (10 if current_meta_tier == "S" else 0),
    }
    priority = sorted(priority_scores, key=priority_scores.get, reverse=True)

    strategy_reason = (
        f"final_score={final_score}，其中经济{economy_score}、血量{hp_score}、阵容{comp_score}；"
        f"{stage}阶段按{stage_focus}优先，并结合{current_meta_tier}级meta，"
        f"所以最终选择{strategy}。"
    )

    consistency_key = "|".join(
        [
            f"level:{level // 2}",
            f"gold:{gold // 10}",
            f"hp:{hp // 10}",
            f"high:{min(high_cost_count, 2)}",
            f"low:{min(low_cost_count, 3)}",
            f"trait:{active_traits[0] if active_traits else 'none'}",
        ]
    )
    previous_strategy = STRATEGY_CONSISTENCY_CACHE.get(consistency_key)
    previous_anchor_state = STRATEGY_ANCHOR_CACHE.get(consistency_key)
    generated_strategy = strategy
    strategy_anchor_score = round(
        final_score * 0.7 + meta_strength_score * 0.2 + augment_score * 0.1,
        2,
    )
    drift_detected = False
    final_strategy_locked = False

    if previous_strategy is None:
        similar_case_match = False
        strategy_distance = 0.0
        STRATEGY_CONSISTENCY_CACHE[consistency_key] = generated_strategy
    else:
        similar_case_match = True
        strategy_distance = calculate_strategy_distance(previous_strategy, generated_strategy)
        strategy = previous_strategy

    if previous_anchor_state is not None:
        previous_anchor_score = previous_anchor_state["anchor_score"]
        previous_anchor_strategy = previous_anchor_state["strategy"]
        anchor_delta = abs(strategy_anchor_score - previous_anchor_score)
        drift_detected = generated_strategy != previous_anchor_strategy
        if drift_detected and anchor_delta < 10:
            strategy = previous_anchor_strategy
            final_strategy_locked = True
    else:
        anchor_delta = 0.0

    STRATEGY_ANCHOR_CACHE[consistency_key] = {
        "anchor_score": strategy_anchor_score,
        "strategy": strategy,
    }

    consistency_check = {
        "similar_case_match": similar_case_match,
        "strategy_distance": strategy_distance,
    }
    strategy_stability = {
        "anchor_score": strategy_anchor_score,
        "drift_detected": drift_detected,
        "final_strategy_locked": final_strategy_locked,
    }
    consistency_text = "策略不稳定，建议优化权重" if strategy_distance > 0.6 else ""
    if similar_case_match:
        strategy_reason = f"{strategy_reason}同类局势命中稳定策略，最终沿用：{strategy}。"
    if final_strategy_locked:
        strategy_reason = (
            f"{strategy_reason}策略漂移抑制触发：anchor差值{round(anchor_delta, 2)}小于10，"
            f"锁定上一策略：{strategy}。"
        )

    cost_text = (
        f"棋子费用分析：已匹配{len(costs)}个棋子，费用分布为{costs}，"
        f"高费卡{high_cost_count}个，低费卡{low_cost_count}个。"
        if costs
        else "棋子费用分析：暂无已匹配棋子费用。"
    )
    trait_text = (
        "trait统计结果："
        + "、".join(f"{trait}x{count}" for trait, count in trait_counter.items())
        + "。"
        if trait_counter
        else "trait统计结果：暂无已匹配羁绊。"
    )
    unknown_text = (
        f"未匹配棋子：{'、'.join(unknown_names)}。" if unknown_names else ""
    )

    explanation = (
        f"当前stage判断原因：{stage_reason}"
        f"三项Skill评分来源：经济score={economy_score}，由金币{gold}换算；"
        f"hp_score={hp_score}，由血量{hp}换算；"
        f"comp_score={comp_score}，由高费卡{high_cost_count}个、"
        f"成型羁绊{len(active_traits)}个、基础阵容分{base_comp_score}、"
        f"meta_bonus={meta_strength_score}、augment_score={augment_score}和board匹配度共同决定。"
        f"{cost_text}"
        f"{trait_text}"
        f"当前阵容倾向：{lineup_direction}。"
        f"Meta Awareness：{meta_reason}"
        f"Meta 对 strategy 的影响：版本强势阵容会提高阵容融合权重，"
        f"当前meta_tier={current_meta_tier}，meta_strength_score={meta_strength_score}。"
        f"{'由于未命中S/A阵容，阵容上限和转型优先级相对较低。' if current_meta_tier == 'B' else ''}"
        f"Augment 动态影响：当前判断为{augment_type}，augment_score={augment_score}，"
        f"{augment_info['impact']}；判断原因：{augment_reason}"
        f"Meta + Augment 组合影响：{current_meta_tier}级meta与{augment_type}共同修正阵容融合分，"
        f"使策略更偏向{stage_focus}与{lineup_direction}的结合。"
        f"动态权重系统：当前{stage_key}阶段权重为经济{stage_weights['economy']}、"
        f"血量{stage_weights['hp']}、阵容{stage_weights['comp']}。"
        f"{'冲突检测触发：低血量、S级meta与经济型augment同时出现，已提高血量权重并降低经济权重。' if conflict_mode else '冲突检测未触发，使用阶段默认权重。'}"
        f"决策收敛层：主导因素为{dominant_system}，{fusion_reason}"
        f"策略稳定性层：anchor_score={strategy_anchor_score}，"
        f"{'检测到策略漂移。' if drift_detected else '未检测到策略漂移。'}"
        f"{'已锁定上一策略以抑制频繁波动。' if final_strategy_locked else '未触发策略锁定。'}"
        f"stage_strategy逻辑：{stage_key}阶段，重点是{stage_focus}，行动建议为{stage_action}。"
        f"策略选择原因：{strategy_reason}"
        "本局推荐基于当前版本 + 经济 + 血量 + 阵容综合判断。"
        f"{consistency_text}"
        f"{unknown_text}"
    )

    chooses_economy = any(keyword in strategy for keyword in ["强经济", "存钱", "运营"])
    chooses_greedy_economy = any(keyword in strategy for keyword in ["强经济", "贪经济", "升人口"])
    chooses_combat = any(keyword in strategy for keyword in ["战力", "D牌", "稳血", "补战力"])

    if gold >= 50 and chooses_economy:
        economy_evaluation_score = 30
    elif gold >= 50:
        economy_evaluation_score = 22
    elif gold < 30 and chooses_economy:
        economy_evaluation_score = 8
    elif gold < 30:
        economy_evaluation_score = 24
    else:
        economy_evaluation_score = 20

    if hp < 40 and not chooses_combat:
        hp_evaluation_score = 8
    elif hp < 40:
        hp_evaluation_score = 28
    elif hp >= 70 and chooses_greedy_economy:
        hp_evaluation_score = 30
    elif hp >= 70:
        hp_evaluation_score = 24
    else:
        hp_evaluation_score = 20

    high_cost_matches_strategy = high_cost_count >= 2 and any(
        keyword in strategy for keyword in ["4费核心", "主C", "中后期"]
    )
    trait_matches_strategy = bool(active_traits) and any(
        trait in strategy for trait in active_traits
    )

    comp_evaluation_score = 20
    if high_cost_matches_strategy:
        comp_evaluation_score += 12
    elif high_cost_count >= 2:
        comp_evaluation_score += 4

    if trait_matches_strategy:
        comp_evaluation_score += 8
    elif active_traits:
        comp_evaluation_score += 3

    comp_evaluation_score = min(comp_evaluation_score, 40)
    strategy_score = (
        economy_evaluation_score + hp_evaluation_score + comp_evaluation_score
    )

    strategy_score = round(final_score)

    if strategy_score < 60:
        should_adjust = True
        if hp < 40:
            adjustment_hint = "当前策略不稳定，需要提升战力权重"
        elif gold > 50:
            adjustment_hint = "当前策略不稳定，需要增强经济策略稳定性"
        else:
            adjustment_hint = "当前策略不稳定，需要减少激进操作，提高生存优先级"
    elif strategy_score >= 80:
        should_adjust = False
        adjustment_hint = "当前策略稳定，可以继续强化该策略路径"
    else:
        should_adjust = False
        adjustment_hint = "当前策略基本可用，建议继续观察局势变化"

    learning_signal = {
        "should_adjust": should_adjust,
        "adjustment_hint": adjustment_hint,
    }

    if hp < 40 or strategy_score < 60 or game_strength == "弱":
        risk_level = "high"
    elif hp < 70 or strategy_score < 80 or game_strength == "一般":
        risk_level = "medium"
    else:
        risk_level = "low"

    product_insight = {
        "why_this_strategy": (
            f"当前推荐选择{strategy}，主要因为final_score={final_score}，"
            f"并结合{stage}阶段、{current_meta_tier}级meta和阵容匹配情况进行融合判断。"
        ),
        "key_factors": ["gold", "hp", "meta_tier"],
        "risk_level": risk_level,
    }

    decision_log = {
        "product_insight": product_insight,
        "input": {
            "level": level,
            "gold": gold,
            "hp": hp,
            "board": board,
        },
        "process": {
            "stage": {
                "result": stage,
                "rule": "level <= 5 为前期，level 6-7 为中期，level >= 8 为后期",
            },
            "game_strength": {
                "hp_score": hp_score,
                "economy_score": economy_score,
                "comp_score": comp_score,
                "final_score": final_score,
                "high_cost_count": high_cost_count,
                "low_cost_count": low_cost_count,
                "final_game_strength": game_strength,
            },
            "lineup_analysis": {
                "matched_champions": matched_champions,
                "unknown_names": unknown_names,
                "costs": costs,
                "high_cost_count": high_cost_count,
                "low_cost_count": low_cost_count,
                "lineup_direction": lineup_direction,
                "items_loaded": list(items.keys()),
            },
            "traits": {
                "trait_counts": dict(trait_counter),
                "trait_rules": {trait: traits.get(trait) for trait in trait_counter},
                "active_traits": active_traits,
            },
            "stage_strategy": {
                "stage_key": stage_key,
                "stage_focus": stage_focus,
                "stage_action": stage_action,
                "stage_reason": stage_reason,
            },
            "skill_debug": {
                "economy_score": economy_score,
                "hp_score": hp_score,
                "comp_score": comp_score,
                "final_score": final_score,
                "meta_debug": {
                    "detected_meta": current_meta_tier,
                    "meta_bonus": meta_strength_score,
                    "meta_reason": meta_reason,
                },
                "augment_debug": {
                    "detected_type": augment_type.replace("类", ""),
                    "augment_score": augment_score,
                    "reason": augment_reason,
                },
                "fusion_debug": {
                    "decision_axis_score": decision_axis_score,
                    "dominant_system": dominant_system,
                    "reason": fusion_reason,
                },
                "dynamic_weight_debug": {
                    "stage_weights": stage_weights,
                    "conflict_mode": conflict_mode,
                    "weight_adjustments": weight_adjustments,
                },
                "strategy_stability": strategy_stability,
            },
            "strategy_weights": {
                "priority_scores": priority_scores,
                "strategy_reason": strategy_reason,
            },
            "knowledge_base": {
                "meta_tier": current_meta_tier,
                "matched_meta_lineup": matched_meta_lineup,
                "meta_strength_score": meta_strength_score,
                "base_comp_score": base_comp_score,
                "augment_type": augment_type,
                "augment_score": augment_score,
                "augment_info": augment_info,
                "meta_lineups": meta_tiers,
                "stage_strategy_key": stage_key,
                "stage_strategy": current_stage_strategy,
            },
            "decision_axis": decision_axis,
            "strategy_stability": strategy_stability,
            "consistency_check": consistency_check,
            "evaluation": {
                "economy_score": economy_evaluation_score,
                "hp_score": hp_score,
                "comp_score": comp_evaluation_score,
                "total": strategy_score,
            },
            "learning_signal": learning_signal,
            "product_insight": product_insight,
        },
        "output": {
            "strategy": strategy,
            "explanation": explanation,
            "priority": priority,
            "strategy_score": strategy_score,
            "learning_signal": learning_signal,
            "product_insight": product_insight,
            "decision_axis": decision_axis,
            "strategy_stability": strategy_stability,
        },
    }

    ai_enhanced = enhance_explanation(
        {
            "stage": stage,
            "game_strength": game_strength,
            "priority": priority,
        },
        strategy,
        explanation,
        decision_log,
    )

    return {
        "stage": stage,
        "stage_focus": stage_focus,
        "stage_action": stage_action,
        "game_strength": game_strength,
        "strategy": strategy,
        "strategy_score": strategy_score,
        "decision_axis": decision_axis,
        "strategy_stability": strategy_stability,
        "learning_signal": learning_signal,
        "explanation": explanation,
        "priority": priority,
        "skill_debug": {
            "economy_score": economy_score,
            "hp_score": hp_score,
            "comp_score": comp_score,
            "final_score": final_score,
            "meta_debug": {
                "detected_meta": current_meta_tier,
                "meta_bonus": meta_strength_score,
                "meta_reason": meta_reason,
            },
            "augment_debug": {
                "detected_type": augment_type.replace("类", ""),
                "augment_score": augment_score,
                "reason": augment_reason,
            },
            "fusion_debug": {
                "decision_axis_score": decision_axis_score,
                "dominant_system": dominant_system,
                "reason": fusion_reason,
            },
            "dynamic_weight_debug": {
                "stage_weights": stage_weights,
                "conflict_mode": conflict_mode,
                "weight_adjustments": weight_adjustments,
            },
            "strategy_stability": strategy_stability,
        },
        "decision_log": decision_log,
        "ai_enhanced": {
            "ai_explanation": ai_enhanced["ai_explanation"],
            "coach_tip": ai_enhanced["coach_tip"],
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "jcc-ai",
        "version": "1.0",
    }


@app.post("/ocr/mock")
def ocr_mock(payload: OCRMockRequest) -> dict[str, Any]:
    return api_success(get_mock_game_state())


@app.post("/ocr/image")
async def ocr_image(request: Request) -> dict[str, Any]:
    temp_path = None

    try:
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            payload = OCRImageRequest(**await request.json())
            if payload.image_path:
                image_path = payload.image_path
            elif payload.image_base64:
                temp_path = save_base64_image_to_temp(payload.image_base64)
                image_path = temp_path
            else:
                return api_error("请提供 image_path 或 image_base64")
        elif content_type.startswith("image/"):
            image_bytes = await request.body()
            if not image_bytes:
                return api_error("图片内容为空")
            temp_path = save_raw_image_to_temp(image_bytes)
            image_path = temp_path
        else:
            return api_error("请使用 JSON base64、image_path 或 image/* 原始图片请求")

        data = extract_game_state_from_image(image_path)
        if not validate_ocr_game_state(data):
            return api_error("OCR structured output validation failed")
        return api_success(data)
    except Exception as exc:
        logger.exception("ocr image error")
        return api_error(str(exc))
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


@app.post("/analyze")
def analyze(payload: AnalyzeRequest) -> dict[str, Any]:
    try:
        data = analyze_game_state(payload.level, payload.gold, payload.hp, payload.board)
        return api_success(data)
    except Exception as exc:
        logger.exception("analyze error")
        return api_error(str(exc))


@app.post("/feedback")
def feedback(payload: FeedbackRequest) -> dict[str, Any]:
    try:
        return api_success(append_feedback_log(payload))
    except Exception as exc:
        logger.exception("feedback error")
        return api_error(str(exc))


if __name__ == "__main__":
    uvicorn.run("main:app", host=config.SERVER_HOST, port=config.SERVER_PORT, reload=True)
