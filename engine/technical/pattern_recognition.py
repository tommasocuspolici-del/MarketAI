"""PatternDetector — 8 pattern grafici su OHLCV (numpy vettorizzato).

H&S, Inverse H&S, Double Top/Bottom, Triangoli Asc/Desc/Sym,
Cup & Handle, Flag.

Regola 8: numpy, zero loop su serie temporali.
Regola 2 (SRP): rileva — non persiste (PatternSignalsRepo).
Helper di pivot in engine/technical/pivot_utils.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from engine.technical.pattern_schemas import (
    PatternDetectionConfig,
    PatternResult,
    PatternSignal,
    PatternType,
    load_pattern_config,
)
from engine.technical.pivot_utils import find_pivots, normalised_slope, ts_to_datetime
from shared.logger import get_logger

if TYPE_CHECKING:
    import pandas as pd

__version__ = "9.0.0"
__all__ = ["PatternDetector", "find_pivots"]

log = get_logger(__name__)


class PatternDetector:
    """Rileva automaticamente pattern grafici su OHLCV.

    Uso::
        det = PatternDetector()
        patterns = det.detect(df, ticker="AAPL")
        # list[PatternResult] ordinata per confidence DESC
    """

    def __init__(self, config: PatternDetectionConfig | None = None) -> None:
        self._cfg   = config or load_pattern_config()
        self._order = self._cfg.pivot_order
        self._min   = self._cfg.min_confidence

    def detect(self, df: pd.DataFrame, ticker: str) -> list[PatternResult]:
        """Rileva tutti i pattern sulla serie OHLCV."""
        if df is None or len(df) < 2 * self._order + 3:
            return []
        cc    = "close" if "close" in df.columns else "Close"
        tc    = "ts" if "ts" in df.columns else df.columns[0]
        close = df[cc].to_numpy(dtype=np.float64)
        dates = df[tc].values
        hi, li = find_pivots(close, self._order)
        out: list[PatternResult] = []
        out += self._hs(ticker, close, dates, hi, li, inv=False)
        out += self._hs(ticker, close, dates, hi, li, inv=True)
        out += self._double(ticker, close, dates, hi, li, top=True)
        out += self._double(ticker, close, dates, hi, li, top=False)
        out += self._triangles(ticker, close, dates)
        out += self._flag(ticker, close, dates)
        out += self._cup(ticker, close, dates)
        filtered = [r for r in out if r.confidence >= self._min]
        return sorted(filtered, key=lambda r: r.confidence, reverse=True)

    # ─── Head and Shoulders (+ Inverse) ─────────────────────────────────────

    def _hs(
        self,
        ticker: str,
        close: np.ndarray,
        dates: np.ndarray,
        hi: np.ndarray,
        li: np.ndarray,
        *,
        inv: bool,
    ) -> list[PatternResult]:
        """H&S (inv=False, bearish) o Inverse H&S (inv=True, bullish).

        Per ogni tripla consecutiva di pivot alti (H&S) o bassi (IH&S):
          · Verifica che il pivot centrale domina (testa > spalle o viceversa)
          · Calcola simmetria delle spalle e piattezza della neckline
          · Confidence = weighted(symmetry, flatness)
        """
        pivots, opp = (li, hi) if inv else (hi, li)
        if len(pivots) < 3:
            return []
        cfg, out = self._cfg, []
        for i in range(len(pivots) - 2):
            i1, i2, i3 = int(pivots[i]), int(pivots[i + 1]), int(pivots[i + 2])
            p1, p2, p3 = close[i1], close[i2], close[i3]
            if inv:
                if not (p2 < p1 and p2 < p3):
                    continue
            else:
                if not (p2 > p1 and p2 > p3):
                    continue
            sym = 1.0 - float(abs(p1 - p3) / (abs(p2) + 1e-9))
            if sym < 1.0 - cfg.max_shoulder_asymmetry:
                continue
            o1 = opp[(opp > i1) & (opp < i2)]
            o2 = opp[(opp > i2) & (opp < i3)]
            if not len(o1) or not len(o2):
                continue
            t1_i, t2_i = int(o1[-1]), int(o2[0])
            t1, t2  = close[t1_i], close[t2_i]
            neck    = float((t1 + t2) / 2)
            span    = abs(float(p2) - neck) + 1e-9
            if span / (neck + 1e-9) < cfg.min_head_dominance:
                continue
            nkslope = abs(float(t2) - float(t1)) / (span * max(1, t2_i - t1_i))
            flat    = 1.0 - min(1.0, nkslope / (cfg.max_neckline_slope_ratio + 1e-9))
            conf    = float(np.clip(0.55 * sym + 0.30 * flat + 0.15, 0.0, 1.0))
            tgt     = float(neck + (neck - p2)) if inv else float(neck - (p2 - neck))
            pt      = PatternType.INVERSE_HEAD_AND_SHOULDERS if inv else PatternType.HEAD_AND_SHOULDERS
            sig     = PatternSignal.BULLISH if inv else PatternSignal.BEARISH
            out.append(PatternResult(
                ticker=ticker, pattern_type=pt, signal=sig, confidence=conf,
                start_idx=i1, end_idx=i3,
                start_date=ts_to_datetime(dates[i1]),
                end_date=ts_to_datetime(dates[i3]),
                key_levels={
                    "neckline": round(neck, 4),
                    "target": round(tgt, 4),
                    "head": round(float(p2), 4),
                },
                description=(
                    f"{'Inv ' if inv else ''}H&S: neckline={neck:.2f} target={tgt:.2f}"
                ),
            ))
        return out

    # ─── Double Top / Double Bottom ──────────────────────────────────────────

    def _double(
        self,
        ticker: str,
        close: np.ndarray,
        dates: np.ndarray,
        hi: np.ndarray,
        li: np.ndarray,
        *,
        top: bool,
    ) -> list[PatternResult]:
        """Double Top (bearish) o Double Bottom (bullish).

        Criteri: prossimità dei due estremi < max_price_proximity_pct;
        profondità della valley/picco intermedio > min_valley_depth_pct.
        """
        pivots = hi if top else li
        opp    = li if top else hi
        if len(pivots) < 2:
            return []
        cfg, out = self._cfg, []
        for i in range(len(pivots) - 1):
            i1, i2 = int(pivots[i]), int(pivots[i + 1])
            p1, p2 = close[i1], close[i2]
            mx   = max(abs(p1), abs(p2)) + 1e-9
            prox = float(abs(p1 - p2) / mx)
            if prox > cfg.max_price_proximity_pct:
                continue
            mid = opp[(opp > i1) & (opp < i2)]
            if not len(mid):
                continue
            vp    = float(close[mid[len(mid) // 2]])
            avg   = float((p1 + p2) / 2.0)
            depth = float(abs(avg - vp) / (abs(avg) + 1e-9))
            if depth < cfg.min_valley_depth_pct:
                continue
            conf = float(np.clip(
                1.0 - prox / (cfg.max_price_proximity_pct + 1e-9) * 0.5, 0.5, 0.95
            ))
            pt  = PatternType.DOUBLE_TOP if top else PatternType.DOUBLE_BOTTOM
            sig = PatternSignal.BEARISH if top else PatternSignal.BULLISH
            tgt = vp - (avg - vp) if top else vp + (vp - avg)
            out.append(PatternResult(
                ticker=ticker, pattern_type=pt, signal=sig, confidence=conf,
                start_idx=i1, end_idx=i2,
                start_date=ts_to_datetime(dates[i1]),
                end_date=ts_to_datetime(dates[i2]),
                key_levels={
                    "support": round(vp, 4),
                    "resistance": round(avg, 4),
                    "target": round(tgt, 4),
                },
                description=(
                    f"{'Double Top' if top else 'Double Bottom'}: "
                    f"livello={avg:.2f} target={tgt:.2f}"
                ),
            ))
        return out

    # ─── Triangoli ──────────────────────────────────────────────────────────

    def _triangles(
        self,
        ticker: str,
        close: np.ndarray,
        dates: np.ndarray,
    ) -> list[PatternResult]:
        """Triangolo asc/desc/sym via regressione lineare su pivot (vettorizzata).

        Classificazione per slope di highs e lows:
          · Asc:  slope_lows > ms, |slope_highs| < ft   → BULLISH
          · Desc: slope_highs < -ms, |slope_lows| < ft  → BEARISH
          · Sym:  slope_lows > ms, slope_highs < -ms    → NEUTRAL
        """
        cfg = self._cfg
        w   = cfg.triangle_window_bars
        if len(close) < w:
            return []
        seg     = close[-w:]
        hi, li  = find_pivots(seg, self._order)
        if len(hi) < cfg.min_pivot_count or len(li) < cfg.min_pivot_count:
            return []
        sh = normalised_slope(hi, seg[hi])
        sl = normalised_slope(li, seg[li])
        ft, ms = cfg.flat_slope_threshold, cfg.min_slope_threshold
        if sl > ms and abs(sh) < ft:
            pt   = PatternType.TRIANGLE_ASCENDING
            sig  = PatternSignal.BULLISH
            conf = float(np.clip(0.6 + min(0.3, sl * 10), 0.6, 0.90))
        elif sh < -ms and abs(sl) < ft:
            pt   = PatternType.TRIANGLE_DESCENDING
            sig  = PatternSignal.BEARISH
            conf = float(np.clip(0.6 + min(0.3, abs(sh) * 10), 0.6, 0.90))
        elif sl > ms and sh < -ms:
            pt   = PatternType.TRIANGLE_SYMMETRIC
            sig  = PatternSignal.NEUTRAL
            conf = float(np.clip(0.6 + min(0.25, (sl - sh) * 5), 0.6, 0.85))
        else:
            return []
        apex   = float(np.mean(seg[-5:]))
        h_val  = float(np.max(seg[hi[-1:]])) if len(hi) else apex
        l_val  = float(np.min(seg[li[-1:]])) if len(li) else apex
        height = h_val - l_val
        off    = len(close) - w
        return [PatternResult(
            ticker=ticker, pattern_type=pt, signal=sig, confidence=conf,
            start_idx=off, end_idx=len(close) - 1,
            start_date=ts_to_datetime(dates[off]),
            end_date=ts_to_datetime(dates[-1]),
            key_levels={
                "slope_h": round(sh, 5),
                "slope_l": round(sl, 5),
                "target_bull": round(apex + height, 4),
                "target_bear": round(apex - height, 4),
            },
            description=(
                f"{pt.value.replace('_', ' ').title()} apex≈{apex:.2f}"
            ),
        )]

    # ─── Flag ────────────────────────────────────────────────────────────────

    def _flag(
        self,
        ticker: str,
        close: np.ndarray,
        dates: np.ndarray,
    ) -> list[PatternResult]:
        """Flag bullish/bearish: impulso forte + consolidamento compatto."""
        cfg, n = self._cfg, len(close)
        for pl in range(cfg.min_pole_bars, min(16, n // 3)):
            for cl in range(3, min(cfg.max_consolidation_bars + 1, n - pl)):
                ps = n - pl - cl
                if ps < 0:
                    break
                pole = close[ps: ps + pl]
                cons = close[ps + pl: ps + pl + cl]
                move = float((pole[-1] - pole[0]) / (abs(pole[0]) + 1e-9))
                if abs(move) < cfg.min_pole_move_pct:
                    continue
                cr = float(
                    (cons.max() - cons.min())
                    / (abs(move) * abs(float(pole[0])) + 1e-9)
                )
                if cr > 0.5:
                    continue
                sig  = PatternSignal.BULLISH if move > 0 else PatternSignal.BEARISH
                conf = float(np.clip(0.60 + 0.30 * (1 - cr), 0.60, 0.90))
                tgt  = float(close[-1] + (pole[-1] - pole[0]))
                ei   = ps + pl + cl - 1
                return [PatternResult(
                    ticker=ticker,
                    pattern_type=PatternType.FLAG,
                    signal=sig,
                    confidence=conf,
                    start_idx=ps,
                    end_idx=ei,
                    start_date=ts_to_datetime(dates[ps]),
                    end_date=ts_to_datetime(dates[ei]),
                    key_levels={
                        "pole_move_pct": round(move, 4),
                        "target": round(tgt, 4),
                    },
                    description=(
                        f"{'Bull' if sig == PatternSignal.BULLISH else 'Bear'} Flag "
                        f"move={move:.1%} target={tgt:.2f}"
                    ),
                )]
        return []

    # ─── Cup and Handle ──────────────────────────────────────────────────────

    def _cup(
        self,
        ticker: str,
        close: np.ndarray,
        dates: np.ndarray,
    ) -> list[PatternResult]:
        """Cup & Handle: U-shape + piccola pausa finale (bullish)."""
        cfg = self._cfg
        n   = len(close)
        ce  = n - 3
        cs  = max(0, ce - cfg.min_cup_bars * 2)
        seg = close[cs:ce]
        if len(seg) < cfg.min_cup_bars:
            return []
        mv     = float(seg[int(np.argmin(seg))])
        lv, rv = float(seg[0]), float(seg[-1])
        depth  = float((lv - mv) / (abs(lv) + 1e-9))
        sym    = 1.0 - float(abs(lv - rv) / (abs(lv) + 1e-9))
        if not (cfg.min_cup_depth_pct <= depth <= cfg.max_cup_depth_pct):
            return []
        if sym < 0.80:
            return []
        handle = close[ce:]
        if len(handle) < 2:
            return []
        hr = float((rv - float(handle.min())) / (abs(rv) + 1e-9))
        if hr > cfg.max_handle_retracement_pct:
            return []
        conf = float(
            np.clip(0.55 * sym + 0.25 * (1 - abs(depth - 0.2) / 0.2) + 0.20, 0.60, 0.92)
        )
        tgt = float(rv + (rv - mv))
        return [PatternResult(
            ticker=ticker,
            pattern_type=PatternType.CUP_AND_HANDLE,
            signal=PatternSignal.BULLISH,
            confidence=conf,
            start_idx=cs,
            end_idx=n - 1,
            start_date=ts_to_datetime(dates[cs]),
            end_date=ts_to_datetime(dates[-1]),
            key_levels={
                "cup_bottom": round(mv, 4),
                "resistance": round(rv, 4),
                "target": round(tgt, 4),
            },
            description=(
                f"Cup&Handle fondo={mv:.2f} resist={rv:.2f} target={tgt:.2f}"
            ),
        )]
