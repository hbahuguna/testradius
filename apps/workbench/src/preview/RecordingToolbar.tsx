interface RecordingToolbarProps {
  recordingMode: boolean;
  onToggle: () => void;
}

export default function RecordingToolbar({ recordingMode, onToggle }: RecordingToolbarProps) {
  return (
    <div className="rt-bar">
      <span className="rt-label">Mode</span>
      <button
        className={`rt-toggle ${!recordingMode ? "rt-active-select" : ""}`}
        onClick={() => recordingMode && onToggle()}
      >
        Select
      </button>
      <button
        className={`rt-toggle ${recordingMode ? "rt-active-record" : ""}`}
        onClick={() => !recordingMode && onToggle()}
      >
        Record
      </button>
    </div>
  );
}
