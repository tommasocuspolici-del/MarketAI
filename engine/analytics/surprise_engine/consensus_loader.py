"""ConsensusLoader â€” carica stime consensus per Economic Surprise Engine v2.

Fonti supportate (in ordine di prioritÃ ):
  1. YAML manuale (config/surprise_engine_consensus.yaml) â†’ source='yaml_manual'
  2. FRED-derived (previous actual value come naive consensus) â†’ source='fred_derived'
  3. Mock (test) â†’ source='mock'

Dopo il caricamento, build_for_calculator() produce un DataFrame pronto
per SurpriseCalculator.compute_from_df() â€” include sia consensus che actuals.

Regola 12: fetch â†’ clean â†’ validate â†’ duckdb_write â†’ cache â†’ return.
Regola 29: gated da feature flag 'surprise_consensus_loader'.
Regola 2 (SRP): carica consensus â€” non calcola sorprese (SurpriseCalculator).

ANTI-REGRESSIONE (v9.0 Sett.6):
  Â· load_yaml() NON accetta espressioni Python nelle stime â€” solo scalari numerici.
  Â· fred_derived consensus = valore precedente shifted(1): non Ã¨ consenso reale,
    Ã¨ un placeholder per il gap strutturale. L'utente deve aggiornare il YAML.
"""
from __future__ import annotations

from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import ConfigurationError, DataValidationError, FeatureDisabledError
from shared.feature_flags import is_enabled
from shared.logger import get_logger

__version__ = "9.0.0"
__all__ = ["ConsensusLoader", "ConsensusBatch"]

log = get_logger(__name__)

_CONSENSUS_YAML_PATH = Path(__file__).resolve().parents[3] / "config" / "surprise_engine_consensus.yaml"
_SURPRISE_ENGINE_YAML_PATH = Path(__file__).resolve().parents[3] / "config" / "surprise_engine.yaml"

# Colonne obbligatorie per il DataFrame che entra in SurpriseCalculator
_CALCULATOR_COLS: list[str] = [
    "release_date", "indicator_code", "sector",
    "consensus", "actual", "prior",
]


class ConsensusBatch:
    """Risultato di un caricamento consensus â€” wrapper attorno a pd.DataFrame."""

    def __init__(self, df: pd.DataFrame, source: str, loaded_at: datetime) -> None:
        self.df         = df
        self.source     = source
        self.loaded_at  = loaded_at
        self.row_count  = len(df)

    def __repr__(self) -> str:
        return (
            f"ConsensusBatch(source='{self.source}', rows={self.row_count}, "
            f"loaded_at='{self.loaded_at.strftime('%Y-%m-%d %H:%M')}')"
        )


class ConsensusLoader:
    """Carica e persiste stime consensus per gli indicatori economici.

    Uso tipico::
        loader = ConsensusLoader()
        batch  = loader.load_yaml()
        loader.save(batch)
        df_for_calc = loader.build_for_calculator()
        # â†’ passa df_for_calc a SurpriseCalculator.compute_from_df()

    Feature flag: 'surprise_consensus_loader' (Regola 29).
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        if not is_enabled("surprise_consensus_loader"):
            raise FeatureDisabledError(
                "Feature 'surprise_consensus_loader' is disabled. "
                "Abilita in config/feature_flags.yaml."
            )
        self._client = client or get_duckdb_client()
        self._indicator_map = self._load_indicator_map()

    # â”€â”€â”€ Load â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def load_yaml(
        self,
        yaml_path: Path | None = None,
    ) -> ConsensusBatch:
        """Carica stime consensus da YAML manuale.

        Args:
            yaml_path: Path al file YAML. Default: config/surprise_engine_consensus.yaml.

        Returns:
            ConsensusBatch con DataFrame pronto per save().
        """
        path = yaml_path or _CONSENSUS_YAML_PATH
        if not path.exists():
            raise ConfigurationError(
                f"File consensus non trovato: {path}. "
                "Crea config/surprise_engine_consensus.yaml."
            )
        with path.open() as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        estimates: list[dict[str, Any]] = raw.get("estimates", [])
        if not estimates:
            log.warning("consensus_loader.yaml_empty", path=str(path))
            return ConsensusBatch(pd.DataFrame(), source="yaml_manual", loaded_at=datetime.now(UTC))

        rows: list[dict[str, object]] = []
        for entry in estimates:
            code = str(entry.get("code", "")).strip().upper()
            d    = entry.get("date", "")
            val  = entry.get("consensus")
            if not code or not d or val is None:
                log.debug("consensus_loader.yaml_entry_skip", entry=entry)
                continue
            try:
                # ANTI-REGRESSIONE: val deve essere scalare numerico â€” non espressioni
                consensus_float = float(val)
                release = pd.Timestamp(str(d)).date()
            except (ValueError, TypeError) as exc:
                log.warning("consensus_loader.yaml_parse_error", code=code, error=str(exc))
                continue
            rows.append({
                "indicator_code": code,
                "release_date":   release,
                "consensus_value": np.float64(consensus_float),
                "source": "yaml_manual",
            })

        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        log.info("consensus_loader.yaml_loaded", rows=len(df), path=str(path))
        return ConsensusBatch(df, source="yaml_manual", loaded_at=datetime.now(UTC))

    def load_fred_derived(self) -> ConsensusBatch:
        """Genera consensus naivi dalla tabella macro_series DuckDB.

        Usa il valore precedente (shift +1) come consensus naive per ogni
        indicatore con fred_actual configurato in surprise_engine.yaml.
        Non Ã¨ consenso reale degli analisti â€” Ã¨ un placeholder operativo.
        """
        indicator_codes = list(self._indicator_map.keys())
        if not indicator_codes:
            return ConsensusBatch(pd.DataFrame(), source="fred_derived", loaded_at=datetime.now(UTC))

        rows: list[dict[str, object]] = []
        try:
            with self._client.transaction() as conn:
                # Cerca le serie FRED nella tabella macro_series
                fred_series = [
                    self._indicator_map[c].get("fred_actual", "")
                    for c in indicator_codes
                    if self._indicator_map[c].get("fred_actual")
                ]
                if not fred_series:
                    return ConsensusBatch(pd.DataFrame(), source="fred_derived", loaded_at=datetime.now(UTC))

                placeholders = ", ".join(["?"] * len(fred_series))
                df_macro = conn.execute(  # type: ignore[attr-defined]
                    f"""
                    SELECT series_id, date, value
                    FROM macro_series
                    WHERE series_id IN ({placeholders})
                    ORDER BY series_id, date DESC
                    """,
                    fred_series,
                ).df()

            if df_macro.empty:
                return ConsensusBatch(pd.DataFrame(), source="fred_derived", loaded_at=datetime.now(UTC))

            # Reverse map: fred_series â†’ indicator_code
            fred_to_code = {
                self._indicator_map[c]["fred_actual"]: c
                for c in indicator_codes
                if self._indicator_map[c].get("fred_actual")
            }

            for series_id, grp in df_macro.groupby("series_id"):
                code = fred_to_code.get(str(series_id))
                if not code:
                    continue
                # Consensus = valore precedente (shift 1) su dati ordinati per data
                grp = grp.sort_values("date")
                latest_actual = grp.iloc[-1]
                prev_actual   = grp.iloc[-2] if len(grp) > 1 else grp.iloc[-1]
                rows.append({
                    "indicator_code":  code,
                    "release_date":    pd.Timestamp(str(latest_actual["date"])).date(),
                    "consensus_value": np.float64(float(prev_actual["value"])),
                    "source":          "fred_derived",
                })

        except Exception as exc:
            log.warning("consensus_loader.fred_derived_error", error=str(exc)[:120])
            return ConsensusBatch(pd.DataFrame(), source="fred_derived", loaded_at=datetime.now(UTC))

        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        log.info("consensus_loader.fred_derived_loaded", rows=len(df))
        return ConsensusBatch(df, source="fred_derived", loaded_at=datetime.now(UTC))

    # â”€â”€â”€ Save â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def save(self, batch: ConsensusBatch) -> int:
        """Persiste un ConsensusBatch nella tabella consensus_estimates.

        Returns:
            Numero di righe inserite/aggiornate.
        """
        if batch.df.empty:
            return 0
        df = batch.df.copy()
        if "source" not in df.columns:
            df["source"] = batch.source
        df["loaded_at"] = datetime.now(UTC).isoformat()

        try:
            with self._client.transaction() as conn:
                conn.register("_consensus_batch", df)  # type: ignore[attr-defined]
                conn.execute(  # type: ignore[attr-defined]
                    """
                    INSERT OR REPLACE INTO consensus_estimates
                    (indicator_code, release_date, consensus_value, source, loaded_at)
                    SELECT
                        indicator_code,
                        release_date::DATE,
                        consensus_value,
                        source,
                        loaded_at::TIMESTAMPTZ
                    FROM _consensus_batch
                """)
            log.info("consensus_loader.saved", rows=len(df), source=batch.source)
            return len(df)
        except Exception as exc:
            from shared.exceptions import DatabaseError
            raise DatabaseError(f"consensus_estimates write failed: {exc}") from exc

    # â”€â”€â”€ Build DataFrame per SurpriseCalculator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def build_for_calculator(self) -> pd.DataFrame:
        """Join consensus_estimates con i valori actual da economic_consensus.

        Produce un DataFrame con le colonne attese da SurpriseCalculator:
          release_date, indicator_code, sector, consensus, actual, prior.

        Preferisce source='yaml_manual' su 'fred_derived' per lo stesso
        (indicator_code, release_date) â€” prioritÃ  esplicita per il consenso reale.
        """
        try:
            with self._client.transaction() as conn:
                df = conn.execute(  # type: ignore[attr-defined]
                    """
                    WITH ranked_est AS (
                        SELECT
                            indicator_code,
                            release_date,
                            consensus_value,
                            source,
                            ROW_NUMBER() OVER (
                                PARTITION BY indicator_code, release_date
                                ORDER BY
                                    CASE source
                                        WHEN 'yaml_manual' THEN 1
                                        WHEN 'fred_derived' THEN 2
                                        ELSE 3
                                    END
                            ) AS rn
                        FROM consensus_estimates
                    ),
                    best_est AS (
                        SELECT indicator_code, release_date, consensus_value
                        FROM ranked_est WHERE rn = 1
                    )
                    SELECT
                        ec.release_date,
                        ec.indicator_code,
                        ec.sector,
                        COALESCE(be.consensus_value, ec.consensus_value) AS consensus,
                        ec.actual_value                                   AS actual,
                        ec.prior_value                                    AS prior,
                        ec.source
                    FROM economic_consensus ec
                    LEFT JOIN best_est be
                        ON ec.indicator_code = be.indicator_code
                        AND ec.release_date  = be.release_date
                    WHERE ec.actual_value IS NOT NULL
                    ORDER BY ec.release_date DESC
                """).df()

            if df.empty:
                log.info("consensus_loader.build_empty_result")
            else:
                log.info("consensus_loader.build_done", rows=len(df))
            return df

        except Exception as exc:
            log.warning("consensus_loader.build_error", error=str(exc)[:120])
            return pd.DataFrame(columns=_CALCULATOR_COLS)

    # â”€â”€â”€ Internals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _load_indicator_map() -> dict[str, dict[str, Any]]:
        """Carica la mappa indicator_code â†’ config da surprise_engine.yaml."""
        try:
            with _SURPRISE_ENGINE_YAML_PATH.open() as f:
                raw = yaml.safe_load(f) or {}
            result: dict[str, dict[str, Any]] = {}
            for _sector, sector_cfg in raw.get("sectors", {}).items():
                for ind in sector_cfg.get("indicators", []):
                    code = str(ind.get("code", "")).upper()
                    if code:
                        result[code] = dict(ind)
                        result[code]["sector"] = _sector
            return result
        except Exception as exc:
            log.warning("consensus_loader.indicator_map_error", error=str(exc)[:80])
            return {}
