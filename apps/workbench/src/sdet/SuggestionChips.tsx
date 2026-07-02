interface SuggestionChipsProps {
  chips: { id: string; label: string }[];
  onChipClick: (label: string) => void;
  disabled: boolean;
}

export default function SuggestionChips({ chips, onChipClick, disabled }: SuggestionChipsProps) {
  if (chips.length === 0) return null;
  return (
    <div className="sc-chips">
      {chips.map((chip) => (
        <button
          key={chip.id}
          className="sc-chip-btn"
          onClick={() => onChipClick(chip.label)}
          disabled={disabled}
        >
          {chip.label}
        </button>
      ))}
    </div>
  );
}
