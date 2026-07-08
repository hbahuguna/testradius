import { useState } from "react";
import type { MessageGroup } from "./types";

interface ChatBubbleProps {
  group: MessageGroup;
  onBack?: () => void;
  onSendMessage?: (text: string) => void;
}

export default function ChatBubble({ group, onBack, onSendMessage }: ChatBubbleProps) {
  const [codeExpanded, setCodeExpanded] = useState(false);
  const isNode9 = group.nodeId === "N9";
  const isLast = group.isLast;

  return (
    <div className={`cb-group ${group.isLast ? "cb-last" : ""}`}>
      <div className="cb-bubble cb-agent">
        {isNode9 && (
          <div className="cb-phase-cue">Element Selection</div>
        )}
        <div className="cb-content" dir="auto">
          {renderContent(group.agentMessage)}
        </div>
        {isNode9 && (
          <div className="cb-preview-hint">
            Click on the elements in the preview panel to the left to select them.
            Selected elements appear as chips below. When done, click the chip below or type a message.
          </div>
        )}
        {group.code && (
          <div className="cb-code">
            <div className="cb-code-header">
              <span className="cb-code-label">Playwright Test</span>
              <div className="cb-code-actions">
                <button className="cb-btn" onClick={() => navigator.clipboard.writeText(group.code!)}>Copy</button>
                <button className="cb-btn" onClick={() => setCodeExpanded(!codeExpanded)}>
                  {codeExpanded ? "Collapse" : "Show all"}
                </button>
              </div>
            </div>
            <pre className={`cb-pre ${codeExpanded ? "" : "cb-collapsed"}`}><code>{group.code}</code></pre>
          </div>
        )}
      </div>

      {group.userMessage && (
        <div className="cb-bubble cb-user">
          <div className="cb-content">{group.userMessage}</div>
        </div>
      )}

      {group.isLast && onBack && (group.nodeId === "N10" || group.nodeId === "N11" || group.nodeId === "N12") ? (
        <div className="cb-phase-buttons">
          {onSendMessage && <button className="cb-btn cb-btn-primary cb-phase-btn" onClick={() => onSendMessage("LGTM")}>LGTM</button>}
          <button className="cb-btn cb-btn-secondary cb-phase-btn" onClick={onBack}>&larr; Back</button>
        </div>
      ) : onBack && group.isLast && (
        <button className="cb-back" onClick={onBack} title="Undo this step">&larr; Back</button>
      )}

      {onSendMessage && isLast && group.nodeId === "N14" && (
        <div className="cb-phase-buttons">
          <button className="cb-btn cb-btn-primary" onClick={() => onSendMessage("Generate")}>Generate/Modify Test</button>
        </div>
      )}
    </div>
  );
}

function renderContent(text: string): React.ReactNode {
  const parts = text.split(/(```[\s\S]*?```)/g);
  if (parts.length === 1) {
    return <p className="cb-text">{text}</p>;
  }
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("```")) {
          const code = part.replace(/```[\w]*\n?/, "").replace(/```$/, "");
          return (
            <pre key={i} className="cb-inline-code"><code>{code}</code></pre>
          );
        }
        return part ? <p key={i} className="cb-text">{part}</p> : null;
      })}
    </>
  );
}
