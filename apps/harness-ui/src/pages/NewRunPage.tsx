export function NewRunPage(): JSX.Element {
  return (
    <section className="page">
      <div className="empty">
        <h2>Start with context</h2>
        <p>
          Provide a target URL and goal. The harness will generate a plan with
          Gemini, you review and approve it, then execution starts in the
          sandbox.
        </p>
        <p className="muted">Form and plan-review checkpoint arrive in STORY-H002.x.</p>
      </div>
    </section>
  );
}
