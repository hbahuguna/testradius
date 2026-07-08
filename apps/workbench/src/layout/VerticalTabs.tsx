interface TabDef {
  id: string;
  label: string;
  icon: string;
}

interface VerticalTabsProps {
  tabs: TabDef[];
  activeTab: string;
  onTabChange: (id: string) => void;
}

export type { TabDef };

export default function VerticalTabs({ tabs, activeTab, onTabChange }: VerticalTabsProps) {
  return (
    <nav className="vt-bar">
      {tabs.map((t) => (
        <button
          key={t.id}
          className={`vt-tab ${t.id === activeTab ? "vt-active" : ""}`}
          onClick={() => onTabChange(t.id)}
          title={t.label}
        >
          <span className="vt-icon" dangerouslySetInnerHTML={{ __html: t.icon }} />
          <span className="vt-label">{t.label}</span>
        </button>
      ))}
    </nav>
  );
}
