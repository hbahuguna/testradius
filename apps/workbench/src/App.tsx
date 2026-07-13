import { useState, useCallback } from "react";
import "./App.css";
import AgentPanel from "./sdet/AgentPanel";
import VerticalTabs from "./layout/VerticalTabs";
import ContentArea from "./layout/ContentArea";
import PreviewPanel from "./preview/PreviewPanel";
import EditorPanel from "./editor/EditorPanel";
import OutputPanel from "./OutputPanel";
import AgenticTester from "./sdet/AgenticTester";
import type { ContextElement, RecordedAction, OpenCodeEvent } from "./sdet/types";
import type { TabDef } from "./layout/VerticalTabs";

const API_BASE = import.meta.env.VITE_WORKBENCH_API || "";
const SDET_API_BASE = import.meta.env.VITE_SDET_API || "http://localhost:8004";
const WORKBENCH_REPO_DEFAULT = import.meta.env.VITE_WORKBENCH_REPO || "";

function proxyEncode(url: string): string {
  return btoa(url.replace(/\/+$/, ""))
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function inferActionType(tag: string, elType?: string): string {
  const t = tag.toLowerCase();
  if (elType === "checkbox" || (t === "input" && elType === "checkbox")) return "check";
  if (t === "select") return "select";
  if (t === "input" || t === "textarea") return "fill";
  if (t === "a" || t === "button") return "click";
  return "click";
}

function genId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

const TABS: TabDef[] = [
  {
    id: "preview",
    label: "Preview",
    icon: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`,
  },
  {
    id: "code",
    label: "Code",
    icon: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`,
  },
  {
    id: "output",
    label: "Output",
    icon: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`,
  },
  {
    id: "agentic",
    label: "Agentic",
    icon: `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/></svg>`,
  },
];

function App() {
  const [url, setUrl] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [repoDir, setRepoDir] = useState(WORKBENCH_REPO_DEFAULT);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("preview");
  const [contextElements, setContextElements] = useState<ContextElement[]>([]);
  const [recordedActions, setRecordedActions] = useState<RecordedAction[]>([]);
  const [elementSelectionMode, setElementSelectionMode] = useState(false);
  const [recordingMode, setRecordingMode] = useState(false);
  const [sharedTestCode, setSharedTestCode] = useState<string | null>(null);
  const [sharedOpencodeEvents, setSharedOpencodeEvents] = useState<OpenCodeEvent[]>([]);
  const [sharedOpencodeRunning, setSharedOpencodeRunning] = useState(false);
  const [sharedOpencodeLiveCode, setSharedOpencodeLiveCode] = useState("");
  const [sharedOpencodeFinalCode, setSharedOpencodeFinalCode] = useState<string | null>(null);

  const handleOpencodeStateChange = useCallback((state: {
    testCode: string | null;
    opencodeEvents: OpenCodeEvent[];
    opencodeRunning: boolean;
    opencodeLiveCode: string;
    opencodeFinalCode: string | null;
  }) => {
    setSharedTestCode(state.testCode);
    setSharedOpencodeEvents(state.opencodeEvents);
    setSharedOpencodeRunning(state.opencodeRunning);
    setSharedOpencodeLiveCode(state.opencodeLiveCode);
    setSharedOpencodeFinalCode(state.opencodeFinalCode);
  }, []);

  const handleElementClick = useCallback((data: { cssPath: string; tag: string; text: string; id: string; inShadowDOM?: boolean }) => {
    const actionType = inferActionType(data.tag);
    setContextElements(prev => {
      const existing = prev.find(el => el.cssPath === data.cssPath);
      if (existing) return prev;
      return [...prev, {
        id: genId(),
        cssPath: data.cssPath,
        tag: data.tag,
        text: data.text,
        elementId: data.id,
        actionType,
      }];
    });
  }, []);

  const handleRecordAction = useCallback((action: RecordedAction) => {
    setRecordedActions(prev => [...prev, action]);
  }, []);

  const removeContextElement = useCallback((id: string) => {
    setContextElements(prev => prev.filter(el => el.id !== id));
  }, []);

  const clearContext = useCallback(() => {
    setContextElements([]);
    setRecordedActions([]);
  }, []);

  const handleRecordingModeToggle = useCallback(() => {
    setRecordingMode(prev => !prev);
  }, []);

  const handleDeleteAction = useCallback((index: number) => {
    setRecordedActions(prev => {
      const next = prev.filter((_, i) => i !== index);
      return next.map((a, i) => ({ ...a, step_order: i + 1 }));
    });
  }, []);

  const handleMoveAction = useCallback((index: number, direction: "up" | "down") => {
    setRecordedActions(prev => {
      const target = direction === "up" ? index - 1 : index + 1;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((a, i) => ({ ...a, step_order: i + 1 }));
    });
  }, []);

  const handleGo = useCallback(async () => {
    if (!url.trim()) return;
    setLoading(true);
    setError(null);
    setContextElements([]);
    setRecordedActions([]);
    setElementSelectionMode(false);
    setRecordingMode(false);
    setPreviewUrl(url.trim());
    setLoading(false);
  }, [url]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleGo();
  };

  const previewSrc = previewUrl
    ? (() => {
        const u = new URL(previewUrl);
        const base = proxyEncode(u.origin);
        const path = u.pathname.replace(/\/$/, "");
        return `${API_BASE}/v/${base}${path}/`;
      })()
    : null;

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-top">
          <h1>TestSquad Workbench</h1>
        </div>
        <div className="toolbar">
          <input
            className="url-bar"
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Enter URL (e.g. https://example.com)"
          />
          <button className="go-btn" onClick={handleGo} disabled={loading}>
            {loading ? "..." : "Go"}
          </button>
        </div>
        {error && <div className="error-bar">{error}</div>}
      </header>

      <main className="app-main">
        <VerticalTabs tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab} />

        <ContentArea activeTab={activeTab}>
          {activeTab === "preview" && (
            <PreviewPanel
              previewUrl={previewUrl}
              previewSrc={previewSrc}
              elementSelectionMode={elementSelectionMode}
              recordingMode={recordingMode}
              contextElementsCount={contextElements.length}
              recordedActions={recordedActions}
              onElementClick={handleElementClick}
              onRecordingModeToggle={handleRecordingModeToggle}
              onRecordAction={handleRecordAction}
              onDeleteAction={handleDeleteAction}
              onMoveAction={handleMoveAction}
            />
          )}
          {activeTab === "code" && (
            <EditorPanel
              apiBase={SDET_API_BASE}
              repoDir={repoDir}
            />
          )}
          {activeTab === "output" && (
            <OutputPanel
              testCode={sharedTestCode}
              opencodeLiveCode={sharedOpencodeLiveCode}
              opencodeRunning={sharedOpencodeRunning}
              opencodeEvents={sharedOpencodeEvents}
              opencodeFinalCode={sharedOpencodeFinalCode}
            />
          )}
          {activeTab === "agentic" && (
            <AgenticTester
              apiBase={SDET_API_BASE}
              url={previewUrl || ""}
              repoDir={repoDir}
              recordedActions={recordedActions}
              contextElements={contextElements}
            />
          )}
        </ContentArea>

        <section className="panel agent-panel">
          <div className="panel-header">
            <span>SDET Agent</span>
            <span className="count">{contextElements.length} element{contextElements.length !== 1 ? "s" : ""} selected</span>
          </div>
          <AgentPanel
            apiBase={SDET_API_BASE}
            url={previewUrl || ""}
            repoDir={repoDir}
            onRepoDirChange={setRepoDir}
            contextElements={contextElements}
            recordedActions={recordedActions}
            onRemoveElement={removeContextElement}
            onClearElements={clearContext}
            onElementSelectionChange={setElementSelectionMode}
            onOpencodeStateChange={handleOpencodeStateChange}
          />
        </section>
      </main>
    </div>
  );
}

export default App;
