import type { RecordedAction } from "../sdet/types";

interface ActionSequenceListProps {
  actions: RecordedAction[];
  onDelete: (index: number) => void;
  onMoveUp: (index: number) => void;
  onMoveDown: (index: number) => void;
}

const ACTION_COLORS: Record<string, string> = {
  click: "#ff8844",
  fill: "#44aaff",
  select: "#cc66cc",
  check: "#66cc66",
};

export default function ActionSequenceList({ actions, onDelete, onMoveUp, onMoveDown }: ActionSequenceListProps) {
  if (actions.length === 0) return null;

  return (
    <div className="as-panel">
      <div className="as-header">
        <span className="as-title">Actions ({actions.length})</span>
      </div>
      <div className="as-table-wrap">
        <table className="as-table">
          <thead>
            <tr>
              <th className="as-col-step">#</th>
              <th className="as-col-action">Action</th>
              <th className="as-col-target">Target</th>
              <th className="as-col-move"></th>
              <th className="as-col-del"></th>
            </tr>
          </thead>
          <tbody>
            {actions.map((a, i) => (
              <tr key={i} className="as-row">
                <td className="as-col-step">{i + 1}</td>
                <td className="as-col-action">
                  <span
                    className="as-action-badge"
                    style={{
                      background: `${ACTION_COLORS[a.action_type] || "#8888aa"}22`,
                      color: ACTION_COLORS[a.action_type] || "#8888aa",
                      borderColor: `${ACTION_COLORS[a.action_type] || "#8888aa"}44`,
                    }}
                  >
                    {a.action_type}
                  </span>
                </td>
                <td className="as-col-target">
                  <span className="as-tag">&lt;{a.tag}&gt;</span>
                  {a.text && <span className="as-text">{a.text.slice(0, 40)}</span>}
                </td>
                <td className="as-col-move">
                  <div className="as-move-group">
                    <button
                      className="as-move-btn"
                      onClick={() => onMoveUp(i)}
                      disabled={i === 0}
                      title="Move up"
                    >&#9650;</button>
                    <button
                      className="as-move-btn"
                      onClick={() => onMoveDown(i)}
                      disabled={i === actions.length - 1}
                      title="Move down"
                    >&#9660;</button>
                  </div>
                </td>
                <td className="as-col-del">
                  <button className="as-del-btn" onClick={() => onDelete(i)} title="Remove step">&times;</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
