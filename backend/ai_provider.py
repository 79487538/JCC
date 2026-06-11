import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_OUTPUT_TOKENS = 700


def env_enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def is_ai_recommendation_enabled() -> bool:
    return env_enabled("ENABLE_AI_RECOMMENDATION", "false")


def get_default_ai_provider() -> str:
    return os.getenv("DEFAULT_AI_PROVIDER", "auto").strip().lower() or "auto"


def _model_configs() -> Dict[str, Dict[str, Any]]:
    return {
        "deepseek-v4-flash": {
            "provider": "deepseek",
            "endpoint": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions"),
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash"),
            "input_per_1m": 0.28,
            "output_per_1m": 0.42,
        },
        "deepseek-r1": {
            "provider": "deepseek",
            "endpoint": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions"),
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": os.getenv("DEEPSEEK_R1_MODEL", "deepseek-r1"),
            "input_per_1m": 0.55,
            "output_per_1m": 2.19,
        },
        "qwen-plus": {
            "provider": "qwen",
            "endpoint": os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            ),
            "api_key_env": "DASHSCOPE_API_KEY",
            "model": os.getenv("QWEN_PLUS_MODEL", "qwen-plus"),
            "input_per_1m": 0.30,
            "output_per_1m": 0.90,
        },
        "qwen-max": {
            "provider": "qwen",
            "endpoint": os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            ),
            "api_key_env": "DASHSCOPE_API_KEY",
            "model": os.getenv("QWEN_MAX_MODEL", "qwen-max"),
            "input_per_1m": 2.40,
            "output_per_1m": 9.60,
        },
        "gpt-4o-mini": {
            "provider": "openai",
            "endpoint": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"),
            "api_key_env": "OPENAI_API_KEY",
            "model": os.getenv("OPENAI_MINI_MODEL", "gpt-4o-mini"),
            "input_per_1m": 0.15,
            "output_per_1m": 0.60,
        },
        "gpt-4o": {
            "provider": "openai",
            "endpoint": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"),
            "api_key_env": "OPENAI_API_KEY",
            "model": os.getenv("OPENAI_HIGH_MODEL", "gpt-4o"),
            "input_per_1m": 5.00,
            "output_per_1m": 15.00,
        },
        "apirouter-auto": {
            "provider": "apirouter",
            "endpoint": os.getenv(
                "APIROUTER_BASE_URL",
                "https://openrouter.ai/api/v1/chat/completions",
            ),
            "api_key_env": "APIROUTER_API_KEY",
            "model": os.getenv("APIROUTER_MODEL", "openai/gpt-4o-mini"),
            "input_per_1m": 0.50,
            "output_per_1m": 1.50,
        },
        "aipower-auto": {
            "provider": "aipower",
            "endpoint": os.getenv("AIPOWER_BASE_URL", ""),
            "api_key_env": "AIPOWER_API_KEY",
            "model": os.getenv("AIPOWER_MODEL", "auto"),
            "input_per_1m": 0.50,
            "output_per_1m": 1.50,
        },
    }


MODEL_ALIASES = {
    "deepseek": "deepseek-v4-flash",
    "deepseek-flash": "deepseek-v4-flash",
    "deepseek-v4": "deepseek-v4-flash",
    "deepseek-r1": "deepseek-r1",
    "qwen": "qwen-plus",
    "qwen-plus": "qwen-plus",
    "qwen-max": "qwen-max",
    "openai": "gpt-4o-mini",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4o": "gpt-4o",
    "apirouter": "apirouter-auto",
    "openrouter": "apirouter-auto",
    "aipower": "aipower-auto",
}


API_KEY_CONFIG_PROMPT = """
API Key 配置示例：
复制 .env.example 为 .env 后按需填写：
DEEPSEEK_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...
OPENAI_API_KEY=sk-...
APIROUTER_API_KEY=sk-or-...
AIPOWER_API_KEY=sk-...
AIPOWER_BASE_URL=https://your-aipower-endpoint/v1/chat/completions
DEFAULT_AI_PROVIDER=auto
ENABLE_AI_RECOMMENDATION=true
"""


def _normalize_model_name(model_name: str) -> str:
    normalized = (model_name or "auto").strip().lower()
    if normalized == "auto":
        normalized = get_default_ai_provider()
        if normalized == "auto":
            normalized = "deepseek-v4-flash"
    return MODEL_ALIASES.get(normalized, normalized)


def _estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return max(1, len(text) // 4)


def _estimate_cost_usd(config: Dict[str, Any], prompt_tokens: int, output_tokens: int) -> float:
    input_cost = prompt_tokens / 1_000_000 * config["input_per_1m"]
    output_cost = output_tokens / 1_000_000 * config["output_per_1m"]
    return round(input_cost + output_cost, 6)


def _build_messages(input_data: Any) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是一个金铲铲 S17 星神版本游戏策略分析助手。"
                "只返回 JSON，不要输出 Markdown。"
                "JSON 格式必须为："
                "{\"recommendations\":[{\"action\":\"...\",\"target\":\"...\","
                "\"item\":\"...\",\"reason\":\"...\"}]}。"
                "不要调用游戏客户端，不要注入，不要读取内存。"
                f"\n\n{API_KEY_CONFIG_PROMPT}"
            ),
        },
        {"role": "user", "content": json.dumps(input_data, ensure_ascii=False)},
    ]


def _base_result(
    config: Dict[str, Any],
    selected_model: str,
    prompt_tokens: int,
    output_tokens: int,
    status: str,
    error: Optional[str],
    content: str = "",
) -> Dict[str, Any]:
    return {
        "provider": config["provider"],
        "model_used": config["model"],
        "model_key": selected_model,
        "content": content,
        "cost_estimate_usd": _estimate_cost_usd(config, prompt_tokens, output_tokens),
        "prompt_tokens_estimate": prompt_tokens,
        "completion_tokens_estimate": output_tokens,
        "ai_status": status,
        "error": error,
    }


def _extract_json_text(content: str) -> str:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text


def parse_ai_json(content: str) -> Dict[str, Any]:
    return json.loads(_extract_json_text(content))


def _post_chat_completion(config: Dict[str, Any], input_data: Any, max_tokens: int) -> Dict[str, Any]:
    api_key = os.getenv(config["api_key_env"])
    endpoint = config["endpoint"]

    if not api_key:
        raise RuntimeError(f"missing api key env: {config['api_key_env']}")
    if not endpoint:
        raise RuntimeError("missing endpoint configuration")

    body = {
        "model": config["model"],
        "messages": _build_messages(input_data),
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    except TimeoutError as exc:
        raise RuntimeError("request timed out") from exc

    data = json.loads(raw)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("empty model response")
    return {"content": content, "raw": data}


def call_ai_model(model_name, input, output_estimate=True):
    configs = _model_configs()
    selected_model = _normalize_model_name(model_name)
    config = configs.get(selected_model)
    if not config:
        selected_model = "deepseek-v4-flash"
        config = configs[selected_model]

    prompt_tokens = _estimate_tokens(input)
    output_tokens = DEFAULT_OUTPUT_TOKENS if output_estimate is True else int(output_estimate or 0)

    if not is_ai_recommendation_enabled():
        return _base_result(
            config,
            selected_model,
            prompt_tokens,
            output_tokens,
            "disabled",
            "AI recommendation disabled by ENABLE_AI_RECOMMENDATION=false",
        )

    try:
        completion = _post_chat_completion(config, input, max_tokens=max(128, output_tokens))
    except Exception as exc:
        return _base_result(
            config,
            selected_model,
            prompt_tokens,
            output_tokens,
            "failed",
            str(exc),
        )

    return _base_result(
        config,
        selected_model,
        prompt_tokens,
        output_tokens,
        "success",
        None,
        completion["content"],
    )
