import type { SearchMode, SearchResponse } from "../contracts";
import { SearchOverview } from "../components/SearchOverview";
import { ResultRegion } from "./ResultRegion";
import type { ExactSort } from "./ExactResultList";

interface Props {
  response: SearchResponse;
  selectedMode: SearchMode;
  phase: "success" | "empty" | "partial";
  matchQuery: string;
  exactSort: ExactSort | null;
  onExactSortChange: (sort: ExactSort) => void;
  onSuggestModeSwitch?: (mode: SearchMode) => void;
  timelineShowSummaries?: boolean;
  thematicShowMachineLabels?: boolean;
}

/** 完整结果页：概览 + 模式视图（用于 App 与组合测试）。 */
export function ResultPage({
  response,
  selectedMode,
  phase,
  matchQuery,
  exactSort,
  onExactSortChange,
  onSuggestModeSwitch,
  timelineShowSummaries,
  thematicShowMachineLabels,
}: Props) {
  return (
    <>
      <SearchOverview response={response} selectedMode={selectedMode} phase={phase} />
      <ResultRegion
        response={response}
        phase={phase}
        matchQuery={matchQuery}
        exactSort={exactSort}
        onExactSortChange={onExactSortChange}
        onSuggestModeSwitch={onSuggestModeSwitch}
        timelineShowSummaries={timelineShowSummaries}
        thematicShowMachineLabels={thematicShowMachineLabels}
      />
    </>
  );
}
