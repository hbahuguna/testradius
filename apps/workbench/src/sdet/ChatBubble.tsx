import { useState } from "react";
import type { MessageGroup } from "./types";

interface ChatBubbleProps {
  group: MessageGroup;
  onBack?: () => void;
}

export default function ChatBubble({ group, onBack }: ChatBubbleProps) {
  const [codeExpanded, setCodeExpanded] = useState(false);
  const isNode9 = group.nodeId === "N9";

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

      {onBack && group.isLast && (
        <button className="cb-back" onClick={onBack} title="Undo this step">&larr; Back</button>
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
