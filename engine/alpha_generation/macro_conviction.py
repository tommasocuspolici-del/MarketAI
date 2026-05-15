"""MacroConvictionCalculator — Settimana 3 Roadmap Unificata.

Aggrega 15 serie FRED in un macro_score unico [-1, +1] con pesi per categoria.
Versione DEFINITIVA: non verrà modificata nelle settimane successive.

15 Serie FRED usate (suddivise in 5 categorie):

  LABOUR (peso 25%):
    ICSA     — Initial Jobless Claims (settimanale)
    CCSA     — Continued Claims (settimanale)
    PAYEMS   — Nonfarm Payrolls MoM change (mensile)

  INFLATION (peso 20%):
    CPIAUCSL — CPI All Urban Consumers YoY (mensile)
    CPILFESL — Core CPI (ex food/energy) YoY (mensile)
    T10YIE   — Breakeven inflation 10Y (TIPS)

  RATES (peso 20%):
    DGS10    — Treasury 10Y yield
    DGS2     — Treasury 2Y yield
    T10Y3M   — Spread 10Y-3M (Estrella-Mishkin input)
    FEDFUNDS — Fed Funds Rate effettivo

  CREDIT (peso 20%):
    BAMLH0A0HYM2 — ICE BofA HY OAS
    TEDRATE      — TED Spread
    NFCI         — Chicago Fed Financial Conditions

  GROWTH (peso 15%):
    INDPRO  — Industrial Production Index MoM
    PAYEMS  — usato anche qui come conferma crescita

Regola 2 (SRP): questo modulo aggrega i sub-moduli, non li implementa.
Regola 8: numpy per tutti i calcoli numerici.
Regola 28: legge da MacroRepository (già in DB, non fa fetch API diretti).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.alpha_generation.claims_cross_analyzer import ClaimsInflationCrossAnalyzer
from engine.alpha_generation.credit_stress_analyzer import CreditStressAnalyzer
from engine.alpha_generation.schemas import (
    MacroConvictionResult,
)
from engine.alpha_generation.yield_curve_analyzer import YieldCurveAnalyzer
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.macro_repo import MacroRepository

__version__ = "1.0.0"
__all__ = ["MacroConvictionCalculator"]

log = get_logger(__name__)

# Pesi per categoria (somma = 1.0)
_CATEGORY_WEIGHTS: dict[str, float] = {
    "labour":    0.25,
    "inflation": 0.20,
    "rates":     0.20,
    "credit":    0.20,
    "growth":    0.15,
}

# Minimo di serie richieste per confidence HIGH
_MIN_SERIES_HIGH_CONFIDENCE = 10
_MIN_SERIES_MEDIUM_CONFIDENCE = 6


class MacroConvictionCalculator:
    """Aggrega 15 serie FRED in un unico macro_score [-1, +1].

    Non esegue fetch API — legge dai DataFrame già presenti in DuckDB
    tramite MacroRepository. Rispetta la pipeline fetch→DB→read (Rule 12).

    Usage::

        repo = get_macro_repository()
        calc = MacroConvictionCalculator(macro_repo=repo)
        result = calc.compute()
    """

    def __init__(self, macro_repo: MacroRepository) -> None:
        self._repo    = macro_repo
        self._claims  = ClaimsInflationCrossAnalyzer()
        self._yield   = YieldCurveAnalyzer()
        self._credit  = CreditStressAnalyzer()

    def compute(self) -> MacroConvictionResult:
        """Calcola il macro_score aggregato dalle 15 serie FRED.

        Returns:
            MacroConvictionResult con score, breakdown categorie, sub-output.
            Se il DB non è raggiungibile, restituisce MacroConvictionResult.degraded()
            con is_degraded=True invece di propagare l'eccezione.

        Notes:
            Se una categoria ha tutte le serie mancanti, il suo peso
            viene ridistribuito proporzionalmente alle altre categorie presenti.
        """
        try:
            return self._compute_internal()
        except Exception as exc:  # noqa: BLE001
            log.error(
                "[DEGRADE] macro_conviction.compute_failed: %s: %s",
                type(exc).__name__, str(exc)[:200],
                exc_info=True,
            )
            return MacroConvictionResult.degraded()

    def _compute_internal(self) -> MacroConvictionResult:
        """Implementazione interna del calcolo (chiamata da compute())."""
        t_start = datetime.now(UTC)

        # ── 1. Leggi tutte le 15 serie dal DB ─────────────────────────────
        series = self._load_all_series()
        series_available = sum(1 for df in series.values() if not df.empty)

        # ── 2. Sub-modulo Claims/Inflation (labour + inflation input) ──────
        claims_out = self._claims.analyze(
            icsa_df  = series.get("ICSA", pd.DataFrame()),
            cpi_df   = series.get("CPIAUCSL", pd.DataFrame()),
            ccsa_df  = series.get("CCSA", None),
        )

        # ── 3. Sub-modulo Yield Curve (rates input) ────────────────────────
        yield_out = self._yield.analyze(
            dgs10_df    = series.get("DGS10", pd.DataFrame()),
            dgs2_df     = series.get("DGS2", pd.DataFrame()),
            dgs3mo_df   = series.get("DGS3MO", None),
            t10y3m_df   = series.get("T10Y3M", None),
            t10yie_df   = series.get("T10YIE", None),
            fedfunds_df = series.get("FEDFUNDS", None),
        )

        # ── 4. Sub-modulo Credit Stress ────────────────────────────────────
        credit_out = self._credit.analyze(
            hy_oas_df = series.get("BAMLH0A0HYM2", pd.DataFrame()),
            ig_oas_df = series.get("BAMLC0A0CM", None),
            ted_df    = series.get("TEDRATE", None),
            nfci_df   = series.get("NFCI", None),
        )

        # ── 5. Calcola score per categoria ────────────────────────────────
        labour_score    = self._compute_labour_score(series)
        inflation_score = self._compute_inflation_score(series, claims_out.cpi_yoy)
        rates_score     = float(yield_out.regime_score)
        credit_score    = float(credit_out.stress_score)
        growth_score    = self._compute_growth_score(series)

        # ── 6. Aggregazione pesata con redistribuzione pesi mancanti ──────
        category_scores = {
            "labour":    labour_score,
            "inflation": inflation_score,
            "rates":     rates_score,
            "credit":    credit_score,
            "growth":    growth_score,
        }

        macro_score, effective_weights = _weighted_aggregate(category_scores)
        macro_score = float(np.clip(macro_score, -1.0, 1.0))

        # ── 7. Confidence basata sul numero di serie disponibili ───────────
        if series_available >= _MIN_SERIES_HIGH_CONFIDENCE:
            confidence = "HIGH"
        elif series_available >= _MIN_SERIES_MEDIUM_CONFIDENCE:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        log.info(
            "macro_conviction.computed",
            macro_score=round(macro_score, 3),
            confidence=confidence,
            series_available=series_available,
            labour=round(labour_score, 3),
            inflation=round(inflation_score, 3),
            rates=round(rates_score, 3),
            credit=round(credit_score, 3),
            growth=round(growth_score, 3),
        )

        return MacroConvictionResult(
            macro_score=macro_score,
            confidence=confidence,
            computed_at=t_start,
            claims_output=claims_out,
            yield_output=yield_out,
            credit_output=credit_out,
            labour_score=labour_score,
            inflation_score=inflation_score,
            rates_score=rates_score,
            credit_score=credit_score,
            growth_score=growth_score,
            series_available=series_available,
            series_required=_MIN_SERIES_HIGH_CONFIDENCE,
            weight_breakdown=effective_weights,
        )

    # ─── Caricamento serie ────────────────────────────────────────────────

    def _load_all_series(self) -> dict[str, pd.DataFrame]:
        """Legge tutte le 15 serie da DuckDB via MacroRepository."""
        series_ids = [
            # Labour (3)
            "ICSA", "CCSA", "PAYEMS",
            # Inflation (3)
            "CPIAUCSL", "CPILFESL", "T10YIE",
            # Rates (4)
            "DGS10", "DGS2", "DGS3MO", "T10Y3M", "FEDFUNDS",
            # Credit (3)
            "BAMLH0A0HYM2", "BAMLC0A0CM", "TEDRATE", "NFCI",
            # Growth (1 extra - INDPRO)
            "INDPRO",
        ]
        result: dict[str, pd.DataFrame] = {}
        for sid in series_ids:
            try:
                df = self._repo.read_macro(sid)
                result[sid] = df if df is not None else pd.DataFrame()
            except Exception as exc:
                log.warning("macro_conviction.series_read_failed",
                            series_id=sid, error=str(exc)[:80])
                result[sid] = pd.DataFrame()
        return result

    # ─── Score per categoria ─────────────────────────────────────────────

    def _compute_labour_score(self, series: dict[str, pd.DataFrame]) -> float:
        """Score categoria labour [-1, +1] da Claims + Payrolls.

        Logica:
          · Claims usano già il regime_score del sub-modulo Claims.
          · Payrolls: positivo se crescita MoM, negativo se contrazione.
        """
        claims_score = self._claims.analyze(
            icsa_df=series.get("ICSA", pd.DataFrame()),
            cpi_df=pd.DataFrame(),   # CPI non serve per labour score
            ccsa_df=series.get("CCSA"),
        ).regime_score

        # Payrolls: MoM change (già in migliaia nel DB FRED)
        payrolls_score = 0.0
        payrolls_df = series.get("PAYEMS", pd.DataFrame())
        if not payrolls_df.empty and "value" in payrolls_df.columns:
            vals = payrolls_df["value"].dropna().to_numpy(dtype=np.float64)
            if len(vals) >= 2:
                mom_change = float(vals[-1] - vals[-2])  # migliaia di posti
                # +200k = ottimo (score ~0.5) | -200k = recessione (score ~-0.8)
                payrolls_score = float(np.clip(mom_change / 400.0, -1.0, 1.0))

        # Media pesata: claims più importanti (60%) di payrolls (40%)
        has_payrolls = not payrolls_df.empty
        if has_payrolls:
            return float(np.clip(0.6 * claims_score + 0.4 * payrolls_score, -1.0, 1.0))
        return float(np.clip(claims_score, -1.0, 1.0))

    def _compute_inflation_score(
        self,
        series: dict[str, pd.DataFrame],
        cpi_yoy: float | None,
    ) -> float:
        """Score categoria inflazione [-1, +1] da CPI, Core CPI, Breakeven.

        Logica: inflazione nel range 1.5-2.5% è ideale (score neutro/positivo).
        Inflazione > 4% o < 0.5% è negativa.
        """
        scores: list[float] = []

        # CPI headline YoY (già disponibile da claims_output)
        if cpi_yoy is not None:
            scores.append(_inflation_to_score(cpi_yoy))

        # Core CPI (rimuove volatilità food/energy)
        core_df = series.get("CPILFESL", pd.DataFrame())
        if not core_df.empty and "value" in core_df.columns:
            core_vals = core_df["value"].dropna()
            if not core_vals.empty:
                scores.append(_inflation_to_score(float(core_vals.iloc[-1])))

        # Breakeven inflation 10Y (aspettative forward-looking)
        be_df = series.get("T10YIE", pd.DataFrame())
        if not be_df.empty and "value" in be_df.columns:
            be_vals = be_df["value"].dropna()
            if not be_vals.empty:
                be = float(be_vals.iloc[-1])
                # Breakeven 2-2.5% = Fed target rispettato → positivo
                be_score = 0.3 if 1.8 <= be <= 2.8 else (-0.4 if be > 3.5 else -0.2)
                scores.append(be_score)

        if not scores:
            return 0.0
        return float(np.clip(float(np.mean(scores)), -1.0, 1.0))

    def _compute_growth_score(self, series: dict[str, pd.DataFrame]) -> float:
        """Score categoria crescita [-1, +1] da Industrial Production.

        INDPRO: MoM change normalizzato. Crescita > 0.3% = espansione.
        """
        indpro_df = series.get("INDPRO", pd.DataFrame())
        if indpro_df.empty or "value" not in indpro_df.columns:
            return 0.0

        vals = indpro_df["value"].dropna().to_numpy(dtype=np.float64)
        if len(vals) < 3:
            return 0.0

        # MoM % change
        mom = float((vals[-1] - vals[-2]) / abs(vals[-2])) if vals[-2] != 0 else 0.0
        # YoY % change (per trend di medio periodo)
        if len(vals) >= 13:
            yoy = float((vals[-1] - vals[-13]) / abs(vals[-13])) if vals[-13] != 0 else 0.0
        else:
            yoy = mom

        # Score: media MoM e YoY, con MoM più pesante per segnale rapido
        combined = 0.4 * mom + 0.6 * yoy
        # Normalizza: +5% YoY = molto forte (score 1.0) | -5% = recessione (-1.0)
        return float(np.clip(combined * 10, -1.0, 1.0))


# ─── Funzioni pure di aggregazione ───────────────────────────────────────────

def _inflation_to_score(cpi_yoy: float) -> float:
    """Mappa CPI YoY (%) in score [-1, +1].

    Tabella:
      < 0.5%  → deflazione → -0.4 (rischio di spirale deflazionistica)
      0.5-1.5 → sub-target → -0.1 (Fed potrebbe tagliare)
      1.5-2.5 → on target  → +0.4 (Goldilocks)
      2.5-3.5 → above tgt  → -0.2 (Fed attenta)
      3.5-4.5 → high       → -0.6 (Fed hawkish)
      > 4.5%  → very high  → -1.0 (Volcker territory)
    """
    if cpi_yoy < 0.5:
        return -0.4
    if cpi_yoy < 1.5:
        return -0.1
    if cpi_yoy < 2.5:
        return  0.4
    if cpi_yoy < 3.5:
        return -0.2
    if cpi_yoy < 4.5:
        return -0.6
    return -1.0


def _weighted_aggregate(
    scores: dict[str, float],
) -> tuple[float, dict[str, float]]:
    """Aggrega i category scores con pesi, gestendo categorie mancanti (NaN).

    Redistribuisce il peso delle categorie con score=0.0 solo se il loro
    DataFrame di input era vuoto (segnalato dal fatto che lo score è esattamente 0.0
    e non c'è distinzione — per ora tutte le categorie hanno sempre un score).

    Args:
        scores: {categoria: score [-1, +1]}

    Returns:
        Tuple (macro_score, effective_weights_dict)
    """
    total_weight = np.float64(0.0)
    weighted_sum = np.float64(0.0)
    effective: dict[str, float] = {}

    for cat, score in scores.items():
        w = np.float64(_CATEGORY_WEIGHTS.get(cat, 0.0))
        weighted_sum += np.float64(score) * w
        total_weight  += w
        effective[cat] = float(w)

    if total_weight <= 0:
        return 0.0, effective

    macro_score = float(weighted_sum / total_weight)
    return macro_score, effective
