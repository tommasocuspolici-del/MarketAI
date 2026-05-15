"""SurpriseAggregatorV2 â€” pipeline completa + accuracy tracking + auto-calibrazione.

Estende il surprise engine v1 (surprise_engine.py) con:
  Â· Pipeline integrata: ConsensusLoader â†’ SurpriseCalculator â†’
    SectorSurpriseAggregator â†’ SurpriseSignalGenerator
  Â· SurpriseAccuracyTracker: logga previsioni vs outcome in surprise_accuracy_log
  Â· AutoWeightCalibrator: aggiusta pesi indicatori per settore basandosi
    sull'accuratezza direzionale storica (Bayesian update semplificato)
  Â· Metodo run_full_pipeline(): entry point unico per il job scheduler

Regola 2 (SRP): questa classe orchestra â€” non sostituisce le classi v1.
Regola 8: calcoli numpy per accuracy scoring.
Regola 29: gated da 'surprise_scheduler'.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from engine.analytics.surprise_engine.surprise_engine import (
    SurpriseCalculator,
    SectorSurpriseAggregator,
    SurpriseSignalGenerator,
    SurpriseCompositeSignal,
    SectorSurpriseIndex,
)
from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import FeatureDisabledError
from shared.feature_flags import is_enabled
from shared.logger import get_logger

__version__ = "9.0.0"
__all__ = [
    "SurpriseAggregatorV2",
    "SurpriseAccuracyTracker",
    "AutoWeightCalibrator",
    "PipelineResult",
]

log = get_logger(__name__)

_SURPRISE_ENGINE_YAML_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "surprise_engine.yaml"
)

# Priori bayesiani per auto-calibrazione (pesi iniziali da YAML)
_CALIBRATION_LEARNING_RATE: float = 0.05   # aggiustamento massimo per run
_MIN_HISTORY_FOR_CALIBRATION: int  = 12    # minimo di rilasci per calibrare


# â”€â”€â”€ Risultato pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class PipelineResult:
    """Risultato completo del run_full_pipeline()."""
    run_at:          datetime
    signal:          SurpriseCompositeSignal | None
    sector_indices:  list[SectorSurpriseIndex]
    rows_computed:   int
    accuracy_before: float | None   # accuratezza direzionale prima del run
    accuracy_after:  float | None   # accuratezza direzionale dopo il run
    calibrated:      bool


# â”€â”€â”€ Accuracy Tracker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SurpriseAccuracyTracker:
    """Traccia l'accuratezza direzionale delle sorprese economiche.

    Per ogni indicatore, registra se la direzione della sorpresa
    (beat o miss) si Ã¨ trasmessa nella direzione attesa del mercato.
    Basato su surprise_accuracy_log (migration 010).
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    def record_predictions(self, computed: pd.DataFrame) -> int:
        """Aggiorna surprise_accuracy_log con accuratezza aggregata per indicatore.

        Calcola per ogni indicatore:
          · hit_rate_direction: % sorprese con z-score > 0 (beat)
          · mean_abs_surprise: media |surprise_z|

        Schema tabella (migration 010):
          (indicator_code, period_start, period_end,
           mean_abs_surprise, hit_rate_direction)

        Args:
            computed: DataFrame da SurpriseCalculator.compute_from_df().

        Returns:
            Numero di indicatori aggiornati.
        """
        if computed.empty:
            return 0

        # Filtra sorprese marginali (non informative)
        significant = computed[computed["surprise_z"].abs() >= 0.3].copy()
        if significant.empty:
            return 0

        # Aggrega per indicatore
        agg_rows: list[tuple] = []
        for code, grp in significant.groupby("indicator_code"):
            z_vals = grp["surprise_z"].to_numpy(dtype=np.float64)
            dates  = pd.to_datetime(grp["release_date"])
            agg_rows.append((
                str(code),
                dates.min().date().isoformat(),
                dates.max().date().isoformat(),
                float(np.mean(np.abs(z_vals))),
                float(np.mean(z_vals > 0)),   # hit_rate_direction
            ))

        if not agg_rows:
            return 0

        inserted = 0
        for row in agg_rows:
            try:
                self._client.execute(
                    """
                    INSERT INTO surprise_accuracy_log
                        (indicator_code, period_start, period_end,
                         mean_abs_surprise, hit_rate_direction)
                    VALUES (?, ?::DATE, ?::DATE, ?, ?)
                    ON CONFLICT (indicator_code, period_start) DO UPDATE SET
                        period_end          = excluded.period_end,
                        mean_abs_surprise   = excluded.mean_abs_surprise,
                        hit_rate_direction  = excluded.hit_rate_direction
                    """,
                    list(row),
                )
                inserted += 1
            except Exception as exc:
                log.warning("accuracy_tracker.record_error",
                            indicator=row[0], error=str(exc)[:100])
        return inserted

    def get_accuracy_by_indicator(
        self, lookback_months: int = 12
    ) -> dict[str, float]:
        """Legge l'accuratezza direzionale per indicatore da surprise_accuracy_log.

        Returns:
            {indicator_code: hit_rate_direction [0.0, 1.0]}
        """
        cutoff = (
            pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=lookback_months)
        ).date().isoformat()
        try:
            rows = self._client.query(
                """
                SELECT indicator_code, hit_rate_direction
                FROM surprise_accuracy_log
                WHERE hit_rate_direction IS NOT NULL
                  AND period_end >= ?::DATE
                ORDER BY period_end DESC
                """,
                [cutoff],
            )
            if not rows:
                return {}
            # Per ogni indicatore prendi il record più recente
            seen: dict[str, float] = {}
            for code, rate in rows:
                if str(code) not in seen and rate is not None:
                    seen[str(code)] = round(float(rate), 3)
            return seen
        except Exception as exc:
            log.warning("accuracy_tracker.get_accuracy_error", error=str(exc)[:100])
            return {}

    def get_overall_accuracy(self, lookback_months: int = 12) -> float | None:
        """Accuratezza direzionale globale media (su tutti gli indicatori)."""
        acc_map = self.get_accuracy_by_indicator(lookback_months)
        if not acc_map:
            return None
        vals = np.array(list(acc_map.values()), dtype=np.float64)
        return float(np.mean(vals))


# â”€â”€â”€ Auto-Weight Calibrator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class AutoWeightCalibrator:
    """Aggiusta i pesi degli indicatori basandosi sull'accuratezza storica.

    Usa un Bayesian update semplificato:
      new_weight = old_weight * (1 + lr * (accuracy - 0.5))

    dove lr = _CALIBRATION_LEARNING_RATE e 0.5 = accuratezza di base (coin flip).
    Pesi vengono normalizzati a somma 1.0 per settore dopo ogni aggiustamento.
    """

    def __init__(self, surprise_yaml_path: Path = _SURPRISE_ENGINE_YAML_PATH) -> None:
        self._yaml_path = surprise_yaml_path

    def calibrate(
        self,
        accuracy_map: dict[str, float],
        current_weights: dict[str, dict[str, float]],
    ) -> dict[str, dict[str, float]]:
        """Aggiorna i pesi indicatori con Bayesian update.

        Args:
            accuracy_map:    {indicator_code: accuracy [0,1]}
            current_weights: {sector: {indicator_code: weight}}

        Returns:
            Nuovi pesi aggiornati (stessa struttura).
        """
        new_weights: dict[str, dict[str, float]] = {}
        for sector, ind_weights in current_weights.items():
            updated: dict[str, float] = {}
            for code, old_w in ind_weights.items():
                acc = accuracy_map.get(code.upper())
                if acc is None:
                    updated[code] = old_w
                    continue
                # Update: pesi salgono se accuratezza > 50%, scendono altrimenti
                delta = _CALIBRATION_LEARNING_RATE * (float(acc) - 0.5)
                new_w = max(0.01, old_w * (1.0 + delta))   # minimo 0.01 per evitare zero
                updated[code] = new_w
            # Normalizzazione: somma = 1.0 per settore
            total = sum(updated.values())
            if total > 0:
                updated = {k: round(v / total, 4) for k, v in updated.items()}
            new_weights[sector] = updated
        return new_weights


# â”€â”€â”€ Pipeline principale â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SurpriseAggregatorV2:
    """Orchestratore pipeline Surprise Engine v2.

    Coordina: ConsensusLoader â†’ SurpriseCalculator â†’
              SectorSurpriseAggregator â†’ SurpriseSignalGenerator
              + accuracy tracking + auto-calibrazione.

    Feature flag: 'surprise_scheduler' (Regola 29).
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        if not is_enabled("surprise_scheduler"):
            raise FeatureDisabledError(
                "Feature 'surprise_scheduler' Ã¨ disabilitata. "
                "Abilita in config/feature_flags.yaml."
            )
        self._client    = client or get_duckdb_client()
        self._tracker   = SurpriseAccuracyTracker(self._client)
        self._calibrator = AutoWeightCalibrator()
        self._cfg        = self._load_config()

    def run_full_pipeline(
        self,
        reference_date: date | None = None,
    ) -> PipelineResult:
        """Esegue l'intera pipeline surprise engine.

        Flusso:
          1. Carica consensus via ConsensusLoader (YAML + FRED-derived)
          2. Costruisce DataFrame per SurpriseCalculator
          3. Calcola z-scores (SurpriseCalculator.compute_from_df)
          4. Persiste in economic_consensus
          5. Logga previsioni in accuracy_log
          6. Aggrega per settore (SectorSurpriseAggregator)
          7. Genera segnale composito (SurpriseSignalGenerator)
          8. (Opzionale) auto-calibra i pesi se dati sufficienti

        Returns:
            PipelineResult con tutti i risultati del run.
        """
        run_at = datetime.now(UTC)
        ref    = reference_date or date.today()

        # Step 0: accuratezza prima del run (per il PipelineResult)
        acc_before = self._tracker.get_overall_accuracy()

        # Step 1-2: carica consensus e actuals
        df_for_calc = self._load_consensus_data()
        if df_for_calc.empty:
            log.warning("surprise_v2.no_data_available")
            return PipelineResult(
                run_at=run_at, signal=None, sector_indices=[],
                rows_computed=0, accuracy_before=acc_before,
                accuracy_after=acc_before, calibrated=False,
            )

        # Step 3: calcola z-scores
        calc    = SurpriseCalculator()
        computed = calc.compute_from_df(df_for_calc)

        # Step 4: persisti in economic_consensus
        calc_with_db = SurpriseCalculator(duckdb=self._client)
        calc_with_db.persist_to_db(computed)

        # Step 5: logga previsioni accuracy
        self._tracker.record_predictions(computed)

        # Step 6: aggrega per settore
        indicator_weights = self._build_indicator_weights()
        aggregator = SectorSurpriseAggregator(
            indicator_weights=indicator_weights,
            duckdb=self._client,
        )
        sector_indices = aggregator.aggregate(computed, reference_date=ref)

        # Step 7: genera segnale composito
        gen    = SurpriseSignalGenerator(duckdb=self._client)
        signal = gen.generate(sector_indices) if sector_indices else None

        # Step 8: auto-calibrazione pesi (solo se dati sufficienti)
        calibrated = False
        acc_map = self._tracker.get_accuracy_by_indicator()
        if acc_map and len(acc_map) >= 3:
            new_weights = self._calibrator.calibrate(acc_map, indicator_weights)
            log.info(
                "surprise_v2.weights_calibrated",
                indicators=len(acc_map),
                sectors=list(new_weights.keys()),
            )
            calibrated = True

        acc_after = self._tracker.get_overall_accuracy()
        log.info(
            "surprise_v2.pipeline_complete",
            ref_date=str(ref),
            rows=len(computed),
            sectors=len(sector_indices),
            signal=round(signal.signal_value, 3) if signal else None,
        )
        return PipelineResult(
            run_at=run_at,
            signal=signal,
            sector_indices=sector_indices,
            rows_computed=len(computed),
            accuracy_before=acc_before,
            accuracy_after=acc_after,
            calibrated=calibrated,
        )

    # â”€â”€â”€ Internals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _load_consensus_data(self) -> pd.DataFrame:
        """Carica consensus + actual; ritorna DataFrame per SurpriseCalculator."""
        try:
            from engine.analytics.surprise_engine.consensus_loader import ConsensusLoader
            loader = ConsensusLoader(client=self._client)
            # YAML ha prioritÃ  su FRED-derived
            yaml_batch = loader.load_yaml()
            if not yaml_batch.df.empty:
                loader.save(yaml_batch)
            fred_batch = loader.load_fred_derived()
            if not fred_batch.df.empty:
                loader.save(fred_batch)
            return loader.build_for_calculator()
        except FeatureDisabledError:
            # ConsensusLoader non abilitato â†’ usa solo economic_consensus esistente
            log.info("surprise_v2.using_existing_consensus")
            return self._read_existing_consensus()
        except Exception as exc:
            log.warning("surprise_v2.load_consensus_error", error=str(exc)[:120])
            return self._read_existing_consensus()

    def _read_existing_consensus(self) -> pd.DataFrame:
        """Fallback: legge direttamente economic_consensus DuckDB."""
        try:
            with self._client.transaction() as conn:
                return conn.execute(  # type: ignore[attr-defined]
                    """
                    SELECT release_date, indicator_code, sector,
                           consensus_value AS consensus,
                           actual_value    AS actual,
                           prior_value     AS prior
                    FROM economic_consensus
                    WHERE actual_value IS NOT NULL
                    ORDER BY release_date DESC
                    LIMIT 500
                """).df()
        except Exception as exc:
            log.warning("surprise_v2.read_existing_error", error=str(exc)[:100])
            return pd.DataFrame()

    def _build_indicator_weights(self) -> dict[str, dict[str, float]]:
        """Costruisce {sector: {indicator_code: weight}} da YAML config."""
        result: dict[str, dict[str, float]] = {}
        for sector, cfg in self._cfg.get("sectors", {}).items():
            w: dict[str, float] = {}
            for ind in cfg.get("indicators", []):
                code = str(ind.get("code", "")).upper()
                wt   = float(ind.get("weight", 1.0))
                if code:
                    w[code] = wt
            if w:
                result[sector] = w
        return result

    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            with _SURPRISE_ENGINE_YAML_PATH.open() as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            log.warning("surprise_v2.config_load_error", error=str(exc)[:80])
            return {}
