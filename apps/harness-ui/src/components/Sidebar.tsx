import type { Route } from "../App";

const NAV_ITEMS: Array<{ route: Route; label: string; hint: string }> = [
  { route: "runs", label: "Runs", hint: "History & live status" },
  { route: "new-run", label: "New Run", hint: "Goal → plan → approve" },
  { route: "evidence", label: "Evidence", hint: "Screenshots, video, traces" },
  { route: "results", label: "Results", hint: "Assertions & reports" },
  { route: "settings", label: "Settings", hint: "Model, policy, sandbox" },
];

export function Sidebar({ current }: { current: Route }): JSX.Element {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__logo">TR</span>
        <div>
          <p className="sidebar__title">TestRadius</p>
          <p className="sidebar__subtitle">Harness</p>
        </div>
      </div>
      <nav className="sidebar__nav">
        {NAV_ITEMS.map((item) => (
          <a
            key={item.route}
            href={`#/${item.route}`}
            className={`sidebar__item ${current === item.route ? "sidebar__item--active" : ""}`}
          >
            <span className="sidebar__item-label">{item.label}</span>
            <span className="sidebar__item-hint">{item.hint}</span>
          </a>
        ))}
      </nav>
      <footer className="sidebar__footer">
        <span className="pill pill--ok">CLI-first</span>
        <span className="pill">Sandbox</span>
      </footer>
    </aside>
  );
}
