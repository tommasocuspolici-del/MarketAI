# ruff: noqa: N999
"""H1 — Market Health Matrix (v11.0).

Vista a matrice regime: una griglia dove ogni cella è un indicatore con
semaforo (🟢/🟡/🔴), valore corrente e regime label — raggruppati per
categoria. In cima: Health Score 0-100 derivato dal composite_score.

Tutte le letture da DuckDB (Regola 12: zero API call in questa pagina).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__version__ = "11.0.0"
__all__ = ["body_h1_market_health_matrix"]

# ─── Soglie semaforo (Regola 7 — no magic numbers inline) ────────────────────

_VIX_GREEN_MAX      = 18.0
_VIX_YELLOW_MAX     = 26.0
_CREDIT_HY_GREEN    = 400.0   # bps HY OAS
_CREDIT_HY_YELLOW   = 550.0
_CREDIT_TED_GREEN   = 50.0    # bps TED spread
_CREDIT_TED_YELLOW  = 100.0
_PCR_GREEN_MIN      = 0.6     # put/call ratio — contrarian: elevato è bearish
_PCR_GREEN_MAX      = 1.0
_PCR_YELLOW_MAX     = 1.4
_CAPE_GREEN_MAX     = 25.0    # Shiller CAPE
_CAPE_YELLOW_MAX    = 35.0
_MACRO_SCORE_GREEN  = 0.2     # macro conviction score [-1, +1]
_MACRO_SCORE_RED    = -0.2


# ─── Data containers ──────────────────────────────────────────────────────────

@dataclass
class HealthCell:
    """Singola cella della matrice."""
    name: str
    value_str: str          # es. "18.2", "420 bps", "FLAT"
    color: str              # "green" | "yellow" | "red" | "gray"
    regime_label: str       # es. "ELEVATED", "MODERATE", "EXPANSION"
    detail: str = ""        # riga aggiuntiva opzionale


@dataclass
class HealthCategory:
    """Gruppo di celle (colonna della matrice)."""
    icon: str
    title: str
    cells: list[HealthCell]


@dataclass
class HealthMatrixData:
    """Dati completi per la pagina H1."""
    health_score: int                   # 0–100
    health_label: str                   # es. "MODERATAMENTE RIALZISTA"
    composite_score: float              # [-1, +1]
    categories: list[HealthCategory]
    is_degraded: bool = False


# ─── Public loaders (testabili senza Streamlit) ───────────────────────────────

def load_health_matrix() -> HealthMatrixData:
    """Carica tutti i dati dal DuckDB e costruisce la matrice.

    Legge da: engine_composite_signal, yield_curve_snapshots,
    credit_spread_signals, vix_signals, sentiment_observations,
    pe_metrics, vol_surface_snapshots, putcall_ratio_daily,
    earnings_calendar.

    Returns:
        HealthMatrixData pronto per il rendering.
    """
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
    except Exception:
        return _degraded_matrix()

    composite = _load_composite(db)
    yield_curve = _load_yield_curve(db)
    credit = _load_credit(db)
    vix = _load_vix(db)
    vol_surface = _load_vol_surface(db)
    sentiment = _load_sentiment(db)
    valuation = _load_valuation(db)
    earnings = _load_upcoming_earnings(db)
    options = _load_options_flow(db)
    labour = _load_labour(composite)

    score = composite.get("composite_score", 0.0) if composite else 0.0
    health_score = _to_health_score(score)

    categories = [
        HealthCategory("🌐", "MACRO", [
            _yield_curve_cell(yield_curve),
            _macro_conviction_cell(composite),
        ]),
        HealthCategory("📉", "VOLATILITÀ", [
            _vix_cell(vix),
            _vol_surface_cell(vol_surface),
        ]),
        HealthCategory("💳", "CREDITO", [
            _hy_oas_cell(credit),
            _ted_spread_cell(credit),
        ]),
        HealthCategory("👷", "LABOUR", [
            _labour_cell(labour),
        ]),
        HealthCategory("😊", "SENTIMENT", [
            _sentiment_cell(sentiment),
        ]),
        HealthCategory("💰", "VALUATION", [
            _cape_cell(valuation),
        ]),
        HealthCategory("📅", "EARNINGS", [
            _earnings_cell(earnings),
        ]),
        HealthCategory("🎯", "OPTIONS", [
            _pcr_cell(options),
            _iv_skew_cell(options),
        ]),
    ]

    return HealthMatrixData(
        health_score=health_score,
        health_label=_health_label(health_score),
        composite_score=score,
        categories=categories,
    )


# ─── Individual DB loaders ────────────────────────────────────────────────────

def _load_composite(db) -> dict | None:
    try:
        rows = db.query(
            "SELECT composite_score, macro_component, labour_market_component, "
            "recommended_action, confidence, regime, claims_regime, yield_curve_regime "
            "FROM engine_composite_signal ORDER BY computed_at DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "composite_score": _f(r[0]),
            "macro_component": _f(r[1]),
            "labour_component": _f(r[2]),
            "action": r[3], "confidence": r[4],
            "regime": r[5], "claims_regime": r[6], "yield_curve_regime": r[7],
        }
    except Exception:
        return None


def _load_yield_curve(db) -> dict | None:
    try:
        rows = db.query(
            "SELECT spread_10y_2y, curve_regime, recession_prob_12m "
            "FROM yield_curve_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {"spread": _f(r[0]), "regime": r[1], "recession_prob": _f(r[2])}
    except Exception:
        return None


def _load_credit(db) -> dict | None:
    try:
        rows = db.query(
            "SELECT hy_oas, ted_spread, stress_level, stress_score "
            "FROM credit_spread_signals ORDER BY computed_at DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {"hy_oas": _f(r[0]), "ted_spread": _f(r[1]),
                "stress_level": r[2], "stress_score": _f(r[3])}
    except Exception:
        return None


def _load_vix(db) -> dict | None:
    try:
        rows = db.query(
            "SELECT vix_level, vix_zscore, regime "
            "FROM vix_signals ORDER BY computed_at DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {"level": _f(r[0]), "zscore": _f(r[1]), "regime": r[2]}
    except Exception:
        return None


def _load_vol_surface(db) -> dict | None:
    try:
        rows = db.query(
            "SELECT surface_regime, contango_pct, skew_index "
            "FROM vol_surface_snapshots ORDER BY snapshot_at DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {"regime": r[0], "contango_pct": _f(r[1]), "skew_index": _f(r[2])}
    except Exception:
        return None


def _load_sentiment(db) -> dict | None:
    try:
        rows = db.query(
            "SELECT score FROM sentiment_observations "
            "WHERE source = 'cnn_fg' ORDER BY ts DESC LIMIT 1"
        )
        if not rows:
            return None
        return {"cnn_fg": _f(rows[0][0])}
    except Exception:
        return None


def _load_valuation(db) -> dict | None:
    try:
        rows = db.query(
            "SELECT shiller_cape, cape_zscore, trailing_pe "
            "FROM pe_metrics ORDER BY metric_date DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {"cape": _f(r[0]), "cape_zscore": _f(r[1]), "pe_trailing": _f(r[2])}
    except Exception:
        return None


def _load_upcoming_earnings(db) -> list[dict]:
    try:
        from datetime import date, timedelta
        today = date.today()
        cutoff = today + timedelta(days=7)
        rows = db.query(
            "SELECT ticker, company_name, report_date, report_time, eps_estimate "
            "FROM earnings_calendar "
            "WHERE report_date >= ? AND report_date <= ? "
            "ORDER BY report_date LIMIT 5",
            [today, cutoff],
        )
        return [
            {"ticker": r[0], "company_name": r[1], "report_date": r[2],
             "report_time": r[3], "eps_estimate": _f(r[4])}
            for r in rows
        ] if rows else []
    except Exception:
        return []


def _load_options_flow(db) -> dict | None:
    try:
        rows = db.query(
            "SELECT put_call_ratio, iv_skew_25d, iv_atm "
            "FROM putcall_ratio_daily ORDER BY date DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {"pcr": _f(r[0]), "iv_skew": _f(r[1]), "iv_atm": _f(r[2])}
    except Exception:
        return None


def _load_labour(composite: dict | None) -> dict | None:
    if composite is None:
        return None
    comp = composite.get("labour_component")
    regime = composite.get("claims_regime")
    return {"component": comp, "regime": regime} if comp is not None else None


# ─── Cell builders ────────────────────────────────────────────────────────────

def _yield_curve_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("Yield Curve", "N/D", "gray", "—")
    regime = (d.get("regime") or "unknown").upper()
    spread = d.get("spread")
    spread_str = f"{spread:+.0f}bp" if spread is not None else "—"
    color = _yield_curve_color(regime)
    return HealthCell("Yield Curve", regime, color, spread_str,
                      detail=f"10Y-2Y: {spread_str}")


def _macro_conviction_cell(composite: dict | None) -> HealthCell:
    if composite is None:
        return HealthCell("Macro Conv.", "N/D", "gray", "—")
    score = composite.get("macro_component", 0.0) or 0.0
    color = (
        "green" if score >= _MACRO_SCORE_GREEN else
        "red"   if score <= _MACRO_SCORE_RED   else
        "yellow"
    )
    return HealthCell("Macro Conv.", f"{score:+.2f}", color,
                      "RIALZISTA" if color == "green" else
                      "RIBASSISTA" if color == "red" else "NEUTRO")


def _vix_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("VIX", "N/D", "gray", "—")
    level = d.get("level")
    zscore = d.get("zscore")
    if level is None:
        return HealthCell("VIX", "N/D", "gray", "—")
    color = (
        "green" if level < _VIX_GREEN_MAX else
        "red"   if level > _VIX_YELLOW_MAX else
        "yellow"
    )
    z_str = f"z={zscore:+.1f}" if zscore is not None else ""
    return HealthCell("VIX", f"{level:.1f}", color,
                      (d.get("regime") or "unknown").upper(), detail=z_str)


def _vol_surface_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("Vol Surface", "N/D", "gray", "—")
    regime = (d.get("regime") or "unknown").upper()
    color = "green" if "CONTANGO" in regime else "yellow" if "FLAT" in regime else "red"
    return HealthCell("Vol Surface", regime, color, regime)


def _hy_oas_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("HY OAS", "N/D", "gray", "—")
    hy = d.get("hy_oas")
    if hy is None:
        return HealthCell("HY OAS", "N/D", "gray", "—")
    color = (
        "green" if hy < _CREDIT_HY_GREEN  else
        "red"   if hy > _CREDIT_HY_YELLOW else
        "yellow"
    )
    stress = (d.get("stress_level") or "unknown").upper()
    return HealthCell("HY OAS", f"{hy:.0f} bps", color, stress)


def _ted_spread_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("TED Spread", "N/D", "gray", "—")
    ted = d.get("ted_spread")
    if ted is None:
        return HealthCell("TED Spread", "N/D", "gray", "—")
    color = (
        "green" if ted < _CREDIT_TED_GREEN  else
        "red"   if ted > _CREDIT_TED_YELLOW else
        "yellow"
    )
    return HealthCell("TED Spread", f"{ted:.0f} bps", color,
                      "BASSO" if color == "green" else
                      "ALTO"  if color == "red"   else "MODERATO")


def _labour_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("Labour", "N/D", "gray", "—")
    comp = d.get("component", 0.0)
    regime = (d.get("regime") or "unknown").upper()
    color = "green" if comp >= 0.1 else "red" if comp <= -0.1 else "yellow"
    return HealthCell("Labour", regime, color, f"score: {comp:+.2f}")


def _sentiment_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("CNN F&G", "N/D", "gray", "—")
    score = d.get("cnn_fg")
    if score is None:
        return HealthCell("CNN F&G", "N/D", "gray", "—")
    pct = int(score * 100) if score <= 1.0 else int(score)
    label = (
        "EXTREME GREED" if pct >= 75 else
        "GREED"         if pct >= 55 else
        "NEUTRAL"       if pct >= 45 else
        "FEAR"          if pct >= 25 else
        "EXTREME FEAR"
    )
    color = "red" if pct >= 75 else "yellow" if pct >= 55 else "green" if pct <= 25 else "yellow"
    return HealthCell("CNN F&G", str(pct), color, label)


def _cape_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("Shiller CAPE", "N/D", "gray", "—")
    cape = d.get("cape")
    if cape is None:
        return HealthCell("Shiller CAPE", "N/D", "gray", "—")
    color = (
        "green" if cape < _CAPE_GREEN_MAX  else
        "red"   if cape > _CAPE_YELLOW_MAX else
        "yellow"
    )
    label = (
        "CHEAP"      if color == "green"  else
        "EXPENSIVE"  if color == "red"    else
        "FAIR"
    )
    return HealthCell("Shiller CAPE", f"{cape:.1f}x", color, label)


def _earnings_cell(upcoming: list[dict]) -> HealthCell:
    if not upcoming:
        return HealthCell("Earnings 7gg", "Nessuno", "gray", "—")
    count = len(upcoming)
    first = upcoming[0]
    ticker = first.get("ticker", "?")
    d = first.get("report_date")
    time_tag = first.get("report_time") or ""
    detail = f"{ticker} {d} {time_tag}".strip()
    return HealthCell("Earnings 7gg", f"{count} rilasci", "yellow", detail)


def _pcr_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("P/C Ratio", "N/D", "gray", "—")
    pcr = d.get("pcr")
    if pcr is None:
        return HealthCell("P/C Ratio", "N/D", "gray", "—")
    color = (
        "green" if _PCR_GREEN_MIN <= pcr <= _PCR_GREEN_MAX else
        "yellow" if pcr <= _PCR_YELLOW_MAX else
        "red"
    )
    label = (
        "NEUTRO"       if _PCR_GREEN_MIN <= pcr <= _PCR_GREEN_MAX else
        "BEARISH FLOW" if pcr > _PCR_YELLOW_MAX else
        "BULLISH FLOW"
    )
    return HealthCell("P/C Ratio", f"{pcr:.2f}", color, label)


def _iv_skew_cell(d: dict | None) -> HealthCell:
    if d is None:
        return HealthCell("IV Skew 25d", "N/D", "gray", "—")
    skew = d.get("iv_skew")
    if skew is None:
        return HealthCell("IV Skew 25d", "N/D", "gray", "—")
    pct = skew * 100
    color = "red" if pct > 5.0 else "yellow" if pct > 2.0 else "green"
    label = "PUT PREMIUM" if color == "red" else "SKEW ELEVATO" if color == "yellow" else "SKEW NORMALE"
    return HealthCell("IV Skew 25d", f"{pct:+.1f}%", color, label)


def _yield_curve_color(regime: str) -> str:
    if "STEEP" in regime or "NORMAL" in regime:
        return "green"
    if "FLAT" in regime:
        return "yellow"
    return "red"  # INVERTED


# ─── Score / label helpers ────────────────────────────────────────────────────

def _to_health_score(composite_score: float) -> int:
    """Converte composite_score [-1, +1] in Health Score [0, 100]."""
    return max(0, min(100, round((composite_score + 1.0) / 2.0 * 100)))


def _health_label(score: int) -> str:
    if score >= 70:
        return "FORTEMENTE RIALZISTA"
    if score >= 55:
        return "MODERATAMENTE RIALZISTA"
    if score >= 45:
        return "NEUTRO"
    if score >= 30:
        return "MODERATAMENTE RIBASSISTA"
    return "FORTEMENTE RIBASSISTA"


def _degraded_matrix() -> HealthMatrixData:
    return HealthMatrixData(
        health_score=50,
        health_label="N/D",
        composite_score=0.0,
        categories=[],
        is_degraded=True,
    )


# ─── Type helper ─────────────────────────────────────────────────────────────

def _f(val: Any) -> float | None:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ─── Streamlit body ───────────────────────────────────────────────────────────

def body_h1_market_health_matrix(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🏥 Market Health Matrix")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="h1_refresh"):
            st.cache_data.clear()
            st.rerun()

    data = _load_matrix_cached(st)

    # ── Health Score bar ──────────────────────────────────────────────────────
    score_color = (
        "#22c55e" if data.health_score >= 60 else
        "#ef4444" if data.health_score < 40  else
        "#f59e0b"
    )
    action_icon = (
        "🟢" if data.health_score >= 60 else
        "🔴" if data.health_score < 40  else
        "🟡"
    )
    st.markdown(
        f"""
        <div style="background:#1e293b;border-radius:12px;padding:16px 20px;
                    margin-bottom:20px;border-left:4px solid {score_color}">
          <div style="font-size:0.85rem;color:#94a3b8;margin-bottom:4px">
            MARKET HEALTH SCORE
          </div>
          <div style="font-size:2rem;font-weight:700;color:{score_color}">
            {action_icon} {data.health_score}/100
          </div>
          <div style="font-size:0.9rem;color:#cbd5e1;margin-top:4px">
            {data.health_label}
            &nbsp;·&nbsp; composite: {data.composite_score:+.3f}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if data.is_degraded:
        st.warning("⚠️ Dati non disponibili. Eseguire la pipeline di calcolo segnali.")
        return

    if not data.categories:
        st.info("Nessun dato. Avviare la pipeline di fetch e calcolo.")
        return

    # ── Matrice 3 colonne ─────────────────────────────────────────────────────
    _COLOR_CSS = {
        "green":  ("#16a34a", "#dcfce7"),
        "yellow": ("#ca8a04", "#fef9c3"),
        "red":    ("#dc2626", "#fee2e2"),
        "gray":   ("#64748b", "#f1f5f9"),
    }

    def _render_cell(cell: HealthCell) -> str:
        fg, bg = _COLOR_CSS.get(cell.color, _COLOR_CSS["gray"])
        detail_html = (
            f'<div style="font-size:0.72rem;color:#64748b;margin-top:2px">{cell.detail}</div>'
            if cell.detail else ""
        )
        return (
            f'<div style="background:{bg};border-radius:8px;padding:10px 12px;'
            f'margin-bottom:8px;border-left:3px solid {fg}">'
            f'<div style="font-size:0.75rem;color:#475569;font-weight:600">'
            f'{cell.name}</div>'
            f'<div style="font-size:1.1rem;font-weight:700;color:{fg}">'
            f'{cell.value_str}</div>'
            f'<div style="font-size:0.78rem;color:{fg};opacity:0.85">'
            f'{cell.regime_label}</div>'
            f'{detail_html}'
            f'</div>'
        )

    # Raggruppa in righe di 3 categorie
    cats = data.categories
    for row_start in range(0, len(cats), 3):
        row_cats = cats[row_start: row_start + 3]
        cols = st.columns(len(row_cats))
        for col, cat in zip(cols, row_cats):
            with col:
                st.markdown(f"**{cat.icon} {cat.title}**")
                cells_html = "".join(_render_cell(c) for c in cat.cells)
                st.markdown(cells_html, unsafe_allow_html=True)

    st.caption(
        "Dati letti da DuckDB locale · "
        "Premere 🔄 Aggiorna per forzare il ricalcolo dei segnali"
    )


def _load_matrix_cached(st):  # pragma: no cover
    from presentation.ui.cache_policy import CACHE_TTL

    @st.cache_data(ttl=CACHE_TTL.SIGNALS)
    def _inner():
        return load_health_matrix()

    return _inner()
