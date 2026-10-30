import { useEffect, useState } from "react";

import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { EvidencePage } from "./pages/EvidencePage";
import { NewRunPage } from "./pages/NewRunPage";
import { ResultsPage } from "./pages/ResultsPage";
import { RunsPage } from "./pages/RunsPage";
import { SettingsPage } from "./pages/SettingsPage";

export type Route =
  | "runs"
  | "new-run"
  | "evidence"
  | "results"
  | "settings";

const ROUTES: Route[] = ["runs", "new-run", "evidence", "results", "settings"];

function routeFromHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const candidate = raw as Route;
  return ROUTES.includes(candidate) ? candidate : "runs";
}

export default function App(): JSX.Element {
  const [route, setRoute] = useState<Route>(routeFromHash);

  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return (
    <div className="shell">
      <Sidebar current={route} />
      <div className="shell__main">
        <TopBar route={route} />
        <main className="shell__content">
          {route === "runs" && <RunsPage />}
          {route === "new-run" && <NewRunPage />}
          {route === "evidence" && <EvidencePage />}
          {route === "results" && <ResultsPage />}
          {route === "settings" && <SettingsPage />}
        </main>
      </div>
    </div>
  );
}
