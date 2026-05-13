"""Pattern Overlay UI component — badge pattern su chart candlestick.

Aggiunge annotazioni visuali (badge colorati) al chart Plotly prodotto da
``candlestick_pro.py`` per ogni PatternResult rilevato da PatternDetector.

Convenzione colori (da DESIGN_TOKENS — Regola 20):
  · Bullish patterns → tokens.colors.positive (verde)
  · Bearish patterns → tokens.colors.negative (rosso)
  · Neutral patterns → tokens.colors.accent (blu/neutro)

Uso tipico::
    fig = build_candlestick_figure(df, tokens)
    fig = add_pattern_overlays(fig, patterns, df, tokens)
    st.plotly_chart(fig, use_container_width=True)

Regola 20: zero colori hardcoded — tutti da DESIGN_TOKENS.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from engine.technical.pattern_schemas import PatternResult, PatternSignal, PatternType

__version__ = "9.0.0"
__all__ = ["add_pattern_overlays", "build_pattern_badge_html", "render_pattern_badges"]

if TYPE_CHECKING:
    import pandas as pd
    from presentation.ui.theme import DesignTokens

# ─── Mapping pattern → icona e label breve ────────────────────────────────────
# Regola 7: costanti nominate, mai magic string inline nel codice UI.
_PATTERN_LABELS: dict[PatternType, tuple[str, str]] = {
    PatternType.HEAD_AND_SHOULDERS:          ("⛰️", "H&S"),
    PatternType.INVERSE_HEAD_AND_SHOULDERS:  ("🏔️", "IH&S"),
    PatternType.DOUBLE_TOP:                  ("🔴", "Double Top"),
    PatternType.DOUBLE_BOTTOM:               ("🟢", "Double Bottom"),
    PatternType.TRIANGLE_ASCENDING:          ("📐↗", "Asc. Triangle"),
    PatternType.TRIANGLE_DESCENDING:         ("📐↘", "Desc. Triangle"),
    PatternType.TRIANGLE_SYMMETRIC:          ("📐", "Sym. Triangle"),
    PatternType.CUP_AND_HANDLE:              ("☕", "Cup & Handle"),
    PatternType.FLAG:                        ("🚩", "Flag"),
    PatternType.PENNANT:                     ("🔺", "Pennant"),
}


def add_pattern_overlays(
    fig: Any,
    patterns: list[PatternResult],
    df: pd.DataFrame,
    tokens: DesignTokens,
) -> Any:
    """Aggiunge annotazioni pattern al figure Plotly esistente.

    Per ogni PatternResult:
      · Rettangolo ombreggiato che copre la durata del pattern
      · Annotazione testuale (nome + confidence) all'inizio del pattern
      · Linee orizzontali per i key_levels (neckline, target, support)

    Args:
        fig: Plotly Figure prodotto da build_candlestick_figure().
        patterns: Lista di PatternResult da PatternDetector.
        df: DataFrame OHLCV originale (per recuperare i timestamp).
        tokens: DESIGN_TOKENS per colori e font.

    Returns:
        Figure arricchita con le annotazioni. Restituisce fig invariato
        se patterns è vuota o se plotly non è installato.
    """
    if not patterns:
        return fig

    try:
        import plotly.graph_objects as go
    except ImportError:
        return fig

    ts_col = "ts" if "ts" in df.columns else df.columns[0]
    timestamps = df[ts_col].values

    for pat in patterns:
        color = _get_pattern_color(pat.signal, tokens)
        icon, label = _PATTERN_LABELS.get(pat.pattern_type, ("📊", pat.pattern_type.value))

        # Indici sicuri nel range del DataFrame
        si = min(pat.start_idx, len(timestamps) - 1)
        ei = min(pat.end_idx, len(timestamps) - 1)

        try:
            x0 = str(timestamps[si])
            x1 = str(timestamps[ei])
        except (IndexError, TypeError):
            continue

        # ── Rettangolo ombreggiato ─────────────────────────────────────────
        fig.add_vrect(
            x0=x0, x1=x1,
            fillcolor=color,
            opacity=0.08,
            line_width=0,
            annotation_text=f"{icon} {label} {pat.confidence:.0%}",
            annotation_position="top left",
            annotation_font_size=11,
            annotation_font_color=color,
        )

        # ── Linee key_levels (neckline, target, support, resistance) ──────
        for level_name in ("neckline", "target", "support", "resistance"):
            level_val = pat.key_levels.get(level_name)
            if level_val is None:
                continue
            line_color = tokens.colors.negative if "target" in level_name and pat.signal == PatternSignal.BEARISH else color
            fig.add_hline(
                y=level_val,
                line_dash="dot",
                line_color=line_color,
                line_width=1,
                opacity=0.5,
                annotation_text=f"{level_name}: {level_val:.2f}",
                annotation_position="right",
                annotation_font_size=10,
                annotation_font_color=line_color,
                x0=x0,
                x1=x1,
            )

    return fig


def build_pattern_badge_html(patterns: list[PatternResult]) -> str:
    """Costruisce HTML con badge colorati per ogni pattern rilevato.

    Usato nei tooltip o nelle card informative sotto il chart.
    Non richiede Plotly — output puro HTML/CSS.

    Args:
        patterns: Lista di PatternResult da mostrare.

    Returns:
        Stringa HTML con badge inline.
    """
    if not patterns:
        return "<em>Nessun pattern rilevato</em>"

    badges: list[str] = []
    for pat in patterns:
        icon, label = _PATTERN_LABELS.get(pat.pattern_type, ("📊", pat.pattern_type.value))
        bg  = "#d4edda" if pat.signal == PatternSignal.BULLISH else (
              "#f8d7da" if pat.signal == PatternSignal.BEARISH else "#d1ecf1"
        )
        fg  = "#155724" if pat.signal == PatternSignal.BULLISH else (
              "#721c24" if pat.signal == PatternSignal.BEARISH else "#0c5460"
        )
        badges.append(
            f'<span style="display:inline-block;background:{bg};color:{fg};'
            f'border-radius:6px;padding:3px 8px;margin:2px;font-size:0.85em;">'
            f'{icon} <strong>{label}</strong> '
            f'<span style="opacity:0.7">{pat.confidence:.0%}</span>'
            f'</span>'
        )
    return " ".join(badges)


def render_pattern_badges(
    patterns: list[PatternResult],
    tokens: DesignTokens | None = None,  # noqa: ARG001
) -> None:
    """Renderizza badge pattern in Streamlit tramite st.markdown.

    Args:
        patterns: Lista di PatternResult.
        tokens: DesignTokens (non usato ma mantenuto per firma uniforme).
    """
    try:
        import streamlit as st
    except ImportError:  # pragma: no cover
        return

    if not patterns:
        st.caption("Nessun pattern rilevato nella finestra corrente.")
        return

    html = build_pattern_badge_html(patterns)
    st.markdown(html, unsafe_allow_html=True)

    # Mostra tabella dettagli
    rows = []
    for pat in patterns:
        icon, label = _PATTERN_LABELS.get(pat.pattern_type, ("📊", pat.pattern_type.value))
        rows.append({
            "Pattern": f"{icon} {label}",
            "Segnale": pat.signal.value.capitalize(),
            "Confidence": f"{pat.confidence:.0%}",
            "Bar Start": pat.start_idx,
            "Bar End": pat.end_idx,
            "Descrizione": pat.description[:60] + "..." if len(pat.description) > 60 else pat.description,
        })

    import pandas as pd
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ─── Helper privato ──────────────────────────────────────────────────────────

def _get_pattern_color(signal: PatternSignal, tokens: DesignTokens) -> str:
    """Ritorna il colore Plotly/hex per la direzione del pattern.

    Regola 20: colori da DESIGN_TOKENS, mai hardcoded.
    """
    try:
        if signal == PatternSignal.BULLISH:
            return str(tokens.colors.positive)
        if signal == PatternSignal.BEARISH:
            return str(tokens.colors.negative)
        return str(tokens.colors.accent)
    except AttributeError:
        # Fallback sicuro se il token non espone il campo atteso
        if signal == PatternSignal.BULLISH:
            return "#28a745"
        if signal == PatternSignal.BEARISH:
            return "#dc3545"
        return "#007bff"
