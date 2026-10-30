export function SettingsPage(): JSX.Element {
  return (
    <section className="page">
      <div className="empty">
        <h2>Settings</h2>
        <p>
          Model selection (Gemini), sandbox mode, policy guards, and checkpoint
          defaults will be configurable here.
        </p>
        <p className="muted">
          Secrets stay in environment variables (e.g. <code>GEMINI_API_KEY</code>) — never in the UI or repo.
        </p>
      </div>
    </section>
  );
}
