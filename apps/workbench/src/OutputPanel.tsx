import { useState, useRef, useEffect } from "react";
import type { OpenCodeEvent } from "./sdet/types";

interface OutputPanelProps {
  testCode: string | null;
  opencodeLiveCode: string;
  opencodeRunning: boolean;
  opencodeEvents: OpenCodeEvent[];
  opencodeFinalCode: string | null;
}

type OutputTab = "test" | "stream";

export default function OutputPanel({
  testCode,
  opencodeLiveCode,
  opencodeRunning,
  opencodeEvents,
  opencodeFinalCode,
}: OutputPanelProps) {
  const [activeTab, setActiveTab] = useState<OutputTab>("test");
  const streamRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight;
    }
  }, [opencodeLiveCode, opencodeEvents.length]);

  const displayCode = opencodeFinalCode || testCode || opencodeLiveCode;

  return (
    <section className="panel output-panel">
      <div className="op-tabs">
        <button
          className={`op-tab ${activeTab === "test" ? "op-tab-active" : ""}`}
          onClick={() => setActiveTab("test")}
        >
          Test Code
          {displayCode && <span className="op-tab-dot" />}
        </button>
        <button
          className={`op-tab ${activeTab === "stream" ? "op-tab-active" : ""}`}
          onClick={() => setActiveTab("stream")}
        >
          OpenCode Stream
          {opencodeRunning && <span className="op-tab-live" />}
        </button>
      </div>

      {activeTab === "test" && (
        <div className="op-test">
          {displayCode ? (
            <>
              <div className="op-test-header">
                <span className="op-test-label">
                  {opencodeRunning ? "Generating..." : opencodeFinalCode ? "Final Test Code" : "Test Code"}
                </span>
                {opencodeRunning && <span className="op-test-spinner" />}
                {displayCode && (
                  <button
                    className="op-test-copy"
                    onClick={() => navigator.clipboard.writeText(displayCode)}
                  >
                    Copy
                  </button>
                )}
              </div>
              <pre className="op-test-pre"><code>{displayCode}</code></pre>
            </>
          ) : (
            <div className="op-empty">
              <div className="op-empty-icon">&lt;/&gt;</div>
              <div className="op-empty-text">No test code generated yet</div>
              <div className="op-empty-hint">
                Start a session and complete the SDET flow to generate test code
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "stream" && (
        <div className="op-stream" ref={streamRef}>
          {opencodeEvents.length === 0 && !opencodeRunning ? (
            <div className="op-empty">
              <div className="op-empty-icon">~</div>
              <div className="op-empty-text">No OpenCode activity yet</div>
              <div className="op-empty-hint">
                OpenCode runs when the SDET agent reaches the Generate phase
              </div>
            </div>
          ) : (
            <>
              <div className="op-stream-header">
                <span className="op-stream-title">
                  {opencodeRunning ? "Running..." : "Complete"}
                </span>
                {opencodeRunning && <span className="op-stream-spinner" />}
                <span className="op-stream-count">{opencodeEvents.length} events</span>
              </div>
              {opencodeEvents.map((evt, i) => {
                if (evt.type === "opencode_error") {
                  return <div key={i} className="op-stream-error">Error: {evt.content}</div>;
                }
                if (evt.type === "opencode_complete") return null;
                const e = evt as any;
                if (e.event === "node" && e.content) {
                  return <div key={i} style={{ fontWeight: 600, opacity: 0.85, margin: "6px 0 2px" }}>{e.content}</div>;
                }
                if (e.event === "system" && e.content) {
                  return <div key={i} style={{ opacity: 0.6, fontStyle: "italic", margin: "2px 0" }}>{e.content}</div>;
                }
                if (e.event === "tool_use") {
                  const statusIcon = e.status === "completed" ? "\u2713" : e.status === "running" ? "\u25B6" : "\u25CB";
                  if (e.command) {
                    return (
                      <div key={i} className="op-stream-line">
                        <span className="op-stream-line-icon">{statusIcon}</span>
                        <span className="op-stream-tag op-stream-tag-bash">bash</span>
                        <span className="op-stream-body">{e.command}</span>
                        {e.output && <pre className="op-stream-pre">{e.output}</pre>}
                      </div>
                    );
                  }
                  if (e.file_content) {
                    return (
                      <div key={i} className="op-stream-line">
                        <span className="op-stream-line-icon">{statusIcon}</span>
                        <span className="op-stream-tag op-stream-tag-write">{e.tool}</span>
                        <span className="op-stream-body">{e.path}</span>
                        <pre className="op-stream-pre"><code>{e.file_content}</code></pre>
                      </div>
                    );
                  }
                  if (e.path) {
                    return (
                      <div key={i} className="op-stream-line">
                        <span className="op-stream-line-icon">{statusIcon}</span>
                        <span className="op-stream-tag op-stream-tag-read">{e.tool}</span>
                        <span className="op-stream-body">{e.path}</span>
                      </div>
                    );
                  }
                  return (
                    <div key={i} className="op-stream-line">
                      <span className="op-stream-line-icon">{statusIcon}</span>
                      <span className="op-stream-tag">{e.tool}</span>
                      <span className="op-stream-body">{e.content || e.status}</span>
                    </div>
                  );
                }
                if (e.event === "text" && e.content) {
                  return <div key={i} className="op-stream-text">{e.content}</div>;
                }
                if (e.event === "thinking" && e.content) {
                  return <div key={i} className="op-stream-think">{e.content}</div>;
                }
                return null;
              })}
              {opencodeLiveCode && (
                <div className="op-stream-code">
                  <div className="op-stream-code-header">
                    Generated Code
                    {opencodeRunning && <span className="op-stream-code-live">LIVE</span>}
                  </div>
                  <pre className="op-stream-code-pre"><code>{opencodeLiveCode}</code></pre>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
