"""Tests per ConsensusLoader, SurpriseAggregatorV2, SurpriseAccuracyTracker.

Roadmap v3.0 — Settimana 6.

Tutti i test usano DuckDB in-memory + YAML mock — nessuna rete reale.
Feature flags mockati per isolare i test dalla configurazione di produzione.
"""
from __future__ import annotations

import textwrap
from contextlib import contextmanager
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import duckdb
import numpy as np
import pandas as pd
import pytest


# ─── Schema in-memory ────────────────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS consensus_estimates (
    estimate_id    VARCHAR NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    indicator_code VARCHAR NOT NULL,
    release_date   DATE NOT NULL,
    consensus_value DOUBLE,
    source         VARCHAR NOT NULL,
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- ANTI-REGRESSIONE: PK composita uguale a migration 015 (non estimate_id)
    -- Se si usa estimate_id come PK, INSERT OR REPLACE non funziona (UUID diversi ogni insert)
    PRIMARY KEY (indicator_code, release_date, source)
);
CREATE TABLE IF NOT EXISTS economic_consensus (
    release_date      DATE NOT NULL,
    indicator_code    VARCHAR NOT NULL,
    sector            VARCHAR NOT NULL,
    consensus_value   DOUBLE,
    actual_value      DOUBLE,
    prior_value       DOUBLE,
    surprise_raw      DOUBLE,
    surprise_std      DOUBLE,
    surprise_z        DOUBLE,
    source            VARCHAR,
    PRIMARY KEY (release_date, indicator_code)
);
CREATE TABLE IF NOT EXISTS surprise_accuracy_log (
    indicator_code VARCHAR NOT NULL,
    release_date   DATE NOT NULL,
    predicted_beat BOOLEAN,
    surprise_z     DOUBLE,
    recorded_at    TIMESTAMPTZ,
    outcome_beat   BOOLEAN,
    PRIMARY KEY (indicator_code, release_date)
);
CREATE TABLE IF NOT EXISTS sector_surprise_index (
    snapshot_date  DATE NOT NULL,
    sector         VARCHAR NOT NULL,
    surprise_index DOUBLE,
    momentum_1m    DOUBLE,
    momentum_3m    DOUBLE,
    regime         VARCHAR,
    beat_count     INTEGER,
    miss_count     INTEGER,
    data_points    INTEGER,
    PRIMARY KEY (snapshot_date, sector)
);
CREATE TABLE IF NOT EXISTS surprise_signal (
    generated_at   TIMESTAMPTZ NOT NULL,
    signal_value   DOUBLE,
    dominant_sector VARCHAR,
    beat_count     INTEGER,
    miss_count     INTEGER,
    PRIMARY KEY (generated_at)
);
"""


@pytest.fixture
def in_memory_client():
    """DuckDB client in-memory con schema completo surprise engine."""
    conn = duckdb.connect(":memory:")
    for stmt in _CREATE_TABLES.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    client.transaction = _transaction
    return client


@pytest.fixture
def sample_consensus_df() -> pd.DataFrame:
    """DataFrame consensus pronto per SurpriseCalculator."""
    return pd.DataFrame({
        "release_date":   [date(2026, 5, 2), date(2026, 5, 9), date(2026, 5, 16)],
        "indicator_code": ["NFP", "INITIAL_CLAIMS", "CPI_YOY"],
        "sector":         ["labour", "labour", "inflation"],
        "consensus":      [185.0, 225.0, 3.4],
        "actual":         [203.0, 218.0, 3.2],
        "prior":          [177.0, 231.0, 3.5],
    })


# ─── Mock YAML per ConsensusLoader ───────────────────────────────────────────

_MOCK_YAML_CONTENT = textwrap.dedent("""
estimates:
  - code: NFP
    date: "2026-05-02"
    consensus: 185000
  - code: INITIAL_CLAIMS
    date: "2026-05-09"
    consensus: 225
  - code: CPI_YOY
    date: "2026-05-16"
    consensus: 3.4
  - code: BADENTRY
    date: "not-a-date"
    consensus: 99
""")


def _make_consensus_loader(client):
    """Crea ConsensusLoader con feature flag mockato."""
    with patch(
        "engine.analytics.surprise_engine.consensus_loader.is_enabled",
        return_value=True,
    ):
        from engine.analytics.surprise_engine.consensus_loader import ConsensusLoader
        loader = ConsensusLoader(client=client)
        return loader


# ─── Test: ConsensusLoader.load_yaml ─────────────────────────────────────────

class TestConsensusLoaderYAML:
    """Tests per load_yaml() con YAML mock su file system."""

    def test_load_yaml_parses_valid_entries(self, tmp_path, in_memory_client) -> None:
        """Entries valide vengono caricate correttamente."""
        yf = tmp_path / "consensus.yaml"
        yf.write_text(_MOCK_YAML_CONTENT)
        loader = _make_consensus_loader(in_memory_client)
        batch  = loader.load_yaml(yaml_path=yf)
        # 3 valide (NFP, CLAIMS, CPI) + 1 invalida (BADENTRY con data errata)
        assert len(batch.df) == 3
        assert batch.source == "yaml_manual"

    def test_load_yaml_skips_bad_date(self, tmp_path, in_memory_client) -> None:
        """Entry con data non parsabile viene scartata senza eccezione."""
        yf = tmp_path / "consensus.yaml"
        yf.write_text(_MOCK_YAML_CONTENT)
        loader = _make_consensus_loader(in_memory_client)
        batch  = loader.load_yaml(yaml_path=yf)
        codes  = batch.df["indicator_code"].tolist()
        assert "BADENTRY" not in codes

    def test_load_yaml_missing_file_raises(self, in_memory_client) -> None:
        """File mancante → ConfigurationError."""
        from shared.exceptions import ConfigurationError
        loader = _make_consensus_loader(in_memory_client)
        with pytest.raises(ConfigurationError):
            loader.load_yaml(yaml_path=Path("/nonexistent/path.yaml"))

    def test_load_yaml_consensus_values_are_float64(self, tmp_path, in_memory_client) -> None:
        """I valori consensus sono numpy float64 (Regola 8)."""
        yf = tmp_path / "c.yaml"
        yf.write_text(_MOCK_YAML_CONTENT)
        loader = _make_consensus_loader(in_memory_client)
        batch  = loader.load_yaml(yaml_path=yf)
        assert batch.df["consensus_value"].dtype == np.float64

    def test_load_yaml_empty_file_returns_empty_batch(self, tmp_path, in_memory_client) -> None:
        yf = tmp_path / "c.yaml"
        yf.write_text("estimates: []\n")
        loader = _make_consensus_loader(in_memory_client)
        batch  = loader.load_yaml(yaml_path=yf)
        assert batch.df.empty


# ─── Test: ConsensusLoader.save ──────────────────────────────────────────────

class TestConsensusLoaderSave:
    """Tests per save() in DuckDB in-memory."""

    def test_save_returns_row_count(self, tmp_path, in_memory_client) -> None:
        yf = tmp_path / "c.yaml"
        yf.write_text(_MOCK_YAML_CONTENT)
        loader = _make_consensus_loader(in_memory_client)
        batch  = loader.load_yaml(yaml_path=yf)
        n      = loader.save(batch)
        assert n == len(batch.df)

    def test_save_empty_batch_returns_zero(self, in_memory_client) -> None:
        from engine.analytics.surprise_engine.consensus_loader import ConsensusBatch
        loader = _make_consensus_loader(in_memory_client)
        empty  = ConsensusBatch(pd.DataFrame(), source="yaml_manual", loaded_at=datetime.now(UTC))
        assert loader.save(empty) == 0

    def test_save_idempotent_upsert(self, tmp_path, in_memory_client) -> None:
        """Salva due volte lo stesso batch → no duplicati (OR REPLACE)."""
        yf = tmp_path / "c.yaml"
        yf.write_text(_MOCK_YAML_CONTENT)
        loader = _make_consensus_loader(in_memory_client)
        batch  = loader.load_yaml(yaml_path=yf)
        loader.save(batch)
        loader.save(batch)
        with in_memory_client.transaction() as conn:
            count = conn.execute("SELECT COUNT(*) FROM consensus_estimates").fetchone()[0]
        assert count == len(batch.df)


# ─── Test: feature flag ──────────────────────────────────────────────────────

def test_consensus_loader_flag_disabled_raises() -> None:
    """ConsensusLoader lancia FeatureDisabledError se flag è off."""
    from shared.exceptions import FeatureDisabledError
    with patch(
        "engine.analytics.surprise_engine.consensus_loader.is_enabled",
        return_value=False,
    ):
        from engine.analytics.surprise_engine.consensus_loader import ConsensusLoader
        with pytest.raises(FeatureDisabledError):
            ConsensusLoader()


def test_surprise_aggregator_v2_flag_disabled_raises() -> None:
    """SurpriseAggregatorV2 lancia FeatureDisabledError se flag è off."""
    from shared.exceptions import FeatureDisabledError
    with patch(
        "engine.analytics.surprise_engine.surprise_aggregator_v2.is_enabled",
        return_value=False,
    ):
        from engine.analytics.surprise_engine.surprise_aggregator_v2 import SurpriseAggregatorV2
        with pytest.raises(FeatureDisabledError):
            SurpriseAggregatorV2()


# ─── Test: SurpriseAccuracyTracker ───────────────────────────────────────────

class TestSurpriseAccuracyTracker:
    """Tests per SurpriseAccuracyTracker."""

    def _tracker(self, client):
        from engine.analytics.surprise_engine.surprise_aggregator_v2 import SurpriseAccuracyTracker
        return SurpriseAccuracyTracker(client)

    def test_record_predictions_returns_count(self, in_memory_client, sample_consensus_df) -> None:
        """record_predictions ritorna il numero di record inseriti."""
        from engine.analytics.surprise_engine.surprise_engine import SurpriseCalculator
        calc    = SurpriseCalculator()
        computed = calc.compute_from_df(sample_consensus_df)
        tracker = self._tracker(in_memory_client)
        n = tracker.record_predictions(computed)
        assert isinstance(n, int)
        assert n >= 0

    def test_record_predictions_empty_df_returns_zero(self, in_memory_client) -> None:
        tracker = self._tracker(in_memory_client)
        assert tracker.record_predictions(pd.DataFrame()) == 0

    def test_get_accuracy_empty_returns_empty_dict(self, in_memory_client) -> None:
        """Nessun record → dizionario vuoto."""
        tracker = self._tracker(in_memory_client)
        assert tracker.get_accuracy_by_indicator() == {}

    def test_get_overall_accuracy_empty_returns_none(self, in_memory_client) -> None:
        tracker = self._tracker(in_memory_client)
        assert tracker.get_overall_accuracy() is None


# ─── Test: AutoWeightCalibrator ──────────────────────────────────────────────

class TestAutoWeightCalibrator:
    """Tests per AutoWeightCalibrator (Bayesian update semplificato)."""

    def _calibrator(self):
        from engine.analytics.surprise_engine.surprise_aggregator_v2 import AutoWeightCalibrator
        return AutoWeightCalibrator(surprise_yaml_path=Path("/nonexistent.yaml"))

    def test_calibrate_high_accuracy_increases_weight(self) -> None:
        """Indicatore con alta accuratezza vede aumentare il peso."""
        cal = self._calibrator()
        acc = {"NFP": 0.80}     # 80% > 50% → peso deve aumentare
        weights = {"labour": {"NFP": 0.35, "INITIAL_CLAIMS": 0.25}}
        new_w   = cal.calibrate(acc, weights)
        # NFP ha accuracy > 0.5 → peso relativo aumenta
        old_ratio = 0.35 / (0.35 + 0.25)
        new_ratio = new_w["labour"]["NFP"] / (new_w["labour"]["NFP"] + new_w["labour"]["INITIAL_CLAIMS"])
        assert new_ratio > old_ratio

    def test_calibrate_low_accuracy_decreases_weight(self) -> None:
        """Indicatore con bassa accuratezza vede diminuire il peso."""
        cal = self._calibrator()
        acc = {"NFP": 0.20}     # 20% < 50% → peso deve diminuire
        weights = {"labour": {"NFP": 0.35, "INITIAL_CLAIMS": 0.25}}
        new_w   = cal.calibrate(acc, weights)
        old_ratio = 0.35 / (0.35 + 0.25)
        new_ratio = new_w["labour"]["NFP"] / (new_w["labour"]["NFP"] + new_w["labour"]["INITIAL_CLAIMS"])
        assert new_ratio < old_ratio

    def test_calibrate_weights_sum_to_one_per_sector(self) -> None:
        """Dopo calibrazione, i pesi di ogni settore sommano a 1.0."""
        cal = self._calibrator()
        acc = {"NFP": 0.65, "INITIAL_CLAIMS": 0.55}
        weights = {"labour": {"NFP": 0.35, "INITIAL_CLAIMS": 0.25, "UNEMPLOYMENT_RATE": 0.25, "AVERAGE_HOURLY_EARNINGS": 0.15}}
        new_w   = cal.calibrate(acc, weights)
        sector_sum = sum(new_w["labour"].values())
        assert sector_sum == pytest.approx(1.0, abs=1e-3)

    def test_calibrate_unknown_indicator_keeps_weight(self) -> None:
        """Indicatore senza accuracy storica mantiene il peso originale."""
        cal = self._calibrator()
        acc = {}   # nessuna accuratezza disponibile
        weights = {"labour": {"NFP": 0.35}}
        new_w   = cal.calibrate(acc, weights)
        assert new_w["labour"]["NFP"] == pytest.approx(1.0)  # normalizzato (solo NFP)

    def test_calibrate_minimum_weight_floor(self) -> None:
        """Il peso minimo è 0.01 — nessun indicatore viene azzerato."""
        cal = self._calibrator()
        # Accuratezza 0 → peso potrebbe andare a zero senza il floor
        acc = {"NFP": 0.0}
        weights = {"labour": {"NFP": 0.01}}
        new_w   = cal.calibrate(acc, weights)
        assert new_w["labour"]["NFP"] >= 0.01


# ─── Test: SurpriseCalculator (integrazione con v2) ──────────────────────────

class TestSurpriseCalculatorIntegration:
    """Verifica che SurpriseCalculator sia compatibile con il DataFrame v2."""

    def test_compute_from_df_produces_z_scores(self, sample_consensus_df) -> None:
        from engine.analytics.surprise_engine.surprise_engine import SurpriseCalculator
        calc    = SurpriseCalculator()
        result  = calc.compute_from_df(sample_consensus_df)
        assert "surprise_z" in result.columns
        assert "surprise_raw" in result.columns
        assert not result["surprise_z"].isna().all()

    def test_surprise_raw_equals_actual_minus_consensus(self, sample_consensus_df) -> None:
        from engine.analytics.surprise_engine.surprise_engine import SurpriseCalculator
        calc   = SurpriseCalculator()
        result = calc.compute_from_df(sample_consensus_df)
        expected_raw = result["actual"] - result["consensus"]
        pd.testing.assert_series_equal(
            result["surprise_raw"].round(6),
            expected_raw.round(6),
            check_names=False,
        )

    def test_z_scores_are_float64(self, sample_consensus_df) -> None:
        """z-scores devono essere float64 (Regola 8)."""
        from engine.analytics.surprise_engine.surprise_engine import SurpriseCalculator
        calc   = SurpriseCalculator()
        result = calc.compute_from_df(sample_consensus_df)
        assert result["surprise_z"].dtype == np.float64
