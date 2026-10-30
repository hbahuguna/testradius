import { useEffect, useState } from "react";

import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { EvidencePage } from "./pages/EvidencePage";
import { NewRunPage } from "./pages/NewRunPage";
import { PlanReviewPage } from "./pages/PlanReviewPage";
import { ResultsPage } from "./pages/ResultsPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";

export type Route =
  | "runs"
  | "new-run"
  | "evidence"
  | "results"
  | "settings"
  | "plan-review";

const ROUTES: Route[] = ["runs", "new-run", "evidence", "results", "settings", "plan-review"];

function parseHash(): { route: Route; planRunId?: string } {
  const raw = window.location.hash.replace(/^#\/?/, "");
  if (raw.startsWith("plan-review/")) {
    const planRunId = raw.split("/")[1];
    return { route: "plan-review", planRunId };
  }
  const candidate = raw as Route;
  return { route: ROUTES.includes(candidate) ? candidate : "runs" };
}

export default function App(): JSX.Element {
  const [state, setState] = useState(parseHash);

  useEffect(() => {
    const onHashChange = () => setState(parseHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return (
    <div className="shell">
      <Sidebar current={state.route} />
      <div className="shell__main">
        <TopBar route={state.route} />
        <main className="shell__content">
          {state.route === "runs" && <RunsPage />}
          {state.route === "new-run" && <NewRunPage />}
          {state.route === "plan-review" && state.planRunId && (
            <PlanReviewPage
              runId={state.planRunId}
              onBack={() => {
                window.location.hash = "#/runs";
              }}
              onApproved={() => {
                window.location.hash = "#/runs";
              }}
            />
          )}
          {state.route === "plan-review" && !state.planRunId && (
            <section className="page">
              <div className="empty">
                <h2>Missing run</h2>
                <p>Select a run from history to review its plan.</p>
                <a className="btn" href="#/runs">
                  Go to Runs
                </a>
              </div>
            </section>
          )}
          {state.route === "evidence" && <EvidencePage />}
          {state.route === "results" && <ResultsPage />}
          {state.route === "settings" && <SettingsPage />}
        </main>
      </div>
    </div>
  );
}
