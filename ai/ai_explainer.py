import json
import os
import urllib.error
import urllib.request
from typing import Any

import config


LLM_TIMEOUT_SECONDS = 5
LLM_RETRY_COUNT = 1


def enhance_explanation(
    game_state: dict[str, Any],
    strategy: str,
    explanation: str,
    decision_log: dict[str, Any],
) -> dict[str, str]:
    payload = {
        "stage": game_state.get("stage", ""),
        "game_strength": game_state.get("game_strength", ""),
        "strategy": strategy,
        "priority": game_state.get("priority", []),
        "decision_log": decision_log,
        "meta": game_state.get("meta", "optional context"),
    }

    if not config.ENABLE_AI:
        return fallback_explanation(explanation)

    prompt = build_prompt(payload)
    ai_result = call_llm(prompt, config.AI_PROVIDER)
    if ai_result is None:
        return fallback_explanation(explanation)

    return {
        "ai_explanation": str(ai_result.get("ai_explanation") or explanation),
        "coach_tip": str(ai_result.get("coach_tip") or ""),
        "warning": "",
    }


def call_llm(prompt: str, provider: str) -> dict[str, Any] | None:
    providers = ["deepseek", "openai", "qwen"] if provider == "auto" else [provider]

    for provider_name in providers:
        provider_config = get_provider_config(provider_name)
        if provider_config is None:
            continue

        for _ in range(LLM_RETRY_COUNT + 1):
            result = request_chat_completion(provider_config, prompt)
            if result is not None:
                return result

    return None


def get_provider_config(provider: str) -> dict[str, str] | None:
    provider_configs = {
        "deepseek": {
            "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions"),
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        },
        "openai": {
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"),
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        },
        "qwen": {
            "api_key": os.getenv("QWEN_API_KEY", ""),
            "base_url": os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            ),
            "model": os.getenv("QWEN_MODEL", "qwen-plus"),
        },
    }
    provider_config = provider_configs.get(provider.lower())
    if not provider_config or not provider_config["api_key"]:
        return None
    return provider_config


def request_chat_completion(provider_config: dict[str, str], prompt: str) -> dict[str, Any] | None:
    request_body = {
        "model": provider_config["model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是金铲铲高手教练。你只能增强解释和教练提示，"
                    "不能修改 strategy、priority、score 或 decision_log，"
                    "也不能让建议与既定策略冲突。"
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.2,
    }
    data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        provider_config["base_url"],
        data=data,
        headers={
            "Authorization": f"Bearer {provider_config['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT_SECONDS) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    content = (
        response_data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return parse_ai_content(content)


def build_prompt(payload: dict[str, Any]) -> str:
    return (
        "请把下面的金铲铲AI决策解释成普通玩家能理解并执行的话。\n"
        "只允许增强 explanation 和 coach_tip。\n"
        "禁止修改或重算 strategy、priority、score、decision_log。\n"
        "必须只输出 JSON，不要输出 Markdown。\n"
        "JSON格式：{\"ai_explanation\":\"\",\"coach_tip\":\"\"}\n"
        f"输入：{json.dumps(payload, ensure_ascii=False)}"
    )


def parse_ai_content(content: str) -> dict[str, Any] | None:
    if not content:
        return None

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    return {
        "ai_explanation": str(parsed.get("ai_explanation") or ""),
        "coach_tip": str(parsed.get("coach_tip") or ""),
    }


def fallback_explanation(explanation: str) -> dict[str, str]:
    return {
        "ai_explanation": explanation,
        "coach_tip": "",
        "warning": "",
    }
