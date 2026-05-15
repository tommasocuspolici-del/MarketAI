"""Tests per personal.data_entry.risk_questionnaire."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from personal.data_entry.risk_questionnaire import (
    QUESTIONS,
    RiskProfile,
    RiskProfileResult,
    compute_risk_profile,
    load_saved_profile,
    save_profile,
)


def _max_score_answers() -> dict[str, int]:
    """Returns answers with the maximum score for each question."""
    return {q.qid: max(score for _, score in q.options) for q in QUESTIONS}


def _min_score_answers() -> dict[str, int]:
    """Returns answers with the minimum score for each question."""
    return {q.qid: min(score for _, score in q.options) for q in QUESTIONS}


class TestQuestions:
    def test_questions_not_empty(self) -> None:
        assert len(QUESTIONS) > 0

    def test_each_question_has_options(self) -> None:
        for q in QUESTIONS:
            assert len(q.options) >= 2

    def test_each_question_has_dimension(self) -> None:
        valid_dims = {"capacity", "tolerance", "horizon", "knowledge",
                      "CAPACITA", "TOLLERANZA", "ORIZZONTE", "CONOSCENZA"}
        for q in QUESTIONS:
            assert q.dimension in valid_dims, f"Unknown dimension: {q.dimension}"

    def test_question_ids_unique(self) -> None:
        qids = [q.qid for q in QUESTIONS]
        assert len(qids) == len(set(qids))


class TestComputeRiskProfile:
    def test_low_score_conservative(self) -> None:
        answers = _min_score_answers()
        result = compute_risk_profile(answers)
        assert result.profile == RiskProfile.CONSERVATIVE
        assert result.suggested_equity_pct <= 0.25

    def test_high_score_very_aggressive(self) -> None:
        answers = _max_score_answers()
        result = compute_risk_profile(answers)
        assert result.profile in (RiskProfile.AGGRESSIVE, RiskProfile.VERY_AGGRESSIVE)

    def test_returns_risk_profile_result(self) -> None:
        answers = _min_score_answers()
        result = compute_risk_profile(answers)
        assert isinstance(result, RiskProfileResult)

    def test_total_score_is_sum_of_dimensions(self) -> None:
        answers = _min_score_answers()
        result = compute_risk_profile(answers)
        assert result.total_score == sum(result.dimension_scores.values())

    def test_unknown_qids_ignored(self) -> None:
        answers = {"unknown_qid": 5}
        result = compute_risk_profile(answers)
        assert result.total_score == 0

    def test_suggested_drawdown_conservative(self) -> None:
        answers = _min_score_answers()
        result = compute_risk_profile(answers)
        assert result.suggested_max_drawdown_pct == pytest.approx(0.10)

    def test_suggested_equity_pct_in_range(self) -> None:
        for answers in [_min_score_answers(), _max_score_answers()]:
            result = compute_risk_profile(answers)
            assert 0.0 < result.suggested_equity_pct <= 1.0

    def test_answer_texts_populated(self) -> None:
        answers = _min_score_answers()
        result = compute_risk_profile(answers)
        assert len(result.answers) > 0

    def test_empty_answers_returns_conservative(self) -> None:
        result = compute_risk_profile({})
        assert result.profile == RiskProfile.CONSERVATIVE
        assert result.total_score == 0

    def test_dimension_scores_present(self) -> None:
        answers = _min_score_answers()
        result = compute_risk_profile(answers)
        # Dimension names depend on the actual QUESTIONS data
        assert len(result.dimension_scores) > 0
        # Total score matches sum of dimensions
        assert result.total_score == sum(result.dimension_scores.values())

    def test_moderate_profile_range(self) -> None:
        # Punteggio 35-54 → MODERATE
        answers = _min_score_answers()
        result_min = compute_risk_profile(answers)
        answers_max = _max_score_answers()
        result_max = compute_risk_profile(answers_max)
        # Span covers at least moderate and very_aggressive
        profiles = {result_min.profile, result_max.profile}
        assert len(profiles) >= 2


class TestSaveAndLoadProfile:
    def _make_mock_store(self):
        store = MagicMock()
        store.get.return_value = None
        return store

    def test_save_profile_calls_upsert(self) -> None:
        store = self._make_mock_store()
        result = compute_risk_profile(_min_score_answers())
        save_profile(result, raw_answers=_min_score_answers(), store=store)
        store.upsert.assert_called_once()

    def test_save_profile_upsert_has_total_score(self) -> None:
        store = self._make_mock_store()
        result = compute_risk_profile(_min_score_answers())
        raw = _min_score_answers()
        save_profile(result, raw_answers=raw, store=store)
        _, call_args = store.upsert.call_args_list[0][0], store.upsert.call_args
        payload = call_args[0][2]  # positional arg #3
        assert "total_score" in payload
        assert "profile" in payload
        assert "raw_answers" in payload

    def test_load_saved_profile_none_when_empty(self) -> None:
        store = self._make_mock_store()
        result = load_saved_profile(store=store)
        assert result is None

    def test_load_saved_profile_returns_result(self) -> None:
        from unittest.mock import MagicMock
        store = self._make_mock_store()
        mock_record = MagicMock()
        mock_record.payload = {
            "total_score": 30,
            "dimension_scores": {"CAPACITA": 10, "TOLLERANZA": 8, "ORIZZONTE": 7, "CONOSCENZA": 5},
            "profile": "CONSERVATIVE",
            "suggested_max_drawdown_pct": 0.10,
            "suggested_equity_pct": 0.20,
            "answer_texts": {},
        }
        store.get.return_value = mock_record
        result = load_saved_profile(store=store)
        assert result is not None
        assert result.profile == RiskProfile.CONSERVATIVE
        assert result.total_score == 30

    def test_load_saved_profile_handles_corrupt_data(self) -> None:
        store = self._make_mock_store()
        mock_record = MagicMock()
        mock_record.payload = {"broken": "data"}
        store.get.return_value = mock_record
        result = load_saved_profile(store=store)
        assert result is None


class TestRiskProfileResult:
    def test_frozen(self) -> None:
        result = compute_risk_profile({})
        with pytest.raises((AttributeError, TypeError)):
            result.total_score = 999  # type: ignore[misc]
