import { useEffect, useState } from "react";

import { getHarnessApi } from "../api";
import type { EvidenceArtifact, EvidenceManifest } from "../types";

interface EvidencePageProps {
  runId?: string;
}

function groupByType(artifacts: EvidenceArtifact[]) {
  const groups: Record<string, EvidenceArtifact[]> = {};
  for (const a of artifacts) {
    if (!groups[a.type]) groups[a.type] = [];
    groups[a.type].push(a);
  }
  return groups;
}

export function EvidencePage({ runId = "20261030103857" }: EvidencePageProps): JSX.Element {
  const api = getHarnessApi();
  const [manifest, setManifest] = useState<EvidenceManifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<string | null>(null);
  const [consoleText, setConsoleText] = useState<string | null>(null);
  const [networkText, setNetworkText] = useState<string | null>(null);
  const [loadingInspect, setLoadingInspect] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getRunEvidence(runId)
      .then((m) => {
        if (!cancelled) setManifest(m);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [api, runId]);

  const groups = manifest ? groupByType(manifest.artifacts) : {};
  const screenshots = groups.screenshot ?? [];
  const videos = groups.video ?? [];
  const traces = groups.trace ?? [];
  const consoleLogs = groups.console ?? [];
  const networks = groups.network ?? [];

  const inspect = async (path: string, kind: "console" | "network") => {
    setLoadingInspect(true);
    try {
      const res = await fetch(`/${path}`);
      const text = await res.text();
      if (kind === "console") setConsoleText(text);
      else setNetworkText(text);
    } catch (e) {
      if (kind === "console") setConsoleText(`Failed to load: ${e}`);
      else setNetworkText(`Failed to load: ${e}`);
    } finally {
      setLoadingInspect(false);
    }
  };

  return (
    <section className="page">
      <div className="page__head">
        <div>
          <h2>Evidence Center</h2>
          <p className="muted">Screenshots, video (.webm), traces, console and network logs.</p>
        </div>
        <div className="page__head-actions">
          <span className={`pill ${api.mode === "http" ? "pill--ok" : "pill--warn"}`}>
            {api.mode === "http" ? "live" : "mock"}
          </span>
          <a className="btn btn--ghost" href="#/runs">
            ← Back to Runs
          </a>
        </div>
      </div>

      {error && <p className="error">Failed to load evidence: {error}</p>}

      {!manifest && !error && <p className="muted">Loading evidence…</p>}

      {manifest && (
        <>
          <div className="notice">
            <dl className="notice__meta">
              <div>
                <dt>Run ID</dt>
                <dd className="table__mono">{manifest.run_id}</dd>
              </div>
              <div>
                <dt>Artifacts</dt>
                <dd>{manifest.artifacts.length}</dd>
              </div>
            </dl>
          </div>

          {videos.length > 0 && (
            <div className="evidence__section">
              <div className="evidence__section-header">
                <h3>Video Recording</h3>
                <span className="muted">{videos.length} video(s)</span>
              </div>
              <div className="evidence__video">
                {videos.map((v) => (
                  <video key={v.path} controls className="evidence__video-player">
                    <source src={`/${v.path}`} type="video/webm" />
                    Your browser does not support the video tag.
                  </video>
                ))}
              </div>
            </div>
          )}

          {screenshots.length > 0 && (
            <div className="evidence__section">
              <div className="evidence__section-header">
                <h3>Screenshots</h3>
                <span className="muted">{screenshots.length} screenshot(s)</span>
              </div>
              <div className="evidence__grid">
                {screenshots.map((s) => (
                  <button
                    key={s.path}
                    className="evidence__thumb"
                    onClick={() => setLightbox(s.path)}
                    title={s.path.split("/").pop()}
                  >
                    <img src={`/${s.path}`} alt={s.path.split("/").pop()} loading="lazy" />
                    <span className="evidence__thumb-label">{s.path.split("/").pop()}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {(traces.length > 0 || consoleLogs.length > 0 || networks.length > 0) && (
            <div className="evidence__section">
              <div className="evidence__section-header">
                <h3>Traces, Console & Network</h3>
              </div>
              <div className="evidence__files">
                {traces.map((t) => (
                  <a key={t.path} className="evidence__file" href={`/${t.path}`} download>
                    <span className="pill">trace</span>
                    <span className="table__mono">{t.path}</span>
                    <span className="muted">Download Playwright trace</span>
                  </a>
                ))}
                {consoleLogs.map((c) => (
                  <div key={c.path} className="evidence__file evidence__file--button">
                    <span className="pill">console</span>
                    <span className="table__mono">{c.path}</span>
                    <button className="btn btn--ghost btn--sm" onClick={() => inspect(c.path, "console")} disabled={loadingInspect}>
                      Inspect
                    </button>
                    <a className="btn btn--ghost btn--sm" href={`/${c.path}`} target="_blank" rel="noreferrer">
                      Open
                    </a>
                  </div>
                ))}
                {networks.map((n) => (
                  <div key={n.path} className="evidence__file evidence__file--button">
                    <span className="pill">network</span>
                    <span className="table__mono">{n.path}</span>
                    <button className="btn btn--ghost btn--sm" onClick={() => inspect(n.path, "network")} disabled={loadingInspect}>
                      Inspect
                    </button>
                    <a className="btn btn--ghost btn--sm" href={`/${n.path}`} target="_blank" rel="noreferrer">
                      Open
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}

          {consoleText !== null && (
            <div className="evidence__section">
              <div className="evidence__section-header">
                <h3>Console Output</h3>
                <button className="btn btn--ghost btn--sm" onClick={() => setConsoleText(null)}>
                  Close
                </button>
              </div>
              <pre className="evidence__pre">{consoleText || "(empty)"}</pre>
            </div>
          )}

          {networkText !== null && (
            <div className="evidence__section">
              <div className="evidence__section-header">
                <h3>Network Trace</h3>
                <button className="btn btn--ghost btn--sm" onClick={() => setNetworkText(null)}>
                  Close
                </button>
              </div>
              <pre className="evidence__pre">{networkText || "(empty)"}</pre>
            </div>
          )}
        </>
      )}

      {lightbox && (
        <div className="lightbox" onClick={() => setLightbox(null)}>
          <button className="lightbox__close" onClick={() => setLightbox(null)}>
            ×
          </button>
          <img src={`/${lightbox}`} alt={lightbox} className="lightbox__image" onClick={(e) => e.stopPropagation()} />
        </div>
      )}
    </section>
  );
}
