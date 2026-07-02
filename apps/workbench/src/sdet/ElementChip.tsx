import type { ContextElement } from "./types";

const TAG_COLORS: Record<string, string> = {
  button: "#4a8a4a",
  input: "#4a6a8a",
  select: "#8a7a4a",
  textarea: "#4a7a6a",
  a: "#4a4a8a",
  img: "#7a4a8a",
  label: "#6a5a4a",
  form: "#5a6a4a",
};

interface ElementChipProps {
  element: ContextElement;
  onRemove: (id: string) => void;
}

export default function ElementChip({ element, onRemove }: ElementChipProps) {
  const color = TAG_COLORS[element.tag] || "#5a5a7a";
  return (
    <span className="ec-chip" title={element.cssPath}>
      <span className="ec-tag" style={{ background: color }}>{element.tag}</span>
      <span className="ec-text">{element.text.slice(0, 20) || element.cssPath.slice(0, 20)}</span>
      <button className="ec-remove" onClick={() => onRemove(element.id)}>&times;</button>
    </span>
  );
}
