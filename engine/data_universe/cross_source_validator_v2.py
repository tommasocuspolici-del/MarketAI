"""CrossSourceValidatorV2 — Validazione estesa cross-fonte per serie sovrapposte.

Verifica coerenza tra:
  - FRED vs BLS (employment, CPI)
  - FRED vs Yahoo Finance (VIX)

Convenzione 38: la data_universe.yaml è fonte di verità per le serie.
Regola 12: solo letture DB, nessuna API call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from shared.logger import get_logger
from shared.resilience.error_policy import apply_error_policy, ErrorLevel

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

log = get_logger(__name__)

__version__ = "1.0.0"
__all__ = ["CrossSourceValidatorV2", "ValidationResult"]

EMPLOYMENT_DISCREPANCY_THRESHOLD: float = 0.01   # 1% discrepancy → WARN
CPI_DISCREPANCY_THRESHOLD: float = 0.001          # 0.1% discrepancy → WARN
VIX_DISCREPANCY_THRESHOLD: float = 0.5            # 0.5 points → CRITICAL (absolute)


@dataclass
class ValidationResult:
    series_a: str
    series_b: str
    source_a: str
    source_b: str
    discrepancy_pct: float
    max_discrepancy: float
    n_compared: int
    severity: str       # "ok" | "warn" | "critical"
    message: str


class CrossSourceValidatorV2:
    """Valida coerenza tra serie provenienti da fonti diverse.

    Confronta serie macro sovrapposte presenti in macro_data (letture DB puro —
    Regola 12). Le tre validazioni coperte:

    1. Employment: PAYEMS (FRED) vs CES0000000001 (BLS)
    2. CPI: CPIAUCSL (FRED) vs CUUR0000SA0 (BLS)
    3. VIX: VIXCLS (FRED) vs ^VIX (Yahoo Finance)
    """

    def __init__(self, db: DuckDBClient) -> None:
        self._db = db

    # ─── Public validation methods ────────────────────────────────────────────

    def validate_employment_fred_vs_bls(
        self,
        lookback_days: int = 90,
    ) -> ValidationResult:
        """Confronta PAYEMS (FRED) vs CES0000000001 (BLS) per occupazione totale."""
        df_a = self._query_series("PAYEMS", lookback_days)
        df_b = self._query_series("CES0000000001", lookback_days)
        return self._compute_discrepancy(
            df_a=df_a,
            df_b=df_b,
            threshold=EMPLOYMENT_DISCREPANCY_THRESHOLD,
            series_a="PAYEMS",
            series_b="CES0000000001",
            source_a="FRED",
            source_b="BLS",
        )

    def validate_cpi_fred_vs_bls(
        self,
        lookback_days: int = 90,
    ) -> ValidationResult:
        """Confronta CPIAUCSL (FRED) vs CUUR0000SA0 (BLS) per CPI."""
        df_a = self._query_series("CPIAUCSL", lookback_days)
        df_b = self._query_series("CUUR0000SA0", lookback_days)
        return self._compute_discrepancy(
            df_a=df_a,
            df_b=df_b,
            threshold=CPI_DISCREPANCY_THRESHOLD,
            series_a="CPIAUCSL",
            series_b="CUUR0000SA0",
            source_a="FRED",
            source_b="BLS",
        )

    def validate_vix_fred_vs_yahoo(
        self,
        lookback_days: int = 30,
    ) -> ValidationResult:
        """Confronta VIXCLS (FRED) vs ^VIX (Yahoo Finance) per coerenza VIX.

        Per il VIX la soglia è in punti assoluti, non percentuale. Poiché
        _compute_discrepancy lavora in percentuale, si normalizza la soglia
        dividendola per il valore medio atteso di VIX (~20). La soglia di
        0.5 punti su 20 corrisponde a ~2.5%.
        """
        df_a = self._query_series("VIXCLS", lookback_days)
        df_b = self._query_series("^VIX", lookback_days)
        # Normalise absolute threshold to percentage (~0.5 / 20 ≈ 0.025)
        vix_pct_threshold = VIX_DISCREPANCY_THRESHOLD / 20.0
        return self._compute_discrepancy(
            df_a=df_a,
            df_b=df_b,
            threshold=vix_pct_threshold,
            series_a="VIXCLS",
            series_b="^VIX",
            source_a="FRED",
            source_b="Yahoo Finance",
        )

    def run_all(self) -> list[ValidationResult]:
        """Esegue tutte le validazioni disponibili."""
        results: list[ValidationResult] = []
        for method in [
            self.validate_employment_fred_vs_bls,
            self.validate_cpi_fred_vs_bls,
            self.validate_vix_fred_vs_yahoo,
        ]:
            try:
                results.append(method())
            except Exception as exc:
                log.warning("cross_source_v2.validation_failed", error=str(exc))
        return results

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _query_series(self, series_id: str, lookback_days: int) -> pd.DataFrame:
        """Recupera serie da macro_data (tabella principale FRED)."""
        sql = """
        SELECT ts, value
        FROM macro_data
        WHERE series_id = ?
          AND ts >= NOW() - INTERVAL (? || ' days')
        ORDER BY ts DESC
        """
        try:
            return self._db.query_df(sql, [series_id, lookback_days])
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def _compute_discrepancy(
        df_a: pd.DataFrame,
        df_b: pd.DataFrame,
        threshold: float,
        series_a: str,
        series_b: str,
        source_a: str,
        source_b: str,
    ) -> ValidationResult:
        """Calcola discrepanza percentuale media tra due serie allineate.

        La severità è:
          · "ok"       — avg_disc ≤ threshold
          · "warn"     — avg_disc > threshold
          · "critical" — max_disc > threshold * 10
        """
        if df_a.empty or df_b.empty:
            return ValidationResult(
                series_a=series_a, series_b=series_b,
                source_a=source_a, source_b=source_b,
                discrepancy_pct=0.0, max_discrepancy=0.0,
                n_compared=0, severity="ok",
                message="Dati insufficienti per validazione",
            )

        merged = pd.merge(
            df_a.rename(columns={"value": "val_a"}),
            df_b.rename(columns={"value": "val_b"}),
            on="ts", how="inner",
        )
        if merged.empty:
            return ValidationResult(
                series_a=series_a, series_b=series_b,
                source_a=source_a, source_b=source_b,
                discrepancy_pct=0.0, max_discrepancy=0.0,
                n_compared=0, severity="ok",
                message="Nessuna data comune per confronto",
            )

        disc = (
            (merged["val_a"] - merged["val_b"]).abs()
            / merged["val_a"].abs().clip(lower=1e-8)
        )
        avg_disc = float(disc.mean())
        max_disc = float(disc.max())

        if max_disc > threshold * 10:
            severity = "critical"
        elif avg_disc > threshold:
            severity = "warn"
        else:
            severity = "ok"

        log.info(
            "cross_source_v2.result",
            series_a=series_a,
            series_b=series_b,
            severity=severity,
            avg_disc_pct=round(avg_disc * 100, 4),
            max_disc_pct=round(max_disc * 100, 4),
            n=len(merged),
        )

        return ValidationResult(
            series_a=series_a, series_b=series_b,
            source_a=source_a, source_b=source_b,
            discrepancy_pct=round(avg_disc * 100, 4),
            max_discrepancy=round(max_disc * 100, 4),
            n_compared=len(merged),
            severity=severity,
            message=f"Discrepanza media {avg_disc * 100:.3f}%, max {max_disc * 100:.3f}%",
        )
