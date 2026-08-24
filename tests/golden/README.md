# Golden dataset

Official reviewed JSONL cases belong here during pipeline development:

- `exact_cases.jsonl`
- `claim_cases.jsonl`
- `timeline_cases.jsonl`
- `thematic_cases.jsonl`
- `evidence_gate_cases.jsonl`

Each line must be one JSON object with `case_id`, `query`, `mode`, `scope`,
`expected_evidence_ids`, `forbidden_evidence_ids`, `expected_labels`, `notes`,
`annotator`, `reviewer`, and `dataset_version`. `mode` and `scope` must match the
frozen V1 `SearchMode` / `SearchScope` contracts. Pipeline files
(`exact` / `claim` / `timeline` / `thematic`) require `case.mode` to match the
filename; `evidence_gate_cases.jsonl` may contain any legal `SearchMode`.
`annotator` and `reviewer` must be different people. Expected and forbidden
evidence IDs must not overlap. `expected_labels` keys and values must be
non-empty, and every label key must be an ID from `expected_evidence_ids` or
`forbidden_evidence_ids`. All cases must share one `dataset_version`.

`make test-regression` is fail-closed: missing files, structural errors, or zero
reviewed cases exit non-zero. An empty official dataset is not a passing
evaluation. Synthetic loader fixtures live under `tests/fixtures/golden/` and
are never counted as official golden data.

Do not add unlicensed corpus text, PDFs, or runtime databases to the public
repository. Add a case only after a human annotator and a human reviewer have
confirmed the evidence IDs.
