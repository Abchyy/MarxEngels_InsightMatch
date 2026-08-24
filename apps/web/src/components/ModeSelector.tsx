import type { SearchMode } from "../contracts";

const MODES: Array<{ mode: SearchMode; label: string; description: string }> = [
  { mode: "exact", label: "精确检索", description: "只返回逐字出现该词的原文段落" },
  { mode: "claim", label: "观点语义检索", description: "寻找支撑、回应或反驳观点的材料" },
  { mode: "timeline", label: "按时间呈现", description: "相关证据从早年到晚年排列" },
  { mode: "thematic", label: "按思想结构呈现", description: "相关证据按语义相近程度归类" },
];

interface Props {
  value: SearchMode;
  onChange: (mode: SearchMode) => void;
}

export function ModeSelector({ value, onChange }: Props) {
  return (
    <fieldset className="mode-selector">
      <legend>检索方式</legend>
      {MODES.map((item) => (
        <label key={item.mode} className={value === item.mode ? "selected" : ""}>
          <input
            type="radio"
            name="mode"
            value={item.mode}
            checked={value === item.mode}
            onChange={() => onChange(item.mode)}
          />
          <span>
            <strong>{item.label}</strong>
            <small>{item.description}</small>
          </span>
        </label>
      ))}
    </fieldset>
  );
}
