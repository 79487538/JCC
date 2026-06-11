import {
  Activity,
  Clipboard,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings,
  Trash2,
  Users,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import { FormEvent, useEffect, useMemo, useState } from "react";

const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const API_BASE_KEY = "jcc_admin_api_base";
const TOKEN_KEY = "jcc_admin_token";
const EMPTY_AI_CONFIG_FORM: AIConfigForm = {
  provider: "deepseek",
  model_name: "deepseek-v4-flash",
  api_key: "",
  base_url: "",
  enabled: true,
  is_default: false,
  description: "",
};

type DashboardData = {
  total_users: number;
  total_licenses: number;
  active_licenses: number;
  expired_licenses: number;
  total_ai_calls: number;
  total_ai_cost_usd: number;
  today_ai_calls: number;
  today_ai_cost_usd: number;
};

type License = {
  id: number;
  license_key: string;
  duration_days: number;
  status: string;
  activated_by: number | null;
  activated_at: string | null;
  expires_at: string | null;
  device_limit: number;
};

type AdminUser = {
  id: number;
  username: string;
  email: string;
  created_at: string;
  license_status: string;
  license_expires_at: string | null;
};

type AIUsageLog = {
  id: number;
  user_id: number | null;
  license_key: string | null;
  model_used: string;
  estimated_cost_usd: number;
  ai_status: string;
  created_at: string;
};

type AIConfig = {
  id: number;
  provider: string;
  model_name: string;
  api_key: string;
  base_url: string | null;
  enabled: boolean;
  is_default: boolean;
  description: string | null;
  created_at: string;
  updated_at: string;
};

type AIConfigForm = {
  id?: number;
  provider: string;
  model_name: string;
  api_key: string;
  base_url: string;
  enabled: boolean;
  is_default: boolean;
  description: string;
};

type AIConfigTestResult = {
  status: string;
  message: string;
  model_used: string;
  estimated_cost_usd: number;
};

type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

type AIUsagePage = PageResult<AIUsageLog> & {
  total_calls: number;
  total_cost_usd: number;
};

type ApiResponse<T> = {
  status: "ok" | "error";
  data?: T;
  message?: string;
  detail?: string;
};

type View = "dashboard" | "licenses" | "users" | "ai-usage" | "ai-config";

function getApiBase() {
  return localStorage.getItem(API_BASE_KEY) || DEFAULT_API_BASE;
}

async function apiRequest<T>(
  path: string,
  token: string | null,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${getApiBase()}${path}`, { ...options, headers });
  const body = (await response.json().catch(() => ({}))) as ApiResponse<T>;
  if (!response.ok || body.status === "error") {
    throw new Error(body.detail || body.message || "请求失败");
  }
  return body.data as T;
}

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatCost(value: number | undefined) {
  return `$${(value ?? 0).toFixed(6)}`;
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [apiBase, setApiBase] = useState(() => getApiBase());
  const [view, setView] = useState<View>("dashboard");
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [licenses, setLicenses] = useState<License[]>([]);
  const [users, setUsers] = useState<PageResult<AdminUser>>({
    items: [],
    total: 0,
    page: 1,
    page_size: 20,
  });
  const [aiUsage, setAiUsage] = useState<AIUsagePage>({
    items: [],
    total: 0,
    page: 1,
    page_size: 20,
    total_calls: 0,
    total_cost_usd: 0,
  });
  const [aiConfigs, setAiConfigs] = useState<AIConfig[]>([]);
  const [aiConfigForm, setAiConfigForm] = useState<AIConfigForm>({
    ...EMPTY_AI_CONFIG_FORM,
  });
  const [aiConfigTest, setAiConfigTest] = useState<Record<number, string>>({});
  const [userKeyword, setUserKeyword] = useState("");
  const [aiLicenseKey, setAiLicenseKey] = useState("");
  const [aiUserId, setAiUserId] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [durationDays, setDurationDays] = useState(30);
  const [deviceLimit, setDeviceLimit] = useState(1);
  const [count, setCount] = useState(10);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const sortedLicenses = useMemo(
    () => [...licenses].sort((a, b) => b.id - a.id),
    [licenses],
  );

  const totalUserPages = Math.max(1, Math.ceil(users.total / users.page_size));
  const totalAiPages = Math.max(1, Math.ceil(aiUsage.total / aiUsage.page_size));

  async function loadDashboard(activeToken = token) {
    if (!activeToken) {
      return;
    }
    const data = await apiRequest<DashboardData>("/admin/dashboard", activeToken);
    setDashboard(data);
  }

  async function loadLicenses(activeToken = token) {
    if (!activeToken) {
      return;
    }
    const data = await apiRequest<License[]>("/admin/licenses", activeToken);
    setLicenses(data);
  }

  async function loadUsers(
    activeToken = token,
    page = users.page,
    keyword = userKeyword,
  ) {
    if (!activeToken) {
      return;
    }
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(users.page_size),
    });
    if (keyword.trim()) {
      params.set("keyword", keyword.trim());
    }
    const data = await apiRequest<PageResult<AdminUser>>(
      `/admin/users?${params.toString()}`,
      activeToken,
    );
    setUsers(data);
  }

  async function loadAiUsage(
    activeToken = token,
    page = aiUsage.page,
    licenseKey = aiLicenseKey,
    userId = aiUserId,
  ) {
    if (!activeToken) {
      return;
    }
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(aiUsage.page_size),
    });
    if (licenseKey.trim()) {
      params.set("license_key", licenseKey.trim());
    }
    if (userId.trim()) {
      params.set("user_id", userId.trim());
    }
    const data = await apiRequest<AIUsagePage>(
      `/admin/ai-usage?${params.toString()}`,
      activeToken,
    );
    setAiUsage(data);
  }

  async function loadAiConfigs(activeToken = token) {
    if (!activeToken) {
      return;
    }
    const data = await apiRequest<AIConfig[]>("/admin/ai-config", activeToken);
    setAiConfigs(data);
  }

  async function refreshCurrent(activeToken = token) {
    if (!activeToken) {
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      if (view === "dashboard") {
        await loadDashboard(activeToken);
      } else if (view === "licenses") {
        await Promise.all([loadDashboard(activeToken), loadLicenses(activeToken)]);
      } else if (view === "users") {
        await loadUsers(activeToken);
      } else if (view === "ai-config") {
        await loadAiConfigs(activeToken);
      } else {
        await loadAiUsage(activeToken);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshCurrent();
  }, [token, view]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      const data = await apiRequest<{ admin_token: string }>("/admin/login", null, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      localStorage.setItem(TOKEN_KEY, data.admin_token);
      setToken(data.admin_token);
      setPassword("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  function saveApiBase() {
    const normalized = apiBase.trim() || DEFAULT_API_BASE;
    localStorage.setItem(API_BASE_KEY, normalized);
    setApiBase(normalized);
    setMessage("Backend address saved");
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setDashboard(null);
    setLicenses([]);
    setUsers({ items: [], total: 0, page: 1, page_size: 20 });
    setAiUsage({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      total_calls: 0,
      total_cost_usd: 0,
    });
    setAiConfigs([]);
    setAiConfigForm({ ...EMPTY_AI_CONFIG_FORM });
    setAiConfigTest({});
  }

  async function createLicenses(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      const created = await apiRequest<License[]>("/admin/licenses/create", token, {
        method: "POST",
        body: JSON.stringify({
          duration_days: durationDays,
          device_limit: deviceLimit,
          count,
        }),
      });
      setLicenses((current) => [...created, ...current]);
      await loadDashboard();
      setMessage(`已生成 ${created.length} 张卡密`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "生成失败");
    } finally {
      setLoading(false);
    }
  }

  async function updateLicenseStatus(id: number, status: string) {
    setMessage("");
    try {
      const updated = await apiRequest<License>(`/admin/licenses/${id}`, token, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setLicenses((current) =>
        current.map((license) => (license.id === id ? updated : license)),
      );
      await loadDashboard();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "修改失败");
    }
  }

  async function deleteLicense(id: number) {
    setMessage("");
    try {
      await apiRequest(`/admin/licenses/${id}`, token, { method: "DELETE" });
      setLicenses((current) => current.filter((license) => license.id !== id));
      await loadDashboard();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    }
  }

  async function copyLicense(key: string) {
    await navigator.clipboard.writeText(key);
    setMessage("卡密已复制");
  }

  async function searchUsers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      await loadUsers(token, 1, userKeyword);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "搜索失败");
    } finally {
      setLoading(false);
    }
  }

  async function changeUserPage(page: number) {
    setLoading(true);
    setMessage("");
    try {
      await loadUsers(token, page, userKeyword);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function searchAiUsage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      await loadAiUsage(token, 1, aiLicenseKey, aiUserId);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "搜索失败");
    } finally {
      setLoading(false);
    }
  }

  async function changeAiPage(page: number) {
    setLoading(true);
    setMessage("");
    try {
      await loadAiUsage(token, page, aiLicenseKey, aiUserId);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  function editAiConfig(config: AIConfig) {
    setAiConfigForm({
      id: config.id,
      provider: config.provider,
      model_name: config.model_name,
      api_key: config.api_key,
      base_url: config.base_url ?? "",
      enabled: config.enabled,
      is_default: config.is_default,
      description: config.description ?? "",
    });
  }

  function resetAiConfigForm() {
    setAiConfigForm({ ...EMPTY_AI_CONFIG_FORM });
  }

  async function saveAiConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      const saved = await apiRequest<AIConfig>("/admin/ai-config", token, {
        method: "POST",
        body: JSON.stringify(aiConfigForm),
      });
      await loadAiConfigs();
      setAiConfigForm({ ...EMPTY_AI_CONFIG_FORM });
      setMessage(`AI config saved: ${saved.provider} / ${saved.model_name}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setLoading(false);
    }
  }

  async function setDefaultAiConfig(config: AIConfig) {
    setLoading(true);
    setMessage("");
    try {
      await apiRequest<AIConfig>("/admin/ai-config", token, {
        method: "POST",
        body: JSON.stringify({
          id: config.id,
          provider: config.provider,
          model_name: config.model_name,
          api_key: config.api_key,
          base_url: config.base_url ?? "",
          enabled: true,
          is_default: true,
          description: config.description ?? "",
        }),
      });
      await loadAiConfigs();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "设置默认失败");
    } finally {
      setLoading(false);
    }
  }

  async function deleteAiConfig(id: number) {
    setLoading(true);
    setMessage("");
    try {
      await apiRequest(`/admin/ai-config/${id}`, token, { method: "DELETE" });
      await loadAiConfigs();
      if (aiConfigForm.id === id) {
        resetAiConfigForm();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除失败");
    } finally {
      setLoading(false);
    }
  }

  async function testAiConfig(id: number) {
    setLoading(true);
    setMessage("");
    try {
      const result = await apiRequest<AIConfigTestResult>(
        `/admin/ai-config/${id}/test`,
        token,
        { method: "POST" },
      );
      setAiConfigTest((current) => ({
        ...current,
        [id]: `${result.status}: ${result.message} (${result.model_used}, ${formatCost(
          result.estimated_cost_usd,
        )})`,
      }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "测试失败");
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <main className="login-screen">
        <section className="login-panel">
          <div className="brand-row">
            <KeyRound size={34} />
            <div>
              <h1>JCC Admin</h1>
              <p>后台管理系统</p>
            </div>
          </div>
          <form onSubmit={handleLogin}>
            <label>
              管理员账号
              <input
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </label>
            <label>
              管理员密码
              <input
                autoComplete="current-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            <button className="primary" disabled={loading} type="submit">
              登录
            </button>
          </form>
          {message && <p className="notice error">{message}</p>}
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <div className="brand-row compact">
            <KeyRound size={28} />
            <div>
              <strong>JCC Admin</strong>
              <span>Management Console</span>
            </div>
          </div>
          <nav>
            <NavButton
              active={view === "dashboard"}
              icon={<LayoutDashboard size={18} />}
              label="Dashboard"
              onClick={() => setView("dashboard")}
            />
            <NavButton
              active={view === "licenses"}
              icon={<KeyRound size={18} />}
              label="卡密管理"
              onClick={() => setView("licenses")}
            />
            <NavButton
              active={view === "users"}
              icon={<Users size={18} />}
              label="用户管理"
              onClick={() => setView("users")}
            />
            <NavButton
              active={view === "ai-usage"}
              icon={<Activity size={18} />}
              label="AI日志"
              onClick={() => setView("ai-usage")}
            />
            <NavButton
              active={view === "ai-config"}
              icon={<Settings size={18} />}
              label="AI设置"
              onClick={() => setView("ai-config")}
            />
          </nav>
        </div>
        <button className="ghost" onClick={logout} type="button">
          <LogOut size={18} />
          退出
        </button>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <h1>{getViewTitle(view)}</h1>
            <p>JCC 授权、用户与 AI 成本概览</p>
          </div>
          <button
            className="icon-button"
            disabled={loading}
            onClick={() => void refreshCurrent()}
            type="button"
          >
            <RefreshCw size={18} />
            刷新
          </button>
        </header>

        {message && <p className="notice">{message}</p>}

        {view === "dashboard" && (
          <section className="metrics-grid">
            <Metric title="用户总数" value={dashboard?.total_users ?? 0} />
            <Metric title="卡密总数" value={dashboard?.total_licenses ?? 0} />
            <Metric title="有效卡密" value={dashboard?.active_licenses ?? 0} />
            <Metric title="过期卡密" value={dashboard?.expired_licenses ?? 0} />
            <Metric title="AI调用总数" value={dashboard?.total_ai_calls ?? 0} />
            <Metric
              title="AI总成本"
              value={formatCost(dashboard?.total_ai_cost_usd)}
            />
            <Metric title="今日AI调用" value={dashboard?.today_ai_calls ?? 0} />
            <Metric
              title="今日AI成本"
              value={formatCost(dashboard?.today_ai_cost_usd)}
            />
          </section>
        )}

        {view === "licenses" && (
          <>
            <section className="panel">
              <form className="create-form" onSubmit={createLicenses}>
                <label>
                  有效天数
                  <input
                    min={1}
                    type="number"
                    value={durationDays}
                    onChange={(event) => setDurationDays(Number(event.target.value))}
                  />
                </label>
                <label>
                  设备限制
                  <input
                    min={1}
                    type="number"
                    value={deviceLimit}
                    onChange={(event) => setDeviceLimit(Number(event.target.value))}
                  />
                </label>
                <label>
                  生成数量
                  <input
                    max={500}
                    min={1}
                    type="number"
                    value={count}
                    onChange={(event) => setCount(Number(event.target.value))}
                  />
                </label>
                <button className="primary with-icon" disabled={loading} type="submit">
                  <Plus size={18} />
                  批量生成
                </button>
              </form>
            </section>

            <section className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>卡密</th>
                    <th>状态</th>
                    <th>天数</th>
                    <th>设备</th>
                    <th>激活用户</th>
                    <th>过期时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedLicenses.map((license) => (
                    <tr key={license.id}>
                      <td className="key-cell">{license.license_key}</td>
                      <td>
                        <select
                          value={license.status}
                          onChange={(event) =>
                            void updateLicenseStatus(license.id, event.target.value)
                          }
                        >
                          <option value="unused">unused</option>
                          <option value="active">active</option>
                          <option value="expired">expired</option>
                          <option value="disabled">disabled</option>
                        </select>
                      </td>
                      <td>{license.duration_days}</td>
                      <td>{license.device_limit}</td>
                      <td>{license.activated_by ?? "-"}</td>
                      <td>{formatDate(license.expires_at)}</td>
                      <td>
                        <div className="row-actions">
                          <button
                            className="square-button"
                            onClick={() => void copyLicense(license.license_key)}
                            title="复制卡密"
                            type="button"
                          >
                            <Clipboard size={16} />
                          </button>
                          <button
                            className="square-button danger"
                            onClick={() => void deleteLicense(license.id)}
                            title="删除卡密"
                            type="button"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {sortedLicenses.length === 0 && <div className="empty">暂无卡密</div>}
            </section>
          </>
        )}

        {view === "users" && (
          <>
            <section className="panel">
              <form className="search-form" onSubmit={searchUsers}>
                <label>
                  用户名或邮箱
                  <input
                    placeholder="输入关键词搜索"
                    value={userKeyword}
                    onChange={(event) => setUserKeyword(event.target.value)}
                  />
                </label>
                <button className="primary with-icon" disabled={loading} type="submit">
                  <Search size={18} />
                  搜索
                </button>
              </form>
            </section>

            <section className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>用户名</th>
                    <th>邮箱</th>
                    <th>注册时间</th>
                    <th>授权状态</th>
                    <th>授权过期时间</th>
                  </tr>
                </thead>
                <tbody>
                  {users.items.map((user) => (
                    <tr key={user.id}>
                      <td>{user.id}</td>
                      <td>{user.username}</td>
                      <td>{user.email}</td>
                      <td>{formatDate(user.created_at)}</td>
                      <td>
                        <span className={`status-pill ${user.license_status}`}>
                          {user.license_status}
                        </span>
                      </td>
                      <td>{formatDate(user.license_expires_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {users.items.length === 0 && <div className="empty">暂无用户</div>}
            </section>

            <Pagination
              loading={loading}
              page={users.page}
              total={users.total}
              totalPages={totalUserPages}
              onPageChange={changeUserPage}
            />
          </>
        )}

        {view === "ai-usage" && (
          <>
            <section className="summary-strip">
              <Metric title="筛选调用数" value={aiUsage.total_calls} />
              <Metric title="筛选总成本" value={formatCost(aiUsage.total_cost_usd)} />
            </section>

            <section className="panel">
              <form className="ai-search-form" onSubmit={searchAiUsage}>
                <label>
                  License Key
                  <input
                    placeholder="JCC-XXXX-XXXX-XXXX"
                    value={aiLicenseKey}
                    onChange={(event) => setAiLicenseKey(event.target.value)}
                  />
                </label>
                <label>
                  User ID
                  <input
                    min={1}
                    placeholder="用户 ID"
                    type="number"
                    value={aiUserId}
                    onChange={(event) => setAiUserId(event.target.value)}
                  />
                </label>
                <button className="primary with-icon" disabled={loading} type="submit">
                  <Search size={18} />
                  搜索
                </button>
              </form>
            </section>

            <section className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>User ID</th>
                    <th>License Key</th>
                    <th>Model</th>
                    <th>Cost USD</th>
                    <th>AI Status</th>
                    <th>Created At</th>
                  </tr>
                </thead>
                <tbody>
                  {aiUsage.items.map((log) => (
                    <tr key={log.id}>
                      <td>{log.user_id ?? "-"}</td>
                      <td className="key-cell">{log.license_key ?? "-"}</td>
                      <td>{log.model_used}</td>
                      <td>{formatCost(log.estimated_cost_usd)}</td>
                      <td>
                        <span className={`status-pill ${log.ai_status}`}>
                          {log.ai_status}
                        </span>
                      </td>
                      <td>{formatDate(log.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {aiUsage.items.length === 0 && <div className="empty">暂无AI日志</div>}
            </section>

            <Pagination
              loading={loading}
              page={aiUsage.page}
              total={aiUsage.total}
              totalPages={totalAiPages}
              onPageChange={changeAiPage}
            />
          </>
        )}

        {view === "ai-config" && (
          <>
            <section className="panel">
              <div className="backend-line">
                <span>Backend</span>
                <input
                  value={apiBase}
                  onChange={(event) => setApiBase(event.target.value)}
                />
                <button className="icon-button" onClick={saveApiBase} type="button">
                  Save Backend
                </button>
              </div>
              <form className="config-form" onSubmit={saveAiConfig}>
                <label>
                  Provider
                  <select
                    value={aiConfigForm.provider}
                    onChange={(event) =>
                      setAiConfigForm((current) => ({
                        ...current,
                        provider: event.target.value,
                      }))
                    }
                  >
                    <option value="deepseek">deepseek</option>
                    <option value="qwen">qwen</option>
                    <option value="openai">openai</option>
                    <option value="apirouter">apirouter</option>
                    <option value="aipower">aipower</option>
                  </select>
                </label>
                <label>
                  Model
                  <input
                    value={aiConfigForm.model_name}
                    onChange={(event) =>
                      setAiConfigForm((current) => ({
                        ...current,
                        model_name: event.target.value,
                      }))
                    }
                    required
                  />
                </label>
                <label>
                  API Key
                  <input
                    value={aiConfigForm.api_key}
                    onChange={(event) =>
                      setAiConfigForm((current) => ({
                        ...current,
                        api_key: event.target.value,
                      }))
                    }
                    placeholder="sk-..."
                  />
                </label>
                <label>
                  Base URL
                  <input
                    value={aiConfigForm.base_url}
                    onChange={(event) =>
                      setAiConfigForm((current) => ({
                        ...current,
                        base_url: event.target.value,
                      }))
                    }
                    placeholder="https://.../chat/completions"
                  />
                </label>
                <label>
                  Description
                  <input
                    value={aiConfigForm.description}
                    onChange={(event) =>
                      setAiConfigForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))
                    }
                  />
                </label>
                <label className="check-row">
                  <input
                    checked={aiConfigForm.enabled}
                    type="checkbox"
                    onChange={(event) =>
                      setAiConfigForm((current) => ({
                        ...current,
                        enabled: event.target.checked,
                      }))
                    }
                  />
                  Enabled
                </label>
                <label className="check-row">
                  <input
                    checked={aiConfigForm.is_default}
                    type="checkbox"
                    onChange={(event) =>
                      setAiConfigForm((current) => ({
                        ...current,
                        is_default: event.target.checked,
                      }))
                    }
                  />
                  Default
                </label>
                <div className="form-actions">
                  <button className="primary with-icon" disabled={loading} type="submit">
                    <Save size={18} />
                    {aiConfigForm.id ? "Save" : "Create"}
                  </button>
                  <button
                    className="icon-button"
                    onClick={resetAiConfigForm}
                    type="button"
                  >
                    <X size={18} />
                    Reset
                  </button>
                </div>
              </form>
            </section>

            <section className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Model</th>
                    <th>API Key</th>
                    <th>Base URL</th>
                    <th>Enabled</th>
                    <th>Default</th>
                    <th>Description</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {aiConfigs.map((config) => (
                    <tr key={config.id}>
                      <td>{config.provider}</td>
                      <td>{config.model_name}</td>
                      <td>{config.api_key || "-"}</td>
                      <td className="url-cell">{config.base_url || "-"}</td>
                      <td>{config.enabled ? "yes" : "no"}</td>
                      <td>{config.is_default ? "yes" : "no"}</td>
                      <td>{config.description || "-"}</td>
                      <td>
                        <div className="row-actions wide">
                          <button
                            className="icon-button"
                            onClick={() => editAiConfig(config)}
                            type="button"
                          >
                            Edit
                          </button>
                          <button
                            className="icon-button"
                            disabled={loading}
                            onClick={() => void setDefaultAiConfig(config)}
                            type="button"
                          >
                            Default
                          </button>
                          <button
                            className="icon-button"
                            disabled={loading}
                            onClick={() => void testAiConfig(config.id)}
                            type="button"
                          >
                            Test
                          </button>
                          <button
                            className="square-button danger"
                            disabled={loading}
                            onClick={() => void deleteAiConfig(config.id)}
                            title="Delete"
                            type="button"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                        {aiConfigTest[config.id] && (
                          <p className="test-result">{aiConfigTest[config.id]}</p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {aiConfigs.length === 0 && <div className="empty">No AI configs</div>}
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function getViewTitle(view: View) {
  if (view === "dashboard") {
    return "Dashboard";
  }
  if (view === "licenses") {
    return "卡密管理";
  }
  if (view === "ai-config") {
    return "AI设置";
  }
  if (view === "users") {
    return "用户管理";
  }
  return "AI日志";
}

function NavButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={active ? "nav-button active" : "nav-button"}
      onClick={onClick}
      type="button"
    >
      {icon}
      {label}
    </button>
  );
}

function Metric({ title, value }: { title: string; value: number | string }) {
  return (
    <article className="metric">
      <span>{title}</span>
      <strong>{value}</strong>
    </article>
  );
}

function Pagination({
  loading,
  page,
  total,
  totalPages,
  onPageChange,
}: {
  loading: boolean;
  page: number;
  total: number;
  totalPages: number;
  onPageChange: (page: number) => Promise<void>;
}) {
  return (
    <section className="pagination">
      <span>
        共 {total} 条，第 {page} / {totalPages} 页
      </span>
      <div className="page-actions">
        <button
          className="icon-button"
          disabled={loading || page <= 1}
          onClick={() => void onPageChange(page - 1)}
          type="button"
        >
          上一页
        </button>
        <button
          className="icon-button"
          disabled={loading || page >= totalPages}
          onClick={() => void onPageChange(page + 1)}
          type="button"
        >
          下一页
        </button>
      </div>
    </section>
  );
}

export default App;
