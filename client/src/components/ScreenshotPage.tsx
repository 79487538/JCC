import { useEffect, useMemo, useRef, useState } from "react";
import {
  defaultRecognizedState,
  loadRegions,
  recognitionFields,
  recognizeGameStateFromScreenshot,
  saveRegions,
  listScreenshotSources,
  type FieldRecognitionResult,
  type RecognitionField,
  type RecognitionRegion,
} from "../screenshot_recognizer";
import type { AnalyzeResponse, GameState, ScreenshotSource } from "../types";

type Props = {
  backendUrl: string;
  token: string;
  onResult: (response: AnalyzeResponse) => void;
};

const preferredModels = ["auto", "deepseek", "qwen", "openai", "apirouter", "aipower"];
const fieldLabels: Record<RecognitionField, string> = {
  level: "等级",
  gold: "金币",
  hp: "血量",
  round: "回合",
  shop: "商店",
  board: "场上",
  bench: "备战席",
  items: "装备",
  god_choices: "星神选择",
};

function stripMetadata(state: GameState): GameState {
  return {
    level: Number(state.level) || defaultRecognizedState.level,
    gold: Number(state.gold) || defaultRecognizedState.gold,
    hp: Number(state.hp) || defaultRecognizedState.hp,
    round: state.round || defaultRecognizedState.round,
    shop: Array.isArray(state.shop) ? state.shop : defaultRecognizedState.shop,
    board: Array.isArray(state.board) ? state.board : defaultRecognizedState.board,
    bench: Array.isArray(state.bench) ? state.bench : defaultRecognizedState.bench,
    items: Array.isArray(state.items) ? state.items : defaultRecognizedState.items,
    god_choices: Array.isArray(state.god_choices) ? state.god_choices : defaultRecognizedState.god_choices,
    selected_gods: Array.isArray(state.selected_gods)
      ? state.selected_gods
      : defaultRecognizedState.selected_gods,
    main_god: state.main_god || null,
    preferred_model: state.preferred_model || "auto",
  };
}

export default function ScreenshotPage({ backendUrl, token, onResult }: Props) {
  const [sources, setSources] = useState<ScreenshotSource[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [preferredModel, setPreferredModel] = useState("auto");
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [regions, setRegions] = useState(() => loadRegions());
  const [status, setStatus] = useState("");
  const [recognizedState, setRecognizedState] = useState<GameState>(defaultRecognizedState);
  const [editableJson, setEditableJson] = useState(JSON.stringify(defaultRecognizedState, null, 2));
  const [fieldResults, setFieldResults] = useState<Record<string, FieldRecognitionResult>>({});
  const busyRef = useRef(false);

  const selectedSource = useMemo(
    () => sources.find((source) => source.id === selectedSourceId),
    [selectedSourceId, sources],
  );

  const refreshSources = async () => {
    setStatus("正在读取可截图窗口...");
    const list = await listScreenshotSources();
    setSources(list);
    setSelectedSourceId((current) => current || list[0]?.id || "");
    setStatus(list.length > 0 ? "请选择游戏窗口或屏幕" : "未发现可截图窗口");
  };

  const updateRegion = (field: RecognitionField, key: keyof RecognitionRegion, value: number) => {
    setRegions((current) => ({
      ...current,
      [field]: {
        ...current[field],
        [key]: Math.max(0, value),
      },
    }));
  };

  const persistRegions = () => {
    saveRegions(regions);
    setStatus("识别区域已保存到本地");
  };

  const sendAnalyze = async (payload: GameState) => {
    const response = await fetch(`${backendUrl}/api/game/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: token ? `Bearer ${token}` : "",
      },
      body: JSON.stringify(payload),
    });
    const data = (await response.json()) as AnalyzeResponse;
    onResult(data);
    return data;
  };

  const captureAndRecognize = async () => {
    if (!selectedSourceId || busyRef.current) {
      return;
    }

    busyRef.current = true;
    try {
      setStatus("正在按区域截图和 OCR 识别...");
      const state = await recognizeGameStateFromScreenshot(selectedSourceId, preferredModel, regions);
      const gameState = stripMetadata(state);
      setRecognizedState(gameState);
      setEditableJson(JSON.stringify(gameState, null, 2));
      setFieldResults(state.field_results);
      setStatus("识别完成，请确认或编辑 JSON 后获取推荐");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(message);
    } finally {
      busyRef.current = false;
    }
  };

  const confirmAndAnalyze = async () => {
    try {
      const parsed = stripMetadata(JSON.parse(editableJson) as GameState);
      setRecognizedState(parsed);
      setStatus("正在请求后端推荐...");
      const response = await sendAnalyze(parsed);
      setStatus(response.status === "ok" ? "推荐已更新" : "推荐请求失败");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(`JSON 无效：${message}`);
    }
  };

  useEffect(() => {
    void refreshSources();
  }, []);

  useEffect(() => {
    if (!autoEnabled) {
      return;
    }
    const timer = window.setInterval(() => {
      void captureAndRecognize();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [autoEnabled, selectedSourceId, preferredModel, regions]);

  return (
    <section className="panel">
      <div className="panel-title">
        <h2>截图识别局势</h2>
        <div className="button-row">
          <button className="nav-button inline" onClick={captureAndRecognize}>
            手动截图识别
          </button>
          <button className="primary" onClick={confirmAndAnalyze}>
            确认并获取推荐
          </button>
        </div>
      </div>

      <div className="form-grid">
        <label>
          截图来源
          <select value={selectedSourceId} onChange={(event) => setSelectedSourceId(event.target.value)}>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Preferred Model
          <select value={preferredModel} onChange={(event) => setPreferredModel(event.target.value)}>
            {preferredModels.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={autoEnabled}
            onChange={(event) => setAutoEnabled(event.target.checked)}
          />
          自动识别局势
        </label>
      </div>

      <div className="panel-title secondary">
        <button className="nav-button inline" onClick={refreshSources}>
          刷新窗口列表
        </button>
        <button className="nav-button inline" onClick={persistRegions}>
          保存区域配置
        </button>
        <span className="muted">{status}</span>
      </div>

      {selectedSource && (
        <div className="screenshot-preview">
          <img src={selectedSource.thumbnailDataUrl} alt={selectedSource.name} />
          <div>
            <strong>{selectedSource.name}</strong>
            <p>仅截图识别和展示建议，不自动操作游戏，不注入，不读取内存。</p>
          </div>
        </div>
      )}

      <h3 className="section-heading">识别区域校准</h3>
      <div className="region-grid">
        {recognitionFields.map((field) => (
          <div className="region-row" key={field}>
            <strong>{fieldLabels[field]}</strong>
            {(["x", "y", "width", "height"] as const).map((key) => (
              <label key={key}>
                {key}
                <input
                  type="number"
                  value={regions[field][key]}
                  onChange={(event) => updateRegion(field, key, Number(event.target.value))}
                />
              </label>
            ))}
          </div>
        ))}
      </div>

      <h3 className="section-heading">识别结果确认</h3>
      <div className="text-grid">
        <label>
          可编辑 JSON
          <textarea value={editableJson} onChange={(event) => setEditableJson(event.target.value)} />
        </label>
        <div className="field-results">
          {recognitionFields.map((field) => {
            const result = fieldResults[field];
            const lowConfidence = !result || result.confidence < 55 || result.fallback_used;
            return (
              <article className={lowConfidence ? "field-card warning" : "field-card"} key={field}>
                <div>
                  <strong>{fieldLabels[field]}</strong>
                  {lowConfidence && <span>建议人工确认</span>}
                </div>
                <p>confidence: {result?.confidence ?? "-"}</p>
                <p>raw: {result?.text || "-"}</p>
                <p>parsed: {JSON.stringify(result?.parsed ?? recognizedState[field])}</p>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
