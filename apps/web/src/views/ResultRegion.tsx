import type { SearchMode, SearchResponse } from "../contracts";
import { ClaimResultGroups } from "./ClaimResultGroups";
import { ExactResultList, type ExactSort } from "./ExactResultList";
import { ThematicGroups } from "./ThematicGroups";
import { TimelineView } from "./TimelineView";

interface Props {
  response: SearchResponse;
  phase: "success" | "empty" | "partial";
  matchQuery: string;
  exactSort: ExactSort | null;
  onExactSortChange: (sort: ExactSort) => void;
  onSuggestModeSwitch?: (mode: SearchMode) => void;
  timelineShowSummaries?: boolean;
  thematicShowMachineLabels?: boolean;
}

export function ResultRegion({
  response,
  phase,
  matchQuery,
  exactSort,
  onExactSortChange,
  onSuggestModeSwitch,
  timelineShowSummaries,
  thematicShowMachineLabels,
}: Props) {
  const evidence = response.evidence ?? [];
  const isEmpty = phase === "empty" || (evidence.length === 0 && (response.groups?.length ?? 0) === 0);

  return (
    <div className="result-region">
      {response.mode === "exact" && (
        <ExactResultList
          evidence={isEmpty ? [] : evidence}
          matchQuery={matchQuery}
          sort={exactSort}
          onSortChange={onExactSortChange}
          onSuggestModeSwitch={onSuggestModeSwitch}
          insufficiency={response.insufficiency}
        />
      )}
      {response.mode === "claim" && <ClaimResultGroups response={response} />}
      {response.mode === "timeline" && (
        <TimelineView
          groups={response.groups}
          evidence={evidence}
          showSummaries={timelineShowSummaries}
        />
      )}
      {response.mode === "thematic" && (
        <ThematicGroups
          groups={response.groups}
          evidence={evidence}
          classificationNotice={response.classification_notice}
          showMachineLabels={thematicShowMachineLabels}
        />
      )}
    </div>
  );
}
