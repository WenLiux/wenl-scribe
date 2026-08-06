"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { BRAND_COPY } from "./brand";
import { Icon } from "./components/Icon";
import { FloatingBilibiliPlayer, type FloatingBilibiliPlayerHandle } from "./components/video/FloatingBilibiliPlayer";
import { locateEvidenceTimestamp } from "./components/video/evidence";
import { useVideoSeek } from "./components/video/useVideoSeek";
import type { BilibiliVideoInfo } from "./components/video/types";

type TranscriptSegment = { start: number | null; end: number | null; text: string; source?: string };
type Claim = { claim: string; evidence: string; kind: string; start: number | null; end: number | null; context?: string; verified?: boolean };
type ErrorInfo = { code: string; message: string; stage?: string; retryable?: boolean };
type Result = {
  job_id: string; title: string; author: string; duration: number; cover?: string;
  source_url: string; bvid?: string; page?: number; video?: BilibiliVideoInfo;
  method: string; summary: string; key_points: string[]; transcript: string;
  outline?: { title: string; content: string }[]; evidence?: string[]; summary_type?: "extractive" | "generative";
  segments?: TranscriptSegment[]; claims?: Claim[]; summary_error?: ErrorInfo;
  summary_stats?: { total: number; completed: number; failed: number };
};
type Task = {
  job_id: string; status: "pending" | "processing" | "completed" | "partial" | "failed" | "cancelled";
  stage: string; progress: number; message: string; created_at: number; updated_at: number;
  model: string; language?: string; summary_mode: string; title?: string; author?: string; duration?: number;
  cover?: string; bvid?: string; page?: number; error?: string; error_info?: ErrorInfo; warning?: ErrorInfo; result?: Result;
  progress_detail?: Record<string, number>; available_results?: string[];
};
type Settings = {
  model: "small" | "medium" | "large-v3-turbo";
  language: "auto" | "zh" | "en";
  summaryMode: "auto" | "local" | "cloud";
  autoExpandPlayer: boolean;
};
type TranscriptionModel = Settings["model"];
type ApiConfig = {
  provider: "openai" | "gemini" | "sensenova" | "compatible";
  protocol: "openai_responses" | "openai_chat" | "gemini_openai" | "sensenova_native" | "sensenova_compatible" | "ollama";
  base_url: string;
  model: string;
  has_api_key: boolean;
  configured: boolean;
  managed_by_env?: boolean;
  managed_by_env_name?: string;
  key_hint?: string;
  credential_storage?: "environment" | "dpapi" | "legacy_plaintext" | "none";
  capabilities?: { models?: boolean; structured_output?: string; stream?: boolean; usage?: boolean };
};
type ApiModel = { id: string; name?: string; type?: string | null; owned_by?: string | null; allow_chat?: boolean | null };
type ApiModelSelection = {
  mode: "auto" | "manual";
  requested_model?: string;
  selected_model?: string;
  failures?: { model: string; reason: string }[];
};

const API_PROTOCOL_OPTIONS: Record<ApiConfig["provider"], ReadonlyArray<{ value: ApiConfig["protocol"]; label: string }>> = {
  openai: [
    { value: "openai_responses", label: "OpenAI Responses API" },
    { value: "openai_chat", label: "OpenAI Chat Completions" },
  ],
  gemini: [{ value: "gemini_openai", label: "Gemini OpenAI 兼容接口" }],
  sensenova: [
    { value: "sensenova_compatible", label: "SenseNova OpenAI 兼容接口" },
    { value: "sensenova_native", label: "SenseNova 原生接口" },
  ],
  compatible: [
    { value: "openai_chat", label: "OpenAI Chat Completions 兼容" },
    { value: "ollama", label: "Ollama 接口" },
  ],
};

const API_PROVIDER_OPTIONS: ReadonlyArray<{ value: ApiConfig["provider"]; label: string; description: string }> = [
  { value: "sensenova", label: "商汤 SenseNova", description: "只需 API Key，自动读取模型并验证连接" },
  { value: "gemini", label: "Google Gemini", description: "使用 Gemini API Key 和默认兼容接口" },
  { value: "openai", label: "OpenAI", description: "使用 OpenAI API Key 和默认模型" },
  { value: "compatible", label: "其他 OpenAI 兼容服务", description: "用于自定义网关或本地 Ollama" },
];

const API_PROVIDER_PRESETS: Record<ApiConfig["provider"], { protocol: ApiConfig["protocol"]; base_url: string; model: string }> = {
  sensenova: { protocol: "sensenova_compatible", base_url: "https://api.sensenova.cn/compatible-mode/v2", model: "SenseChat-5" },
  gemini: { protocol: "gemini_openai", base_url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-3.5-flash" },
  openai: { protocol: "openai_responses", base_url: "https://api.openai.com/v1", model: "gpt-5-mini" },
  compatible: { protocol: "openai_chat", base_url: "http://127.0.0.1:11434/v1", model: "qwen3:8b" },
};

const API = typeof window !== "undefined" && window.location.port === "3001"
  ? "http://127.0.0.1:8765"
  : "";
const EXAMPLE = "【分享示例】 https://b23.tv/UXgYm0R";
const STAGE_ORDER = ["parsing", "checking_subtitles", "downloading", "loading_model", "transcribing", "cleaning", "summarizing", "validating", "completed"];
const STAGE_LABELS: Record<string, string> = {
  parsing: "解析视频", checking_subtitles: "检查字幕", downloading: "下载音频", loading_model: "加载模型",
  transcribing: "本地转录", cleaning: "整理文字", summarizing: "生成总结", validating: "校验证据", completed: "处理完成",
};
const TERMINAL = new Set(["completed", "partial", "failed", "cancelled"]);
const DEFAULT_SETTINGS: Settings = { model: "small", language: "auto", summaryMode: "auto", autoExpandPlayer: true };
const FIRST_USE_KEY = "wenl-first-use-v1";
const SETTINGS_KEY = "wenl-settings-v3";
const TRANSCRIPTION_MODELS: ReadonlyArray<{
  value: TranscriptionModel;
  title: string;
  description: string;
  badge: string;
}> = [
  { value: "small", title: "Small", description: "下载更快、资源占用较低，适合先体验和普通中文视频。", badge: "默认" },
  { value: "medium", title: "Medium", description: "准确率与速度更均衡，适合访谈和较复杂内容。", badge: "均衡" },
  { value: "large-v3-turbo", title: "Large v3 Turbo", description: "中英文和专业词更稳，但下载、内存与处理时间更多。", badge: "准确优先" },
];
const STATUS_LABELS: Record<string, string> = { pending: "等待中", processing: "处理中", completed: "已完成", partial: "部分完成", failed: "失败", cancelled: "已取消" };
const [BRAND_SLOGAN_LEAD, BRAND_SLOGAN_END] = BRAND_COPY.slogan.split("，");

function formatTime(seconds = 0) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}
function formatDate(ms: number) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(ms);
}
function formatTimestamp(seconds: number | null | undefined) {
  if (seconds == null) return "--:--";
  const value = Math.max(0, Math.floor(seconds));
  const h = Math.floor(value / 3600); const m = Math.floor((value % 3600) / 60); const s = value % 60;
  return h ? `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}` : `${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
}
function progressDetail(task: Task) {
  const detail = task.progress_detail || {};
  if (typeof detail.processed_seconds === "number" && typeof detail.total_seconds === "number") {
    return `音频 ${formatTime(detail.processed_seconds)} / ${formatTime(detail.total_seconds)}`;
  }
  if (typeof detail.bytes_downloaded === "number" && typeof detail.bytes_total === "number") {
    return `下载 ${(detail.bytes_downloaded / 1048576).toFixed(1)} / ${(detail.bytes_total / 1048576).toFixed(1)} MB`;
  }
  if (typeof detail.summary_chunk === "number" && typeof detail.summary_chunks === "number") {
    return `总结分块 ${detail.summary_chunk} / ${detail.summary_chunks}`;
  }
  if (typeof detail.validated_chunks === "number") {
    return `已校验 ${detail.validated_chunks} 个分块${detail.failed_chunks ? `，${detail.failed_chunks} 个未完成` : ""}`;
  }
  if (typeof detail.segments === "number") return `已保存 ${detail.segments} 个时间段`;
  return "阶段进度按实际处理量更新";
}

export default function Home() {
  const [view, setView] = useState<"home" | "history" | "settings">("home");
  const [url, setUrl] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [history, setHistory] = useState<Task[]>([]);
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyFilter, setHistoryFilter] = useState("all");
  const [error, setError] = useState("");
  const [active, setActive] = useState<"summary" | "transcript">("summary");
  const [copied, setCopied] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [cloudAvailable, setCloudAvailable] = useState(false);
  const [apiConfig, setApiConfig] = useState<ApiConfig>({ provider: "openai", protocol: "openai_responses", base_url: "https://api.openai.com/v1", model: "gpt-5-mini", has_api_key: false, configured: false });
  const [apiKey, setApiKey] = useState("");
  const [apiModels, setApiModels] = useState<ApiModel[]>([]);
  const [apiAdvancedOpen, setApiAdvancedOpen] = useState(false);
  const [apiMessage, setApiMessage] = useState("");
  const [apiBusy, setApiBusy] = useState(false);
  const [resummarizing, setResummarizing] = useState(false);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [preflightOpen, setPreflightOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState<TranscriptionModel>("small");
  const [firstUseConfirmed, setFirstUseConfirmed] = useState(false);
  const [usageChecks, setUsageChecks] = useState({ rights: false, accuracy: false, resources: false });
  const [apiDecision, setApiDecision] = useState<"configured" | "later" | null>(null);
  const pollRef = useRef<number | null>(null);
  const floatingPlayerRef = useRef<FloatingBilibiliPlayerHandle | null>(null);
  const { request: videoSeek, locate: locateVideo, reset: resetVideoSeek } = useVideoSeek(result?.duration);

  const loadHistory = useCallback(async () => {
    try {
      const response = await fetch(`${API}/api/history`);
      if (response.ok) setHistory((await response.json()).items || []);
    } catch { /* backend may still be starting */ }
  }, []);

  const loadApiConfig = useCallback(async () => {
    try {
      const response = await fetch(`${API}/api/config`);
      if (!response.ok) return;
      const config: ApiConfig = await response.json();
      setApiConfig(config); setCloudAvailable(config.configured); setProviderDirty(false); setApiModels([]);
    } catch { /* backend may still be starting */ }
  }, []);

  useEffect(() => {
    const loadTimer = window.setTimeout(() => {
      const saved = localStorage.getItem(SETTINGS_KEY);
      if (saved) {
        const next = { ...DEFAULT_SETTINGS, ...JSON.parse(saved) };
        setSettings(next);
        setSelectedModel(next.model);
      } else {
        const legacy = localStorage.getItem("wenl-settings-v2");
        const migrated = legacy ? { ...DEFAULT_SETTINGS, ...JSON.parse(legacy), model: "small" } : DEFAULT_SETTINGS;
        setSettings(migrated);
        setSelectedModel(migrated.model);
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(migrated));
      }
      setFirstUseConfirmed(localStorage.getItem(FIRST_USE_KEY) === "confirmed");
      loadHistory(); loadApiConfig();
    }, 0);
    return () => { window.clearTimeout(loadTimer); if (pollRef.current) window.clearTimeout(pollRef.current); };
  }, [loadHistory, loadApiConfig]);

  useEffect(() => {
    if (!task || TERMINAL.has(task.status)) return;
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - task.created_at) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [task]);

  useEffect(() => resetVideoSeek(), [result?.job_id, resetVideoSeek]);

  function handleTimestampClick(seconds: number | null | undefined) {
    if (seconds == null) return;
    floatingPlayerRef.current?.showForTimestamp();
    locateVideo(seconds);
  }

  function claimTimestamp(item: Claim) {
    return locateEvidenceTimestamp(item.evidence, result?.segments, item.start);
  }

  async function pollJob(jobId: string) {
    try {
      const response = await fetch(`${API}/api/jobs/${jobId}`);
      const next: Task = await response.json();
      if (!response.ok) throw new Error(next.error || "无法读取任务状态");
      setTask(next);
      if ((next.status === "completed" || next.status === "partial") && next.result) {
        setResult(next.result); setActive("summary"); loadHistory(); return;
      }
      if (next.status === "failed" || next.status === "cancelled") {
        if (next.result) setResult(next.result);
        setError(next.error || next.message || "处理未完成"); loadHistory(); return;
      }
      pollRef.current = window.setTimeout(() => pollJob(jobId), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "本地服务暂时不可用");
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setSelectedModel(settings.model);
    setUsageChecks({ rights: false, accuracy: false, resources: false });
    setApiDecision(cloudAvailable ? "configured" : null);
    setPreflightOpen(true);
  }

  async function startTranscription(model: TranscriptionModel) {
    if (pollRef.current) window.clearTimeout(pollRef.current);
    setError(""); setResult(null); setElapsed(0);
    try {
      const response = await fetch(`${API}/api/jobs`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), model, language: settings.language, summary_mode: settings.summaryMode }),
      });
      const created = await response.json();
      if (!response.ok) throw new Error(created.error || "无法创建转录任务");
      setTask(created); pollJob(created.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法连接留文本地服务");
    }
  }

  async function openTask(jobId: string) {
    const response = await fetch(`${API}/api/jobs/${jobId}`);
    const selected: Task = await response.json();
    setView("home"); setTask(selected); setResult(selected.result || null); setError(selected.error || "");
    if (!TERMINAL.has(selected.status)) pollJob(jobId);
  }

  async function deleteTask(jobId: string) {
    await fetch(`${API}/api/jobs/${jobId}`, { method: "DELETE" });
    setHistory(items => items.filter(item => item.job_id !== jobId));
  }

  function saveSettings(next: Settings) {
    setSettings(next); localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
  }

  function confirmFirstUse() {
    localStorage.setItem(FIRST_USE_KEY, "confirmed");
    setFirstUseConfirmed(true);
  }

  async function confirmTranscription() {
    if (!firstUseConfirmed) {
      if (!usageChecks.rights || !usageChecks.accuracy || !usageChecks.resources || !apiDecision) return;
      confirmFirstUse();
    }
    saveSettings({ ...settings, model: selectedModel });
    setPreflightOpen(false);
    await startTranscription(selectedModel);
  }

  function openApiSettingsFromPreflight() {
    if (!usageChecks.rights || !usageChecks.accuracy || !usageChecks.resources) return;
    confirmFirstUse();
    setPreflightOpen(false);
    setView("settings");
    setApiMessage("可在这里配置总结 API；保存后回到首页开始转录。");
  }

  async function copyCurrent() {
    if (!result) return;
    const text = active === "transcript" ? result.transcript : `${result.summary}\n\n${result.key_points.map((p, i) => `${i + 1}. ${p}`).join("\n")}`;
    await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500);
  }

  function apiConfigPayload() {
    return {
      provider: apiConfig.provider,
      protocol: apiConfig.protocol,
      base_url: apiConfig.base_url,
      model: apiConfig.model,
      ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
    };
  }

  async function persistApiConfig(): Promise<ApiConfig> {
    const response = await fetch(`${API}/api/config`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(apiConfigPayload()),
    });
    const data: ApiConfig & { error?: string } = await response.json();
    if (!response.ok) throw new Error(data.error || "保存配置失败");
    setApiConfig(data); setCloudAvailable(data.configured); setApiKey("");
    return data;
  }

  async function saveApiConfig() {
    setApiBusy(true); setApiMessage("");
    try {
      await persistApiConfig();
      setApiMessage("配置已保存；如需自动选择模型，请点击读取可用模型");
    } catch (err) { setApiMessage(err instanceof Error ? err.message : "保存失败"); }
    finally { setApiBusy(false); }
  }

  async function discoverApiModels(selectionMode: "auto" | "manual" = "auto") {
    setApiBusy(true); setApiMessage("正在保存配置并读取可用模型…");
    try {
      const saved = await persistApiConfig();
      if (!saved.capabilities?.models) {
        setApiMessage("该服务没有标准模型列表接口，请在高级设置中填写模型 ID");
        return;
      }
      const response = await fetch(`${API}/api/config/models`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ selection_mode: selectionMode }) });
      const data: { models?: ApiModel[]; selected_model?: string; selection?: ApiModelSelection; config?: ApiConfig; error?: string } = await response.json();
      if (!response.ok) throw new Error(data.error || "读取模型失败；请在高级设置中填写模型 ID");
      const models = Array.isArray(data.models) ? data.models : [];
      const config = data.config;
      setApiModels(models);
      if (config) { setApiConfig(config); setCloudAvailable(config.configured); }
      const selected = data.selection?.selected_model || data.selected_model || config?.model || saved.model;
      const requested = data.selection?.requested_model || saved.model;
      if (selectionMode === "manual" && requested !== selected) {
        throw new Error(`当前选择的模型未被保留：${requested} → ${selected}`);
      }
      if (selectionMode === "auto" && requested !== selected) {
        const failed = data.selection?.failures?.find(item => item.model === requested);
        setApiMessage(`已自动选择 ${selected}；${requested} 验证失败${failed?.reason ? `：${failed.reason}` : ""}。已读取 ${models.length} 个可用模型`);
      } else if (apiConfig.provider === "sensenova") {
        setApiMessage(`连接成功：${selected}；已读取 ${models.length} 个可用模型`);
      } else {
        setApiMessage(`已读取 ${models.length} 个可用模型，自动选择 ${selected}`);
      }
    } catch (err) { setApiMessage(err instanceof Error ? err.message : "读取模型失败"); }
    finally { setApiBusy(false); }
  }

  async function connectSenseNova() {
    await discoverApiModels(apiModels.length > 0 ? "manual" : "auto");
  }

  async function testApiConfig() {
    setApiBusy(true); setApiMessage("正在测试连接…");
    try {
      const response = await fetch(`${API}/api/config/test`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "连接失败");
      setApiMessage(data.message || "连接成功");
    } catch (err) { setApiMessage(err instanceof Error ? err.message : "连接失败"); }
    finally { setApiBusy(false); }
  }

  async function clearApiKey() {
    if (apiConfig.managed_by_env) { setApiMessage(`当前密钥由 ${apiConfig.managed_by_env_name || "环境变量"} 提供，请在启动环境中删除。`); return; }
    setApiBusy(true); setApiMessage("");
    try {
      const response = await fetch(`${API}/api/config`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: apiConfig.provider, protocol: apiConfig.protocol, base_url: apiConfig.base_url, model: apiConfig.model, clear_api_key: true }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "清除失败");
      setApiConfig(data); setCloudAvailable(data.configured); setApiKey(""); setApiModels([]); setApiMessage("密钥已从本机配置中清除");
    } catch (err) { setApiMessage(err instanceof Error ? err.message : "清除失败"); }
    finally { setApiBusy(false); }
  }

  async function resummarize(mode: "cloud" | "local" = "cloud") {
    if (!result) return;
    if (mode === "cloud" && !cloudAvailable) { setView("settings"); setApiMessage("请先配置并测试总结 API，然后返回历史任务重新总结。"); return; }
    setResummarizing(true); setError("");
    try {
      const response = await fetch(`${API}/api/jobs/${result.job_id}/resummarize`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }),
      });
      const restarted: Task = await response.json();
      if (!response.ok) throw new Error((restarted as unknown as {error?: string}).error || "重新总结失败");
      setResult(null); setTask(restarted); pollJob(restarted.job_id);
    } catch (err) { setError(err instanceof Error ? err.message : "重新总结失败"); }
    finally { setResummarizing(false); }
  }

  async function cancelTask() {
    if (!task) return;
    const response = await fetch(`${API}/api/jobs/${task.job_id}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const next = await response.json();
    if (response.ok) setTask(next); else setError(next.error || "取消失败");
  }

  async function retryTask(fromStage: "auto" | "summary" | "transcription" = "auto") {
    if (!task) return;
    setError(""); setResult(null);
    const response = await fetch(`${API}/api/jobs/${task.job_id}/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ from_stage: fromStage }) });
    const next = await response.json();
    if (!response.ok) { setError(next.error || "重试失败"); return; }
    setTask(next); pollJob(next.job_id);
  }

  function selectApiProvider(provider: ApiConfig["provider"]) {
    const preset = API_PROVIDER_PRESETS[provider];
    setApiConfig({ ...apiConfig, provider, ...preset, configured: false, has_api_key: false, key_hint: "" });
    setApiKey(""); setApiModels([]); setApiAdvancedOpen(false);
    setApiMessage(provider === "sensenova" ? "只需输入 API Key，点击“连接并自动选择模型”。" : `${API_PROVIDER_OPTIONS.find(item => item.value === provider)?.label || "服务"} 已切换，请输入 Key 并保存配置。`);
  }

  function selectApiProtocol(protocol: ApiConfig["protocol"]) {
    setApiConfig({ ...apiConfig, protocol, configured: false });
    setApiModels([]);
    setApiMessage("高级接口协议已切换；如果服务商没有标准模型列表，请在下方填写模型 ID。");
  }

  const processing = task && !result && !TERMINAL.has(task.status);
  const downloadUrl = result ? `${API}/api/download/${active}?job_id=${encodeURIComponent(result.job_id)}` : "#";
  const visibleHistory = history.filter(item => {
    const matchesStatus = historyFilter === "all" || item.status === historyFilter;
    const haystack = `${item.title || ""} ${item.author || ""} ${item.bvid || ""} ${(item.result as Result | undefined)?.source_url || ""}`.toLowerCase();
    return matchesStatus && haystack.includes(historyQuery.trim().toLowerCase());
  });
  const resultClaims: Claim[] = result?.claims?.length ? result.claims : (result?.key_points || []).map((point, index) => ({ claim: point, evidence: result?.evidence?.[index] || point, kind: result?.summary_type === "extractive" ? "原文摘录" : "作者观点", start: null, end: null }));
  const resultVideo: BilibiliVideoInfo | null = result?.video || (result?.bvid ? {
    platform: "bilibili",
    bvid: result.bvid,
    page: result.page || 1,
    sourceUrl: result.source_url,
    title: result.title,
    author: result.author,
    duration: result.duration,
  } : null);

  return <main>
    <header className="nav">
      <button className="brand brandButton" onClick={() => { setView("home"); setResult(null); setTask(null); setError(""); }}>
        <span className="brandGlyph"><img src="/wenl_logo2.svg" alt="" /></span>
        <span><strong>留文</strong><small>WENL SCRIBE</small></span>
      </button>
      <nav aria-label="主要导航">
        <button className={view === "home" ? "current" : ""} onClick={() => setView("home")}>首页</button>
        <button className={view === "history" ? "current" : ""} onClick={() => { setView("history"); loadHistory(); }}>历史</button>
        <button className={view === "settings" ? "current" : ""} onClick={() => setView("settings")}>设置</button>
      </nav>
      <span className="localBadge"><i /> 本地运行</span>
    </header>

    {view === "home" && <>
      {!task && !result && <section className="homeHero" id="top">
        <div className="eyebrow">留文 · WENL SCRIBE</div>
        <h1 className="homeSlogan" aria-label={BRAND_COPY.slogan}><span aria-hidden="true">{BRAND_SLOGAN_LEAD}，</span><em aria-hidden="true">{BRAND_SLOGAN_END}</em></h1>
        <p className="lead">粘贴链接，顷刻成文。</p>
        <form className="urlBox quietBox" onSubmit={submit}>
          <label htmlFor="video-url">B 站视频链接或完整分享文案</label>
          <div className="inputRow">
            <input id="video-url" value={url} onChange={e => setUrl(e.target.value)} placeholder="粘贴 B 站视频链接或完整分享文案" autoComplete="off" />
            <button disabled={!url.trim()} type="submit">开始转录<Icon name="arrow-right" size={18} /></button>
          </div>
          <div className="inputFoot"><button type="button" onClick={() => setUrl(EXAMPLE)}>填入示例</button><span>音频与转录默认在本机处理</span></div>
        </form>
        {error && <ErrorCard message={error} onRetry={() => setError("")} />}
      </section>}

      {processing && task && <section className="taskPage">
        <div className="taskTop"><button className="back" onClick={() => { setTask(null); setError(""); }}><Icon name="arrow-left" size={15} />返回首页</button><div className="taskTopActions"><span className="jobTag">任务 {task.job_id.slice(0, 8)}</span><button className="cancelButton" onClick={cancelTask}>取消任务</button></div></div>
        <div className="taskIntro">
          <div><span className="kicker">PROCESSING / 正在处理</span><h2>{task.title || "正在读取视频信息…"}</h2><p>{task.message}</p></div>
          <div className="progressNumber">{task.progress}<small>%</small></div>
        </div>
        <div className="progressTrack"><i style={{ width: `${task.progress}%` }} /></div>
        <div className="stageList">
          {STAGE_ORDER.map((stage, index) => {
            const currentIndex = STAGE_ORDER.indexOf(task.stage);
            const state = index < currentIndex ? "done" : index === currentIndex ? "active" : "pending";
            return <div className={`stage ${state}`} key={stage}><span>{state === "done" ? <Icon name="check" size={14} /> : String(index + 1).padStart(2, "0")}</span><p>{STAGE_LABELS[stage]}</p></div>;
          })}
        </div>
        <div className="taskMeta"><span>已耗时 {formatTime(elapsed)}</span><span>Whisper {task.model} · {task.language || "auto"} · CPU INT8</span><span>总结：{task.summary_mode === "local" ? "本地" : "API / 自动"}</span><span>{progressDetail(task)}</span><span>已完成阶段会立即保存</span></div>
      </section>}

      {(task?.status === "failed" || task?.status === "cancelled") && !result && <section className="taskPage">
        <div className="taskTop"><button className="back" onClick={() => { setTask(null); setError(""); }}><Icon name="arrow-left" size={15} />返回首页</button></div>
        <ErrorCard message={error || task.message} info={task.error_info} onRetry={() => retryTask("auto")} />
        <div className="recoveryActions"><button onClick={() => retryTask("auto")}>从可用阶段重试</button><button onClick={() => retryTask("transcription")}>重新转录</button><a href={`${API}/api/download/diagnostics?job_id=${task.job_id}`}>下载脱敏诊断</a></div>
      </section>}

      {result && <section className="workbench" aria-live="polite">
        <div className="taskTop"><button className="back" onClick={() => { setResult(null); setTask(null); setUrl(""); }}><Icon name="arrow-left" size={15} />新建转录</button><span className={`successPill ${task?.status === "partial" ? "partial" : ""}`}>{task?.status === "partial" ? "部分完成" : "处理完成"}</span></div>
        <div className="resultHead">
          <div className="coverFrame">{result.cover ? <img src={`${API}/api/cover?url=${encodeURIComponent(result.cover)}`} alt={`${result.title} 视频封面`} /> : <span>留文</span>}</div>
          <div className="resultTitle"><span className="kicker">RESULT / 内容结果</span><h2>{result.title}</h2><p>{result.author} · {formatTime(result.duration)} · {result.method}</p></div>
        </div>
        <div className="resultPlayer">
          <FloatingBilibiliPlayer
            key={result.job_id}
            ref={floatingPlayerRef}
            bvid={resultVideo?.bvid || ""}
            page={resultVideo?.page || 1}
            duration={resultVideo?.duration ?? result.duration}
            startTime={videoSeek.seconds}
            autoplay={videoSeek.autoplay}
            reloadKey={videoSeek.version}
            autoExpand={settings.autoExpandPlayer}
            side={active === "transcript" ? "right" : "left"}
          />
        </div>
        <div className="toolbar">
          <div className="tabs" role="tablist"><button className={active === "summary" ? "active" : ""} onClick={() => setActive("summary")}>内容总结</button><button className={active === "transcript" ? "active" : ""} onClick={() => setActive("transcript")}>完整转录</button></div>
          <div className="actions"><label className="autoFloatToggle" title="控制新打开任务首次下滑时是否默认展开悬浮播放器"><input type="checkbox" checked={settings.autoExpandPlayer} onChange={event => saveSettings({...settings, autoExpandPlayer:event.target.checked})} /><span>默认弹出视频</span></label><button className="copy" onClick={copyCurrent}>{copied ? "已复制" : "复制"}</button><a className="download" href={downloadUrl}>下载 Markdown</a><a className="copy" href={`${API}/api/download/diagnostics?job_id=${result.job_id}`}>诊断</a></div>
        </div>
        {active === "summary" ? <div className="summaryPage">
          <div className={`summaryNotice ${result.summary_type || "extractive"}`}>
            <div><strong>{result.summary_type === "generative" ? "AI 语义总结" : "本地原文摘录"}</strong>
            <span>{result.summary_type === "generative" ? "已校验原文引句；重要结论仍建议回看核对。" : "当前不是语义总结，只是算法挑选的原句，因此可能抓错重点。"}</span></div>
            {result.summary_type === "generative" ? <button disabled={resummarizing} onClick={() => resummarize("cloud")}>{resummarizing ? "正在重新总结…" : "重新生成"}</button> : <button disabled={resummarizing} onClick={() => resummarize("cloud")}>{resummarizing ? "正在总结…" : cloudAvailable ? "使用 API 重新总结" : "配置 API 后重新总结"}</button>}
          </div>
          {(task?.status === "partial" || result.summary_error) && <div className="partialNotice"><div><strong>逐字稿已安全保存</strong><span>{result.summary_error?.message || task?.warning?.message || "部分总结未完成，可单独重试。"}</span></div><button onClick={() => resummarize("cloud")}>只重新总结</button></div>}
          {error && <ErrorCard message={error} onRetry={() => setError("")} />}
          <article className="summaryLead"><span className="sectionNo">01</span><div><h3>{result.summary_type === "generative" ? "一句话结论" : "最重要的原文表达"}</h3><p>{result.summary}</p></div></article>
          <article className="summarySection"><div className="summarySectionHead"><span className="sectionNo">02</span><h3>{result.summary_type === "generative" ? "有原文支撑的核心观点" : "算法筛选的重点原句"}</h3></div><ol className="claimList">{resultClaims.map((item, index) => <li key={index}>
            <div className="claimHead"><span>{String(index + 1).padStart(2, "0")}</span><small>{item.kind}</small>{item.verified === false && <small className="unverified">旧数据未校验</small>}</div>
            <p className="claimText">{item.claim}</p>
            <blockquote>{item.evidence}</blockquote>
            <div className="claimActions">{claimTimestamp(item) != null ? <button type="button" onClick={() => handleTimestampClick(claimTimestamp(item))} aria-label={`定位播放 ${formatTimestamp(claimTimestamp(item))}`}><Icon name="play" size={13} />{formatTimestamp(claimTimestamp(item))}–{formatTimestamp(item.end)} 定位播放</button> : <span>旧任务无时间戳</span>}{item.context && <details><summary>展开上下文</summary><p>{item.context}</p></details>}</div>
          </li>)}</ol></article>
          {!!result.outline?.length && <article className="summarySection"><div className="summarySectionHead"><span className="sectionNo">03</span><h3>内容脉络</h3></div><div className="outlineGrid">{result.outline.map((item, index) => <div key={index}><small>{item.title}</small><p>{item.content}</p></div>)}</div></article>}
        </div> : <article className="transcriptPaper"><div className="paperMeta"><span>带时间戳逐字稿</span><span>{result.transcript.length.toLocaleString()} 字 · {result.segments?.length || 0} 段</span></div>{result.segments?.length ? <div className="segmentList">{result.segments.map((segment, index) => <div className="segmentRow" key={index}>{segment.start != null ? <button type="button" onClick={() => handleTimestampClick(segment.start)} aria-label={`定位播放 ${formatTimestamp(segment.start)}`}>{formatTimestamp(segment.start)}</button> : <span>--:--</span>}<p>{segment.text}</p></div>)}</div> : <div className="transcriptText">{result.transcript}</div>}</article>}
      </section>}
    </>}

    {view === "history" && <section className="panelPage">
      <div className="pageHeading"><span className="kicker">LOCAL ARCHIVE / 本地记录</span><h1>最近任务</h1><p>结果保存在这台电脑上。你可以随时打开或删除。</p></div>
      <div className="historyTools"><input value={historyQuery} onChange={event => setHistoryQuery(event.target.value)} placeholder="搜索标题、作者或 BV 号" /><select value={historyFilter} onChange={event => setHistoryFilter(event.target.value)}><option value="all">全部状态</option><option value="completed">已完成</option><option value="processing">处理中</option><option value="partial">部分完成</option><option value="failed">失败</option><option value="cancelled">已取消</option></select></div>
      {visibleHistory.length ? <div className="historyList">{visibleHistory.map(item => <article key={item.job_id}>
        <button className="historyMain" onClick={() => openTask(item.job_id)}>
          <span className={`statusDot ${item.status}`} /><span className="historyText"><strong>{item.title || "未命名任务"}</strong><small>{formatDate(item.created_at)} · {item.model} · {STATUS_LABELS[item.status] || item.status}{!TERMINAL.has(item.status) ? ` · ${item.progress}%` : ""}</small></span><Icon name="arrow-right" size={15} />
        </button><button className="deleteButton" onClick={() => deleteTask(item.job_id)} aria-label={`删除 ${item.title || "任务"}`}>删除</button>
      </article>)}</div> : <div className="emptyState"><b>还没有转录内容。</b><p>粘贴一个视频链接开始使用留文。</p><button onClick={() => setView("home")}>开始第一次转录</button></div>}
    </section>}

    {view === "settings" && <section className="panelPage settingsPage">
      <div className="pageHeading"><span className="kicker">PREFERENCES / 设置</span><h1>处理方式</h1><p>选择速度、准确度与隐私之间的平衡。</p></div>
      <div className="settingGroup"><div><h2>转录模型</h2><p>更大的模型通常更准确，也需要更多时间和内存。</p></div><div className="choiceList">
        {([['large-v3-turbo','Large v3 Turbo','推荐 · 中英文准确度更高'],['medium','Medium','平衡准确度与处理速度'],['small','Small','速度优先 · 英文和专业词准确度较低']] as const).map(([value,title,desc]) => <label key={value} className={settings.model === value ? "selected" : ""}><input type="radio" name="model" checked={settings.model === value} onChange={() => saveSettings({...settings, model:value})}/><span><strong>{title}</strong><small>{desc}</small></span></label>)}
      </div></div>
      <div className="settingGroup"><div><h2>音频语言</h2><p>自动检测适合中英文视频；明确指定语言可减少误判。</p></div><div className="choiceList">
        {([['auto','自动检测','推荐 · 自动识别中文、英文及混合内容'],['zh','中文','固定按中文识别'],['en','English','固定按英文识别']] as const).map(([value,title,desc]) => <label key={value} className={settings.language === value ? "selected" : ""}><input type="radio" name="language" checked={settings.language === value} onChange={() => saveSettings({...settings, language:value})}/><span><strong>{title}</strong><small>{desc}</small></span></label>)}
      </div></div>
      <div className="settingGroup"><div><h2>悬浮播放器</h2><p>控制新打开任务第一次向下阅读时，是否默认展开视频悬浮窗。</p></div><label className="settingToggle">
        <input type="checkbox" checked={settings.autoExpandPlayer} onChange={event => saveSettings({...settings, autoExpandPlayer:event.target.checked})} />
        <span><strong>默认弹出悬浮窗</strong><small>{settings.autoExpandPlayer ? "已开启：新任务首次下滑默认展开；切换开关会同步更新当前任务。" : "已关闭：新任务和当前任务下一次下滑默认显示按钮；主动展开后仍会记住新状态。"}</small></span>
      </label></div>
      <div className="settingGroup"><div><h2>总结服务</h2><p>云端总结会将逐字稿发送至你配置的服务。</p></div><div className="choiceList">
        {([['auto','自动选择',cloudAvailable ? '优先使用 API，失败时退回原文摘录' : '未配置 API，当前只会生成原文摘录'],['local','始终本地','不发送文字；仅提取关键原句，不理解语义'],['cloud','仅 API 语义总结',cloudAvailable ? '使用下方已配置的总结服务' : '请先在下方填写并保存 API 配置']] as const).map(([value,title,desc]) => <label key={value} className={settings.summaryMode === value ? "selected" : ""}><input type="radio" name="summary" checked={settings.summaryMode === value} onChange={() => saveSettings({...settings, summaryMode:value})}/><span><strong>{title}</strong><small>{desc}</small></span></label>)}
      </div></div>
      <div className="settingGroup apiSetting"><div><h2>总结 API</h2><p>配置后，新任务会生成语义总结；历史任务也可直接重新总结，无需再次转录。</p></div><div className="apiForm">
        <label><span>服务商</span><select value={apiConfig.provider} onChange={e => selectApiProvider(e.target.value as ApiConfig["provider"])}>{API_PROVIDER_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select><small className="apiProviderNote">{API_PROVIDER_OPTIONS.find(option => option.value === apiConfig.provider)?.description}</small></label>
        <label><span>{apiConfig.provider === "sensenova" ? "API Key / API_TOKEN" : apiConfig.provider === "gemini" ? "Gemini API Key" : "API Key"}</span><input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={apiConfig.has_api_key ? `已保存 ${apiConfig.key_hint || "密钥"}；留空则不修改` : apiConfig.provider === "compatible" ? "本地服务可留空" : apiConfig.provider === "sensenova" ? "只需粘贴 API Key，不要填 Secret Key" : apiConfig.provider === "gemini" ? "粘贴 AI Studio 生成的 Key" : "粘贴 sk-…"} autoComplete="new-password" /></label>
        {apiConfig.provider !== "sensenova" && <label><span>模型 ID</span><input value={apiConfig.model} onChange={e => setApiConfig({...apiConfig, model: e.target.value, configured: false})} placeholder="例如 gpt-5-mini 或 qwen3:8b" /></label>}
        {apiModels.length > 0 && <label><span>已发现的可用模型</span><select value={apiConfig.model} onChange={e => setApiConfig({...apiConfig, model: e.target.value, configured: false})}>{apiModels.map(model => <option key={model.id} value={model.id}>{model.id}{model.allow_chat === false ? "（不可对话）" : ""}</option>)}</select></label>}
        <div className="apiConnectionCard"><span>连接状态</span><strong>{apiConfig.configured ? `已配置 · ${apiConfig.model}` : "未连接 · 输入 Key 后自动验证"}</strong><small>{apiModels.length ? `已发现 ${apiModels.length} 个模型` : "模型列表会在连接时自动读取"}</small></div>
        <div className="apiActions"><button className="primary" disabled={apiBusy || (apiConfig.provider === "sensenova" && !apiKey.trim() && !apiConfig.has_api_key)} onClick={apiConfig.provider === "sensenova" ? connectSenseNova : saveApiConfig}>{apiBusy ? "处理中…" : apiConfig.provider === "sensenova" ? apiModels.length > 0 ? "连接并验证当前模型" : "连接并自动选择模型" : "保存配置"}</button>{apiConfig.provider === "sensenova" && apiModels.length > 0 && <button type="button" disabled={apiBusy} onClick={() => discoverApiModels("auto")}>自动选择可用模型</button>}{apiConfig.configured && <button disabled={apiBusy} onClick={testApiConfig}>测试连接</button>}{apiConfig.provider !== "sensenova" && <button type="button" disabled={apiBusy || (!apiConfig.configured && !apiKey.trim())} onClick={discoverApiModels}>读取可用模型</button>}{apiConfig.has_api_key && <button disabled={apiBusy} onClick={clearApiKey}>清除密钥</button>}<button type="button" className="apiAdvancedToggle" disabled={apiBusy} onClick={() => setApiAdvancedOpen(value => !value)}>{apiAdvancedOpen ? "收起高级设置" : "高级设置"}</button></div>
        {apiAdvancedOpen && <div className="apiAdvanced"><div className="apiAdvancedHeading"><strong>高级连接设置</strong><small>只有自定义网关、协议异常或模型列表不可用时才需要修改。</small></div><label><span>接口协议</span><select value={apiConfig.protocol} onChange={e => selectApiProtocol(e.target.value as ApiConfig["protocol"])}>{API_PROTOCOL_OPTIONS[apiConfig.provider].map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label><span>API 地址</span><input value={apiConfig.base_url} onChange={e => setApiConfig({...apiConfig, base_url: e.target.value, configured: false})} /></label><label><span>模型 ID</span><input value={apiConfig.model} onChange={e => setApiConfig({...apiConfig, model: e.target.value, configured: false})} /></label></div>}
        {apiMessage && <p className="apiMessage" role="status">{apiMessage}</p>}
        <small className="apiHelp">{apiConfig.provider === "gemini" && <><a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer">打开 Google AI Studio 获取 Key ↗</a> · <a href="https://ai.google.dev/gemini-api/docs/openai" target="_blank" rel="noreferrer">Gemini OpenAI 兼容文档 ↗</a><br />官方兼容接口支持模型列表，保存 Key 后可点击“读取可用模型”；私有代理不支持时再到高级设置手动填写。</>}{apiConfig.provider === "sensenova" && <><a href="https://platform.sensenova.cn/console/keys" target="_blank" rel="noreferrer">打开 SenseNova 控制台获取 API Key ↗</a> · <a href="https://www.sensecore.cn/help/docs/model-as-service/nova/overview/compatible-mode" target="_blank" rel="noreferrer">兼容接口文档 ↗</a><br />首次连接会自动读取并验证模型；发现模型后，选择模型只验证当前选择，不会静默切换。</>}{apiConfig.provider === "compatible" && <>如果服务支持标准 <code>/models</code>，留文会自动读取；本地 Ollama 使用 <code>/api/tags</code>；不支持时只需在高级设置中填写模型 ID。</>}{apiConfig.provider === "openai" && <>OpenAI 支持标准模型列表，保存 Key 后可点击“读取可用模型”自动选择。</>}</small>
        <p className="securityWarning">密钥优先使用 Windows 当前用户加密保存；请勿提交或分享 data/config.json、data/credentials.json 或诊断文件。旧版明文配置会在下一次主动保存时迁移。</p>
      </div></div>
      <div className="privacyNote"><span>本地优先</span><p>视频音频、Whisper 转录和历史任务默认留在这台电脑上。只有主动使用云端总结时，逐字稿才会发送到配置的服务。</p></div>
    </section>}

    {preflightOpen && <div className="dialogBackdrop" role="presentation" onMouseDown={event => {
      if (event.target === event.currentTarget) setPreflightOpen(false);
    }}>
      <section className="transcriptionDialog" role="dialog" aria-modal="true" aria-labelledby="transcription-dialog-title">
        <div className="dialogHead">
          <div><span className="kicker">{firstUseConfirmed ? "TRANSCRIPTION MODEL" : "FIRST USE"}</span><h2 id="transcription-dialog-title">{firstUseConfirmed ? "这次使用哪个转录模型？" : "开始前，先完成首次使用确认"}</h2></div>
          <button type="button" onClick={() => setPreflightOpen(false)} aria-label="关闭"><Icon name="close" size={18} /></button>
        </div>

        {!firstUseConfirmed && <div className="usageLimits">
          <h3>关键使用限制</h3>
          <label><input type="checkbox" checked={usageChecks.rights} onChange={event => setUsageChecks({...usageChecks, rights: event.target.checked})} /><span><strong>内容权限</strong>我确认有权处理该视频，并会遵守平台规则、版权和适用法律。</span></label>
          <label><input type="checkbox" checked={usageChecks.accuracy} onChange={event => setUsageChecks({...usageChecks, accuracy: event.target.checked})} /><span><strong>结果核对</strong>我理解自动转录和总结可能出错，重要信息会回看原视频核对。</span></label>
          <label><input type="checkbox" checked={usageChecks.resources} onChange={event => setUsageChecks({...usageChecks, resources: event.target.checked})} /><span><strong>本机资源与隐私</strong>首次使用会下载模型并占用网络、磁盘和 CPU；启用云端总结后，逐字稿会发送给所选 API 服务。</span></label>
        </div>}

        <div className="modelPicker">
          <h3>选择本次转录模型</h3>
          <div className="modelPickerList">{TRANSCRIPTION_MODELS.map(model => <label key={model.value} className={selectedModel === model.value ? "selected" : ""}>
            <input type="radio" name="preflight-model" checked={selectedModel === model.value} onChange={() => setSelectedModel(model.value)} />
            <span><strong>{model.title}<small>{model.badge}</small></strong><em>{model.description}</em></span>
          </label>)}</div>
        </div>

        {!firstUseConfirmed && <div className="apiDecision">
          <div><h3>总结 API（可选）</h3><p>{cloudAvailable ? "已检测到可用配置，将优先生成语义总结。" : "不配置也能完成本地转录，并生成原文提要；以后可随时在设置中添加。"}</p></div>
          {cloudAvailable
            ? <span className="configuredMark"><Icon name="check" size={14} />已配置</span>
            : <div><button type="button" onClick={openApiSettingsFromPreflight} disabled={!usageChecks.rights || !usageChecks.accuracy || !usageChecks.resources}>现在设置</button><button type="button" className={apiDecision === "later" ? "selected" : ""} onClick={() => setApiDecision("later")}>以后再说</button></div>}
        </div>}

        <div className="dialogActions">
          <button type="button" onClick={() => setPreflightOpen(false)}>取消</button>
          <button type="button" className="primary" onClick={confirmTranscription} disabled={!firstUseConfirmed && (!usageChecks.rights || !usageChecks.accuracy || !usageChecks.resources || !apiDecision)}>使用 {TRANSCRIPTION_MODELS.find(model => model.value === selectedModel)?.title} 开始转录</button>
        </div>
      </section>
    </div>}

    <footer><span>留文 · WENL SCRIBE</span><span>本地优先，结果清晰，内容属于用户。</span><span>A WENL PROJECT</span></footer>
  </main>;
}

function ErrorCard({ message, info, onRetry }: { message: string; info?: ErrorInfo; onRetry: () => void }) {
  return <div className="errorCard" role="alert"><span className="errorMark"><Icon name="warning" size={17} /></span><div><strong>这次没有完成</strong><p>{message}</p>{info && <small>错误码：{info.code}{info.stage ? ` · 失败阶段：${STAGE_LABELS[info.stage] || info.stage}` : ""}{info.retryable ? " · 可以重试" : ""}</small>}</div><button onClick={onRetry}>{info?.retryable ? "重试" : "关闭"}</button></div>;
}
