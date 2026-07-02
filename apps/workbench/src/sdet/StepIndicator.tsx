import { getPhaseLabel } from "./types";

interface StepIndicatorProps {
  currentNodeId: string;
  visitedCount: number;
  totalSteps: number;
}

export default function StepIndicator({ currentNodeId, visitedCount, totalSteps }: StepIndicatorProps) {
  const phase = getPhaseLabel(currentNodeId);
  const pct = Math.min(Math.round((visitedCount / Math.max(totalSteps, 1)) * 100), 100);

  return (
    <div className="si-bar">
      <div className="si-header">
        <span className="si-phase">{phase}</span>
        <span className="si-count">{Math.min(visitedCount + 1, totalSteps)} / {totalSteps}</span>
      </div>
      <div className="si-track">
        <div className="si-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
