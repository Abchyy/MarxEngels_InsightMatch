from marx_engels.retrieval_core.rrf import reciprocal_rank_fusion, stable_score_order


def test_rrf_rewards_documents_found_in_both_channels() -> None:
    scores = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], rank_constant=60)
    assert stable_score_order(scores)[0] == "b"


def test_rrf_rejects_non_positive_constant() -> None:
    try:
        reciprocal_rank_fusion([["a"]], rank_constant=0)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive rank constant was accepted")
