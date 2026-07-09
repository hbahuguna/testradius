import { useState, useCallback } from "react";

interface JiraIssue {
  key: string;
  summary: string;
  status: string;
  priority: string | null;
  issuetype: string | null;
}

interface JiraIssueDetail extends JiraIssue {
  description: string;
  labels: string[];
  assignee: string | null;
  comments: { author: string; body: string; created: string }[];
}

interface TicketIntegrationProps {
  apiBase: string;
  sessionId: string;
  onSelectTicket: (ticketContext: string) => void;
}

export default function TicketIntegration({ apiBase, sessionId, onSelectTicket }: TicketIntegrationProps) {
  const [instanceUrl, setInstanceUrl] = useState(() => localStorage.getItem("ti_jira_url") || "");
  const [email, setEmail] = useState(() => localStorage.getItem("ti_jira_email") || "");
  const [apiToken, setApiToken] = useState(() => localStorage.getItem("ti_jira_token") || "");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [issues, setIssues] = useState<JiraIssue[]>([]);
  const [selectedIssue, setSelectedIssue] = useState<JiraIssueDetail | null>(null);
  const [searching, setSearching] = useState(false);
  const [loadingIssue, setLoadingIssue] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const handleConnect = useCallback(async () => {
    setConnecting(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/workbench/ticket/jira/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, instance_url: instanceUrl, email, api_token: apiToken }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Connection failed");
      }
      localStorage.setItem("ti_jira_url", instanceUrl);
      localStorage.setItem("ti_jira_email", email);
      localStorage.setItem("ti_jira_token", apiToken);
      setConnected(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setConnecting(false);
    }
  }, [apiBase, sessionId, instanceUrl, email, apiToken]);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/workbench/ticket/jira/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, query: searchQuery.trim() }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Search failed");
      }
      const data = await res.json();
      setIssues(data.issues || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSearching(false);
    }
  }, [apiBase, sessionId, searchQuery]);

  const handleSelectIssue = useCallback(async (issueKey: string) => {
    setLoadingIssue(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/workbench/ticket/jira/issue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, issue_key: issueKey }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to fetch issue");
      }
      const data = await res.json();
      setSelectedIssue(data.issue);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoadingIssue(false);
    }
  }, [apiBase, sessionId]);

  const handleUseTicket = useCallback(() => {
    if (!selectedIssue) return;
    const parts: string[] = [];
    parts.push(`JIRA/${selectedIssue.key}: ${selectedIssue.summary}`);
    parts.push(`Status: ${selectedIssue.status} | Priority: ${selectedIssue.priority || "N/A"} | Type: ${selectedIssue.issuetype || "N/A"}`);
    if (selectedIssue.labels?.length) parts.push(`Labels: ${selectedIssue.labels.join(", ")}`);
    parts.push("");
    parts.push("--- Description ---");
    parts.push(selectedIssue.description || "(no description)");
    if (selectedIssue.comments?.length) {
      parts.push("");
      parts.push("--- Comments ---");
      for (const c of selectedIssue.comments) {
        parts.push(`[${c.author}] ${c.body}`);
      }
    }
    const separator = "-".repeat(40);
    onSelectTicket(`\n${separator}\nJira Ticket Context:\n${parts.join("\n")}\n${separator}\n`);
    setExpanded(false);
  }, [selectedIssue, onSelectTicket]);

  const handleDisconnect = useCallback(async () => {
    try {
      await fetch(`${apiBase}/api/workbench/ticket/jira/disconnect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, issue_key: "" }),
      });
    } catch { }
    setConnected(false);
    setIssues([]);
    setSelectedIssue(null);
  }, [apiBase, sessionId]);

  if (!expanded && !connected) {
    return (
      <div className="ti-bar">
        <button className="ti-toggle" onClick={() => setExpanded(true)}>
          + Jira Ticket
        </button>
      </div>
    );
  }

  if (!expanded && connected) {
    return (
      <div className="ti-bar">
        <span className="ti-badge ti-badge-connected">Jira Connected</span>
        <button className="ti-toggle" onClick={() => setExpanded(true)}>
          {selectedIssue ? selectedIssue.key : "Search Tickets"}
        </button>
      </div>
    );
  }

  return (
    <div className="ti-panel">
      <div className="ti-header">
        <span className="ti-title">Jira Ticket Integration</span>
        <button className="ti-close" onClick={() => setExpanded(false)}>&times;</button>
      </div>

      {!connected ? (
        <div className="ti-config">
          <input className="ti-input" type="text" placeholder="Instance URL (e.g. https://your-domain.atlassian.net)" value={instanceUrl} onChange={(e) => setInstanceUrl(e.target.value)} />
          <input className="ti-input" type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input className="ti-input" type="password" placeholder="API Token" value={apiToken} onChange={(e) => setApiToken(e.target.value)} />
          <button className="ti-btn ti-btn-primary" onClick={handleConnect} disabled={connecting || !instanceUrl || !email || !apiToken}>
            {connecting ? "Connecting..." : "Connect"}
          </button>
        </div>
      ) : (
        <div className="ti-search-section">
          <div className="ti-search-row">
            <input className="ti-input ti-search-input" type="text" placeholder="Search tickets by keyword..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleSearch()} />
            <button className="ti-btn ti-btn-primary" onClick={handleSearch} disabled={searching || !searchQuery.trim()}>
              {searching ? "..." : "Search"}
            </button>
            <button className="ti-btn ti-btn-disconnect" onClick={handleDisconnect} title="Disconnect Jira">X</button>
          </div>

          {selectedIssue && (
            <div className="ti-detail">
              <div className="ti-detail-header">
                <strong>{selectedIssue.key}</strong>
                <span className={`ti-status ti-status-${selectedIssue.status.toLowerCase()}`}>{selectedIssue.status}</span>
              </div>
              <p className="ti-detail-summary">{selectedIssue.summary}</p>
              {selectedIssue.description && (
                <div className="ti-detail-desc">
                  <div className="ti-detail-label">Description</div>
                  <p>{selectedIssue.description}</p>
                </div>
              )}
              {selectedIssue.comments.length > 0 && (
                <div className="ti-detail-section">
                  <div className="ti-detail-label">Comments ({selectedIssue.comments.length})</div>
                  {selectedIssue.comments.slice(0, 3).map((c, i) => (
                    <div key={i} className="ti-comment">
                      <span className="ti-comment-author">{c.author}:</span>
                      <span className="ti-comment-body">{c.body.slice(0, 200)}{c.body.length > 200 ? "..." : ""}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="ti-detail-actions">
                <button className="ti-btn ti-btn-primary" onClick={handleUseTicket}>
                  Use This Ticket
                </button>
                <button className="ti-btn ti-btn-secondary" onClick={() => setSelectedIssue(null)}>
                  Back to Results
                </button>
              </div>
            </div>
          )}

          {!selectedIssue && issues.length > 0 && (
            <div className="ti-results">
              {issues.map((issue) => (
                <button key={issue.key} className="ti-result-item" onClick={() => handleSelectIssue(issue.key)}>
                  <div className="ti-result-header">
                    <span className="ti-result-key">{issue.key}</span>
                    <span className="ti-result-type">{issue.issuetype}</span>
                    <span className={`ti-status ti-status-${issue.status.toLowerCase()}`}>{issue.status}</span>
                  </div>
                  <span className="ti-result-summary">{issue.summary}</span>
                </button>
              ))}
            </div>
          )}

          {!selectedIssue && issues.length === 0 && !searching && (
            <p className="ti-hint">Search for Jira tickets to use as test context.</p>
          )}

          {loadingIssue && <p className="ti-hint">Loading ticket details...</p>}
        </div>
      )}

      {error && <div className="ti-error">{error}</div>}
    </div>
  );
}
