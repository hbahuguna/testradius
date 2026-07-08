import { useRef, useEffect, useState, useCallback } from "react";
import type { RecordedAction, LocatorOption, PendingElement } from "../sdet/types";
import RecordingToolbar from "./RecordingToolbar";
import ActionSequenceList from "./ActionSequenceList";

function inferActionType(tag: string, attrs?: Record<string, string>): string {
  const t = tag.toLowerCase();
  const elType = (attrs?.["type"] || "").toLowerCase();
  if (elType === "checkbox" || (t === "input" && elType === "checkbox")) return "check";
  if (t === "select") return "select";
  if (t === "input" || t === "textarea") return "fill";
  if (t === "a" || t === "button") return "click";
  return "click";
}

function generateLocators(data: {
  cssPath: string; tag: string; text: string; id: string; classes: string;
  attributes: Record<string, string>;
}): LocatorOption[] {
  const locators: LocatorOption[] = [];

  if (data.id) {
    locators.push({
      type: "id", value: data.id,
      strategy: `#${data.id}`,
      label: "By ID", brittleness: 1,
    });
  }

  const testid = data.attributes["data-testid"] || data.attributes["data-test"] || data.attributes["data-cy"] || data.attributes["data-tid"];
  if (testid) {
    locators.push({
      type: "testid", value: testid,
      strategy: `[data-testid="${testid}"]`,
      label: "By data-testid", brittleness: 1,
    });
  }

  if (data.attributes["aria-label"]) {
    locators.push({
      type: "aria", value: data.attributes["aria-label"],
      strategy: `[aria-label="${data.attributes["aria-label"]}"]`,
      label: "By ARIA label", brittleness: 2,
    });
  }

  if (data.attributes["name"]) {
    locators.push({
      type: "name", value: data.attributes["name"],
      strategy: `[name="${data.attributes["name"]}"]`,
      label: "By name", brittleness: 2,
    });
  }

  if (data.attributes["placeholder"]) {
    locators.push({
      type: "placeholder", value: data.attributes["placeholder"],
      strategy: `[placeholder="${data.attributes["placeholder"]}"]`,
      label: "By placeholder", brittleness: 2,
    });
  }

  if (data.attributes["alt"]) {
    locators.push({
      type: "alt", value: data.attributes["alt"],
      strategy: `[alt="${data.attributes["alt"]}"]`,
      label: "By alt text", brittleness: 2,
    });
  }

  if (data.text && (data.tag === "a" || data.tag === "button" || data.tag === "label")) {
    const txt = data.text.slice(0, 60);
    locators.push({
      type: "text", value: txt,
      strategy: `text=${txt}`,
      label: "By text", brittleness: 2,
    });
  }

  if (data.attributes["role"]) {
    locators.push({
      type: "role", value: data.attributes["role"],
      strategy: `[role="${data.attributes["role"]}"]`,
      label: "By role", brittleness: 3,
    });
  }

  locators.push({
    type: "css", value: data.cssPath,
    strategy: data.cssPath,
    label: "By CSS path", brittleness: 3,
  });

  const seen = new Set<string>();
  return locators.filter(l => {
    const k = l.type + ":" + l.value;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

interface PreviewPanelProps {
  previewUrl: string | null;
  previewSrc: string | null;
  elementSelectionMode: boolean;
  recordingMode: boolean;
  contextElementsCount: number;
  recordedActions: RecordedAction[];
  onElementClick: (data: { cssPath: string; tag: string; text: string; id: string; inShadowDOM?: boolean }) => void;
  onRecordingModeToggle: () => void;
  onRecordAction: (action: RecordedAction) => void;
  onDeleteAction: (index: number) => void;
  onMoveAction: (index: number, direction: "up" | "down") => void;
}

export default function PreviewPanel({
  previewUrl,
  previewSrc,
  elementSelectionMode,
  recordingMode,
  contextElementsCount,
  recordedActions,
  onElementClick,
  onRecordingModeToggle,
  onRecordAction,
  onDeleteAction,
  onMoveAction,
}: PreviewPanelProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const webviewRef = useRef<any>(null);
  const webviewContainerRef = useRef<HTMLDivElement>(null);
  const isElectron = navigator.userAgent.includes("Electron");
  const [pendingEl, setPendingEl] = useState<PendingElement | null>(null);

  useEffect(() => {
    if (!isElectron || !previewUrl || !webviewContainerRef.current) return;
    const container = webviewContainerRef.current;
    container.innerHTML = "";
    const webview = document.createElement("webview") as any;
    webview.src = previewUrl;
    webview.setAttribute("style", "width:100%;height:100%;border:none");
    webview.setAttribute("allowpopups", "");
    container.appendChild(webview);
    webviewRef.current = webview;
    const onDomReady = () => {
      fetch('/static/inspector_script.js')
        .then(r => r.text())
        .then(code => webview.executeJavaScript(code))
        .catch(() => {});
    };
    const onConsoleMessage = (e: { message: string }) => {
      try {
        const msg = JSON.parse(e.message);
        if (msg.type === "ts-element-click") handleIframeClick(msg);
      } catch {}
    };
    webview.addEventListener("dom-ready", onDomReady);
    webview.addEventListener("console-message", onConsoleMessage);
    return () => {
      webview.removeEventListener("dom-ready", onDomReady);
      webview.removeEventListener("console-message", onConsoleMessage);
    };
  }, [previewUrl, isElectron]);

  const handleIframeClick = useCallback((data: any) => {
    if (pendingEl) return;
    const attrs: Record<string, string> = data.attributes || {};
    if (recordingMode) {
      const locators = generateLocators({
        cssPath: data.cssPath, tag: data.tag, text: data.text,
        id: data.id, classes: data.classes || "", attributes: attrs,
      });
      setPendingEl({
        tag: data.tag, text: data.text, id: data.id,
        classes: data.classes || "", cssPath: data.cssPath,
        attributes: attrs, locators, selectedLocator: locators[0] || null,
      });
    } else {
      onElementClick({
        cssPath: data.cssPath, tag: data.tag, text: data.text,
        id: data.id, inShadowDOM: data.inShadowDOM,
      });
    }
  }, [recordingMode, onElementClick, pendingEl]);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "ts-element-click") {
        handleIframeClick(e.data);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [handleIframeClick]);

  const executeOnPage = useCallback((actionType: string, strategy: string, value?: string) => {
    if (isElectron && webviewRef.current) {
      const js = `window.tsExecAction("${actionType}","${strategy.replace(/"/g,'\\"')}","${(value||'').replace(/"/g,'\\"')}")`;
      webviewRef.current.executeJavaScript(js).catch(() => {});
    } else if (iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage({ type: "ts-execute", actionType, strategy, value }, "*");
    }
  }, [isElectron]);

  const handleConfirmLocator = useCallback(() => {
    if (!pendingEl || !pendingEl.selectedLocator) return;
    const l = pendingEl.selectedLocator;
    const actionType = inferActionType(pendingEl.tag, pendingEl.attributes);
    onRecordAction({
      css_path: l.strategy,
      locator_type: l.type,
      tag: pendingEl.tag,
      action_type: actionType,
      text: pendingEl.text,
      element_id: pendingEl.id,
      step_order: recordedActions.length + 1,
    });
    executeOnPage(actionType, l.strategy);
    setPendingEl(null);
  }, [pendingEl, recordedActions.length, onRecordAction, executeOnPage]);

  const handleCancelLocator = useCallback(() => {
    setPendingEl(null);
  }, []);

  const handleSelectLocator = useCallback((locator: LocatorOption) => {
    setPendingEl(prev => prev ? { ...prev, selectedLocator: locator } : null);
  }, []);

  const modeLabel = recordingMode ? "Recording" : elementSelectionMode ? "Selecting" : null;

  return (
    <section className="panel preview-panel">
      <div className="panel-header">
        <span>Visual Preview</span>
        <div className="panel-header-right">
          <RecordingToolbar recordingMode={recordingMode} onToggle={onRecordingModeToggle} />
          {modeLabel && <span className="pv-mode-badge" data-mode={modeLabel.toLowerCase()}>{modeLabel}</span>}
          <span className="count">
            {recordingMode
              ? `${recordedActions.length} action${recordedActions.length !== 1 ? "s" : ""}`
              : `${contextElementsCount} element${contextElementsCount !== 1 ? "s" : ""}`
            }
          </span>
        </div>
      </div>
      <div className="preview-content" style={{ position: "relative" }}>
        {previewUrl && previewSrc ? (
          <>
            {isElectron ? (
              <div ref={webviewContainerRef} className="preview-iframe" />
            ) : (
              <iframe
                ref={iframeRef}
                className="preview-iframe"
                src={previewSrc}
                title="Page Preview"
              />
            )}
            {!pendingEl && elementSelectionMode && !recordingMode && (
              <div className="pv-overlay">
                <div className="pv-overlay-content">
                  <div className="pv-overlay-icon">&#9678;</div>
                  <div className="pv-overlay-title">Element Selection Mode</div>
                  <div className="pv-overlay-text">
                    Click on the page elements you want to include in your test.
                    Selected elements will appear as chips below the chat.
                  </div>
                  <div className="pv-overlay-count">
                    {contextElementsCount} element{contextElementsCount !== 1 ? "s" : ""} selected
                  </div>
                </div>
              </div>
            )}
            {!pendingEl && recordingMode && !elementSelectionMode && (
              <div className="pv-overlay pv-recording-overlay">
                <div className="pv-overlay-content">
                  <div className="pv-overlay-icon pv-rec-icon">&#9679;</div>
                  <div className="pv-overlay-title">Recording Actions</div>
                  <div className="pv-overlay-text">
                    Click on elements to record each action step. Each click becomes a step in the test sequence.
                  </div>
                  <div className="pv-overlay-count">
                    {recordedActions.length} action{recordedActions.length !== 1 ? "s" : ""} recorded
                  </div>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="placeholder">Enter a URL and click Go to preview a page.</div>
        )}
      </div>

      {pendingEl && (
        <div className="lp-panel">
          <div className="lp-header">
            <span className="lp-title">Record Action</span>
            <span className="lp-el-tag">&lt;{pendingEl.tag}&gt;</span>
            <span className="lp-el-action">{inferActionType(pendingEl.tag, pendingEl.attributes)}</span>
            {pendingEl.text && <span className="lp-el-text">"{pendingEl.text.slice(0, 50)}"</span>}
          </div>
          <div className="lp-strategies">
            {pendingEl.locators.map((loc, i) => (
              <div
                key={loc.type + i}
                className={`lp-strategy ${pendingEl.selectedLocator?.type === loc.type && pendingEl.selectedLocator?.value === loc.value ? "lp-selected" : ""}`}
                onClick={() => handleSelectLocator(loc)}
              >
                <div className="lp-strategy-radio">
                  {pendingEl.selectedLocator?.type === loc.type && pendingEl.selectedLocator?.value === loc.value ? "◉" : "○"}
                </div>
                <div className="lp-strategy-body">
                  <div className="lp-strategy-top">
                    <span className="lp-strategy-label">{loc.label}</span>
                    <span className="lp-strategy-brittleness">
                      {"★".repeat(Math.max(1, 4 - loc.brittleness))}{"☆".repeat(loc.brittleness)}
                    </span>
                  </div>
                  <code className="lp-strategy-value">{loc.strategy}</code>
                </div>
              </div>
            ))}
          </div>
          <div className="lp-actions">
            <button className="lp-cancel-btn" onClick={handleCancelLocator}>Cancel</button>
            <button className="lp-record-btn" onClick={handleConfirmLocator} disabled={!pendingEl.selectedLocator}>
              Record Action
            </button>
          </div>
        </div>
      )}

      <ActionSequenceList
        actions={recordedActions}
        onDelete={onDeleteAction}
        onMoveUp={(i) => onMoveAction(i, "up")}
        onMoveDown={(i) => onMoveAction(i, "down")}
      />
    </section>
  );
}
