import { useMemo, useState } from "react";
import ScreenshotPage from "./components/ScreenshotPage";
import type { AnalyzeResponse, GameState } from "./types";

type View = "login" | "license" | "analyze" | "screenshot" | "results" | "settings";

const defaultBackendUrl = "http://1.12.73.114:8000";

const defaultGameState: GameState = {
  level: 6,
  gold: 32,
  hp: 78,
  round: "3-5",
  shop: ["卡莎", "慎", "阿狸", "亚索", "妮蔻"],
  board: ["盖伦2", "阿狸1", "慎1"],
  bench: ["亚索1", "妮蔻1"],
  items: ["反曲弓", "大棒", "锁子甲"],
  god_choices: ["索拉卡", "锤石"],
  selected_gods: ["索拉卡"],
  main_god: null,
  preferred_model: "auto",
};

const readStorage = (key: string, fallback: string) => localStorage.getItem(key) || fallback;

const parseList = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

function App() {
  const [view, setView] = useState<View>("login");
  const [backendUrl, setBackendUrl] = useState(() => readStorage("backendUrl", defaultBackendUrl));
  const [token, setToken] = useState(() => readStorage("token", ""));
  const [username, setUsername] = useState("test");
  const [password, setPassword] = useState("123456");
  const [licenseKey, setLicenseKey] = useState("");
  const [gameState, setGameState] = useState<GameState>(defaultGameState);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [statusText, setStatusText] = useState("");

  const navItems: Array<[View, string]> = useMemo(
    () => [
      ["login", "登录"],
      ["license", "卡密"],
      ["analyze", "局势"],
      ["screenshot", "截图"],
      ["results", "结果"],
      ["settings", "设置"],
    ],
    [],
  );

  const apiPost = async <T,>(path: string, body: unknown): Promise<T> => {
    const response = await fetch(`${backendUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: token ? `Bearer ${token}` : "",
      },
      body: JSON.stringify(body),
    });
    return (await response.json()) as T;
  };

  const login = async () => {
    setStatusText("登录中...");
    const response = await apiPost<{ status: string; data?: { token: string }; message?: string }>(
      "/login",
      { username, password },
    );
    if (response.status === "ok" && response.data?.token) {
      localStorage.setItem("token", response.data.token);
      setToken(response.data.token);
      setStatusText("登录成功");
      setView("analyze");
      return;
    }
    setStatusText(response.message || "登录失败");
  };

  const activateLicense = async () => {
    setStatusText("激活中...");
    const response = await apiPost<{ status: string; message?: string; data?: unknown }>(
      "/license/activate",
      { license_key: licenseKey, token },
    );
    setStatusText(response.status === "ok" ? "卡密激活成功" : response.message || "卡密激活失败");
  };

  const analyze = async () => {
    setStatusText("获取推荐中...");
    const response = await apiPost<AnalyzeResponse>("/api/game/analyze", gameState);
    setResult(response);
    setStatusText(response.status === "ok" ? "推荐已更新" : "推荐请求失败");
    setView("results");
  };

  const saveSettings = () => {
    localStorage.setItem("backendUrl", backendUrl);
    setStatusText("设置已保存");
  };

  const updateGameState = <K extends keyof GameState>(key: K, value: GameState[K]) => {
    setGameState((current) => ({ ...current, [key]: value }));
  };

  const handleScreenshotResult = (response: AnalyzeResponse) => {
    setResult(response);
    setStatusText(response.status === "ok" ? "截图推荐已更新" : "截图推荐请求失败");
    setView("results");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <div className="brand">JCC S17</div>
          <div className="subtitle">星神 AI 推荐助手</div>
        </div>
        <nav>
          {navItems.map(([key, label]) => (
            <button
              key={key}
              className={view === key ? "nav-button active" : "nav-button"}
              onClick={() => setView(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="safety-note">仅展示策略建议，不自动操作游戏，不注入，不读取内存。</div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <h1>金铲铲 S17 星神 AI 推荐助手</h1>
            <p>{backendUrl}</p>
          </div>
          <span className={token ? "badge ok" : "badge"}>{token ? "已登录" : "未登录"}</span>
        </header>

        {statusText && <div className="status-line">{statusText}</div>}

        {view === "login" && (
          <section className="panel compact">
            <h2>登录</h2>
            <label>
              Username
              <input value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <button className="primary" onClick={login}>
              登录
            </button>
          </section>
        )}

        {view === "license" && (
          <section className="panel compact">
            <h2>卡密激活</h2>
            <label>
              License Key
              <input
                value={licenseKey}
                onChange={(event) => setLicenseKey(event.target.value)}
                placeholder="输入卡密"
              />
            </label>
            <button className="primary" onClick={activateLicense}>
              激活
            </button>
          </section>
        )}

        {view === "analyze" && (
          <section className="panel">
            <div className="panel-title">
              <h2>手动局势输入</h2>
              <button className="primary" onClick={analyze}>
                获取推荐
              </button>
            </div>
            <div className="form-grid">
              <label>
                Level
                <input
                  type="number"
                  value={gameState.level}
                  onChange={(event) => updateGameState("level", Number(event.target.value))}
                />
              </label>
              <label>
                Gold
                <input
                  type="number"
                  value={gameState.gold}
                  onChange={(event) => updateGameState("gold", Number(event.target.value))}
                />
              </label>
              <label>
                HP
                <input
                  type="number"
                  value={gameState.hp}
                  onChange={(event) => updateGameState("hp", Number(event.target.value))}
                />
              </label>
              <label>
                Round
                <input value={gameState.round} onChange={(event) => updateGameState("round", event.target.value)} />
              </label>
              <label>
                Preferred Model
                <select
                  value={gameState.preferred_model}
                  onChange={(event) => updateGameState("preferred_model", event.target.value)}
                >
                  <option value="auto">auto</option>
                  <option value="deepseek">deepseek</option>
                  <option value="qwen">qwen</option>
                  <option value="openai">openai</option>
                  <option value="apirouter">apirouter</option>
                  <option value="aipower">aipower</option>
                </select>
              </label>
              <label>
                Main God
                <input
                  value={gameState.main_god || ""}
                  onChange={(event) => updateGameState("main_god", event.target.value || null)}
                  placeholder="null"
                />
              </label>
            </div>

            <div className="text-grid">
              <ListInput title="Shop" value={gameState.shop} onChange={(value) => updateGameState("shop", value)} />
              <ListInput title="Board" value={gameState.board} onChange={(value) => updateGameState("board", value)} />
              <ListInput title="Bench" value={gameState.bench} onChange={(value) => updateGameState("bench", value)} />
              <ListInput title="Items" value={gameState.items} onChange={(value) => updateGameState("items", value)} />
              <ListInput
                title="God Choices"
                value={gameState.god_choices}
                onChange={(value) => updateGameState("god_choices", value)}
              />
              <ListInput
                title="Selected Gods"
                value={gameState.selected_gods}
                onChange={(value) => updateGameState("selected_gods", value)}
              />
            </div>
          </section>
        )}

        {view === "screenshot" && (
          <ScreenshotPage backendUrl={backendUrl} token={token} onResult={handleScreenshotResult} />
        )}

        {view === "results" && (
          <section className="panel">
            <h2>推荐结果</h2>
            {!result ? (
              <div className="empty">暂无推荐结果</div>
            ) : (
              <>
                <div className="metrics">
                  <Metric label="Model" value={result.model_used || "-"} />
                  <Metric label="Cost USD" value={String(result.estimated_cost_usd ?? "-")} />
                  <Metric label="AI Status" value={result.ai_status || "-"} />
                  <Metric label="AI Error" value={result.ai_error || "-"} />
                </div>
                <div className="recommendations">
                  {result.recommendations.map((item, index) => (
                    <article className="recommendation" key={`${item.action}-${item.target}-${index}`}>
                      <div className="rec-head">
                        <span>{item.action}</span>
                        {item.target && <strong>{item.target}</strong>}
                        {item.item && <em>{item.item}</em>}
                      </div>
                      <p>{item.reason}</p>
                    </article>
                  ))}
                </div>
              </>
            )}
          </section>
        )}

        {view === "settings" && (
          <section className="panel compact">
            <h2>设置</h2>
            <label>
              后端地址
              <input value={backendUrl} onChange={(event) => setBackendUrl(event.target.value)} />
            </label>
            <button className="primary" onClick={saveSettings}>
              保存设置
            </button>
          </section>
        )}
      </main>
    </div>
  );
}

function ListInput({
  title,
  value,
  onChange,
}: {
  title: string;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <label>
      {title}
      <textarea value={value.join(",")} onChange={(event) => onChange(parseList(event.target.value))} />
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export default App;
