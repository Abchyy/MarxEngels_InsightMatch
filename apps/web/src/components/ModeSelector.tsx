import type { SearchMode } from "../contracts";

export const MODE_LABELS: Record<SearchMode, string> = {
  exact: "精确检索",
  claim: "观点语义检索",
  timeline: "按时间呈现",
  thematic: "按思想结构呈现",
};

const MODES: Array<{ mode: SearchMode; description: string }> = [
  { mode: "exact", description: "只返回逐字出现该词的原文段落" },
  { mode: "claim", description: "寻找支撑、回应或反驳观点的材料" },
  { mode: "timeline", description: "相关证据从早年到晚年排列" },
  { mode: "thematic", description: "相关证据按语义相近程度归类" },
];

interface Props {
  value: SearchMode | null;
  onChange: (mode: SearchMode) => void;
  /** 非空时仅这些模式可选；用于 awaiting_mode_selection 收紧选择范围。 */
  allowedModes?: readonly SearchMode[] | null;
  disabled?: boolean;
  /**
   * 当前运行环境尚未接入的模式（普通环境为 claim/timeline/thematic）。
   * 仅展示可用性徽章，不改变可选性：用户选择后由后端返回
   * PIPELINE_NOT_IMPLEMENTED 说明，awaiting 流程也不会因此死锁。
   */
  unavailableModes?: readonly SearchMode[];
}

export function ModeSelector({
  value,
  onChange,
  allowedModes = null,
  disabled = false,
  unavailableModes = [],
}: Props) {
  const showAvailability = unavailableModes.length > 0;
  return (
    <fieldset className="mode-selector">
      <legend>检索方式</legend>
      {MODES.map((item) => {
        const modeDisabled = disabled || (allowedModes !== null && !allowedModes.includes(item.mode));
        const unavailable = unavailableModes.includes(item.mode);
        // 以空格分隔拼接，保证 selected/disabled 可同时命中对应 CSS 规则。
        const className = [
          value === item.mode ? "selected" : "",
          modeDisabled ? "disabled" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <label key={item.mode} className={className || undefined}>
            <input
              type="radio"
              name="mode"
              value={item.mode}
              checked={value === item.mode}
              disabled={modeDisabled}
              onChange={() => onChange(item.mode)}
            />
            <span className="mode-option">
              <strong className="mode-option__name">
                {MODE_LABELS[item.mode]}
                {showAvailability && (
                  <span
                    className={`mode-badge ${unavailable ? "mode-badge--unavailable" : "mode-badge--available"}`}
                  >
                    {unavailable ? "尚未实现" : "当前可用"}
                  </span>
                )}
              </strong>
              <small>{item.description}</small>
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
