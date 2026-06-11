# JCC S17 AI Backend

FastAPI backend with authentication, license activation, and S17 game strategy analysis.

## Configure Environment

Copy the example file:

```powershell
Copy-Item .env.example .env
```

Fill API keys in `.env` as needed:

```env
DEEPSEEK_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...
OPENAI_API_KEY=sk-...
APIROUTER_API_KEY=sk-or-...
AIPOWER_API_KEY=sk-...
AIPOWER_BASE_URL=https://your-aipower-endpoint/v1/chat/completions
DEFAULT_AI_PROVIDER=auto
ENABLE_AI_RECOMMENDATION=false
```

Keep `ENABLE_AI_RECOMMENDATION=false` to use local rule recommendations only. Set it to `true` after adding an API key if you want external AI recommendations.

Optional provider overrides:

```env
DEEPSEEK_BASE_URL=https://api.deepseek.com/chat/completions
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
OPENAI_BASE_URL=https://api.openai.com/v1/chat/completions
APIROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions
APIROUTER_MODEL=openai/gpt-4o-mini
AIPOWER_MODEL=auto
```

## Start Service

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

## Test Game Analyze

Enable external AI in `.env`:

```env
ENABLE_AI_RECOMMENDATION=true
DEFAULT_AI_PROVIDER=auto
DEEPSEEK_API_KEY=sk-...
DASHSCOPE_API_KEY=sk-...
OPENAI_API_KEY=sk-...
APIROUTER_API_KEY=sk-or-...
AIPOWER_API_KEY=sk-...
AIPOWER_BASE_URL=https://your-aipower-endpoint/v1/chat/completions
```

Test `preferred_model=auto`:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/game/analyze -H "Content-Type: application/json" -d "{\"level\":6,\"gold\":32,\"hp\":78,\"round\":\"3-5\",\"shop\":[\"卡莎\",\"慎\",\"阿狸\",\"亚索\",\"妮蔻\"],\"board\":[\"盖伦2\",\"阿狸1\",\"慎1\"],\"bench\":[\"亚索1\",\"妮蔻1\"],\"items\":[\"反曲弓\",\"大棒\",\"锁子甲\"],\"god_choices\":[\"索拉卡\",\"锤石\"],\"selected_gods\":[\"索拉卡\"],\"main_god\":null,\"preferred_model\":\"auto\"}"
```

Switch providers by changing `preferred_model`:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/game/analyze -H "Content-Type: application/json" -d "{\"level\":6,\"gold\":32,\"hp\":78,\"round\":\"3-5\",\"shop\":[\"卡莎\",\"慎\",\"阿狸\",\"亚索\",\"妮蔻\"],\"board\":[\"盖伦2\",\"阿狸1\",\"慎1\"],\"bench\":[\"亚索1\",\"妮蔻1\"],\"items\":[\"反曲弓\",\"大棒\",\"锁子甲\"],\"god_choices\":[\"索拉卡\",\"锤石\"],\"selected_gods\":[\"索拉卡\"],\"main_god\":null,\"preferred_model\":\"deepseek\"}"

curl.exe -X POST http://127.0.0.1:8000/api/game/analyze -H "Content-Type: application/json" -d "{\"level\":6,\"gold\":32,\"hp\":78,\"round\":\"3-5\",\"shop\":[\"卡莎\",\"慎\",\"阿狸\",\"亚索\",\"妮蔻\"],\"board\":[\"盖伦2\",\"阿狸1\",\"慎1\"],\"bench\":[\"亚索1\",\"妮蔻1\"],\"items\":[\"反曲弓\",\"大棒\",\"锁子甲\"],\"god_choices\":[\"索拉卡\",\"锤石\"],\"selected_gods\":[\"索拉卡\"],\"main_god\":null,\"preferred_model\":\"qwen\"}"

curl.exe -X POST http://127.0.0.1:8000/api/game/analyze -H "Content-Type: application/json" -d "{\"level\":6,\"gold\":32,\"hp\":78,\"round\":\"3-5\",\"shop\":[\"卡莎\",\"慎\",\"阿狸\",\"亚索\",\"妮蔻\"],\"board\":[\"盖伦2\",\"阿狸1\",\"慎1\"],\"bench\":[\"亚索1\",\"妮蔻1\"],\"items\":[\"反曲弓\",\"大棒\",\"锁子甲\"],\"god_choices\":[\"索拉卡\",\"锤石\"],\"selected_gods\":[\"索拉卡\"],\"main_god\":null,\"preferred_model\":\"openai\"}"
```

Response includes rule recommendations plus model metadata:

```json
{
  "status": "ok",
  "recommendations": [],
  "model_used": "qwen-max",
  "estimated_cost_usd": 0.001,
  "ai_status": "success",
  "ai_error": null
}
```
