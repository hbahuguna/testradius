import { useEffect, useRef } from "react";
import type { MessageGroup } from "./types";
import ChatBubble from "./ChatBubble";

interface MessageListProps {
  groups: MessageGroup[];
  loading: boolean;
  onBack: () => void;
}

export default function MessageList({ groups, loading, onBack }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [groups.length, loading]);

  if (groups.length === 0 && !loading) {
    return (
      <div className="ml-empty">
        <p>Enter a URL to start testing</p>
        <p className="ml-empty-hint">The SDET agent will guide you through creating Playwright tests.</p>
      </div>
    );
  }

  return (
    <div className="ml-list">
      {groups.map((g, i) => (
        <ChatBubble key={i} group={g} onBack={i === groups.length - 1 ? onBack : undefined} />
      ))}
      {loading && (
        <div className="ml-typing">
          <span className="ml-typing-dot" />
          <span className="ml-typing-dot" />
          <span className="ml-typing-dot" />
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
