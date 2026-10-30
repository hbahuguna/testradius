export function RunsPage(): JSX.Element {
  return (
    <section className="page">
      <div className="empty">
        <h2>No runs yet</h2>
        <p>
          Runs created via the CLI or the New Run form will appear here with live
          status, current step, and links to evidence.
        </p>
        <pre className="code">python3.14 -m harness testradius run</pre>
      </div>
    </section>
  );
}
