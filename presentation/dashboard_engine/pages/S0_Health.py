# ruff: noqa: N999
"""S0 — Health Monitor (v8.2.0).

7-tab dashboard di sistema:
  Tab 1: Sorgenti Dati     — API ping live + stato .env + DataSourceManager
  Tab 2: Motori Analitici  — SignalRegistry snapshot
  Tab 3: Signal Quality    — IC per ogni segnale (AlphaDecayMonitor)
  Tab 4: LLM Status        — Ollama status + configurazione
  Tab 5: News & IB         — News Engine + IB Forecast stage
  Tab 6: Scheduler         — Job status
  Tab 7: System Log        — Ultimi 50 eventi strutturati

Design: ogni funzione _load_*() è pura e testabile senza Streamlit.
Ogni funzione _render_*() è pragma: no cover.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from presentation.ui.components import EmptyState, StatusDot
from presentation.ui.layout import setup_page
from presentation.ui.session_keys import SK

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"
__all__ = ["body_s0_health"]


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SignalQualityRow:
    name: str
    value: float | None
    ic_estimate: float | None
    quality_flag: str          # "ok" | "low_ic" | "insufficient_data" | "stale"
    observation_count: int
    is_stale: bool


@dataclass
class ApiStatusRow:
    name: str
    state: str                 # "ONLINE" | "OFFLINE" | "DEGRADED" | "NO_API_KEY"
    latency_ms: float | None
    has_api_key: bool
    message: str


@dataclass
class CircuitBreakerRow:
    name: str
    state: str                 # "closed" | "open" | "half_open"
    failure_count: int


@dataclass
class SystemSnapshot:
    api_rows: list[ApiStatusRow] = field(default_factory=list)
    signal_rows: list[SignalQualityRow] = field(default_factory=list)
    cb_rows: list[CircuitBreakerRow] = field(default_factory=list)
    system_status: str = "UNKNOWN"   # "OPERATIONAL" | "DEGRADED" | "DOWN"


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders — pure, testable without Streamlit
# ─────────────────────────────────────────────────────────────────────────────

def _load_signal_quality() -> list[SignalQualityRow]:
    """Load current signal values and IC quality from SignalRegistry + AlphaDecayMonitor."""
    from shared.signal_registry import get_signal_registry
    from shared.alpha_decay_monitor import AlphaDecayMonitor

    registry = get_signal_registry()
    monitor = AlphaDecayMonitor()
    rows: list[SignalQualityRow] = []

    for name in registry.all_signals():
        signal = registry.get(name)
        entry_stale = name in registry.stale_signals()

        try:
            ic, flag = monitor.check_decay(name)
        except Exception:
            ic, flag = None, "insufficient_data"

        obs_count = 0
        try:
            obs_count = monitor.observation_count(name)
        except Exception:
            pass

        rows.append(SignalQualityRow(
            name=name,
            value=signal.value if signal else None,
            ic_estimate=ic,
            quality_flag=flag if not entry_stale else "stale",
            observation_count=obs_count,
            is_stale=entry_stale,
        ))

    return sorted(rows, key=lambda r: r.name)


def _load_circuit_breakers() -> list[CircuitBreakerRow]:
    """Load state of known circuit breakers."""
    from shared.resilience.circuit_breaker import get_circuit_breaker, CircuitBreakerState

    known = ["yfinance", "fred", "finnhub", "alpha_vantage", "duckdb"]
    rows: list[CircuitBreakerRow] = []
    for name in known:
        try:
            cb = get_circuit_breaker(name)
            stats = cb.stats()
            failure_count = getattr(stats, "failure_count", 0)
            rows.append(CircuitBreakerRow(
                name=name,
                state=cb.state.value,
                failure_count=failure_count,
            ))
        except Exception:
            rows.append(CircuitBreakerRow(name=name, state="unknown", failure_count=0))
    return rows


def _load_ollama_status() -> dict:
    """Check Ollama availability via HTTP. Returns status dict."""
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resp:
            import json
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"running": True, "models": models, "error": None}
    except Exception as exc:
        return {"running": False, "models": [], "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Renderers — Streamlit (pragma: no cover)
# ─────────────────────────────────────────────────────────────────────────────

def _render_tab_sources(st) -> None:  # pragma: no cover
    """Tab 1 — Sorgenti Dati: API ping + env status + circuit breakers."""
    from engine.market_data.hardening.api_health_checker import ApiHealthChecker
    from shared.env_loader import get_api_key_statuses, load_environment

    # ── Env file ───────────────────────────────────────────────────────────
    st.markdown("### Stato file .env")
    report = load_environment()
    if not report.loaded_successfully:
        st.error(
            "❌ Nessun file `.env` trovato. Crea il file: `cp .env.example .env`"
        )
    else:
        st.success(
            f"✅ Caricato: `{report.dotenv_path}` ({report.loaded_count} variabili)"
        )

    statuses = get_api_key_statuses()
    key_rows = [
        {
            "API": s.name,
            "Variabile": s.env_var,
            "Stato": (
                "✅ Configurata" if s.is_usable else
                "⚠️ Placeholder" if s.is_placeholder else
                "❌ Mancante"
            ),
        }
        for s in statuses
    ]
    st.dataframe(key_rows, use_container_width=True, hide_index=True)

    # ── API ping ───────────────────────────────────────────────────────────
    st.markdown("### Ping API live")
    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("🔄 Pinga ora", key="s0_ping_now"):
            with st.spinner("Ping in corso..."):
                checker = ApiHealthChecker(timeout=5.0)
                st.session_state[SK.API_HEALTH_RESULTS] = checker.check_all()
            st.rerun()

    if SK.API_HEALTH_RESULTS not in st.session_state or st.session_state[SK.API_HEALTH_RESULTS] is None:
        with st.spinner("Verifica sorgenti API..."):
            checker = ApiHealthChecker(timeout=5.0)
            st.session_state[SK.API_HEALTH_RESULTS] = checker.check_all()

    statuses_api = st.session_state[SK.API_HEALTH_RESULTS]
    ping_cols = st.columns(min(len(statuses_api), 4))
    for i, s in enumerate(statuses_api):
        dot_status = {
            "ONLINE": "ok", "DEGRADED": "degraded",
            "OFFLINE": "error", "NO_API_KEY": "degraded",
        }.get(s.state, "unknown")
        latency = f"{s.latency_ms:.0f}ms" if s.latency_ms else "—"
        with ping_cols[i % 4]:
            StatusDot(
                label=s.name,
                status=dot_status,
                detail=f"{s.message} · {latency}",
            ).render()

    # ── Circuit breakers ───────────────────────────────────────────────────
    st.markdown("### Circuit Breakers")
    cb_rows = _load_circuit_breakers()
    cb_data = [
        {
            "Sorgente": r.name,
            "Stato": r.state.upper(),
            "Failures": r.failure_count,
            "": "🟢" if r.state == "closed" else ("🔴" if r.state == "open" else "🟡"),
        }
        for r in cb_rows
    ]
    st.dataframe(cb_data, use_container_width=True, hide_index=True)


def _render_tab_engines(st) -> None:  # pragma: no cover
    """Tab 2 — Motori Analitici: SignalRegistry snapshot."""
    from shared.signal_registry import get_signal_registry

    registry = get_signal_registry()
    all_names = registry.all_signals()

    if not all_names:
        EmptyState(
            "Nessun segnale pubblicato",
            hint="I segnali vengono pubblicati dai motori analitici durante il calcolo.",
            severity="info",
        ).render()
        return

    stale_set = set(registry.stale_signals())
    rows = []
    for name in sorted(all_names):
        sig = registry.get(name)
        is_stale = name in stale_set
        rows.append({
            "Segnale": name,
            "Valore": f"{sig.value:+.4f}" if sig else "—",
            "Qualità": sig.quality_flag if sig else "—",
            "Stale": "⚠️ Sì" if is_stale else "✅ No",
            "IC": f"{sig.ic_estimate:.3f}" if sig and sig.ic_estimate else "—",
        })

    n_fresh = len(all_names) - len(stale_set)
    st.metric("Segnali attivi", f"{n_fresh}/{len(all_names)}")
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_tab_signal_quality(st) -> None:  # pragma: no cover
    """Tab 3 — Signal Quality: IC per ogni segnale."""
    from presentation.ui.components.signal_badge import SignalBadge

    rows = _load_signal_quality()

    if not rows:
        EmptyState(
            "Nessun segnale da monitorare",
            hint="Avvia i motori analitici per popolare il registry.",
            severity="info",
        ).render()
        return

    st.markdown(f"**{len(rows)} segnali monitorati**")

    for row in rows:
        col_badge, col_obs, col_ic = st.columns([3, 1, 1])
        with col_badge:
            SignalBadge(
                name=row.name,
                value=row.value or 0.0,
                ic_estimate=row.ic_estimate,
                quality_flag=row.quality_flag,
            ).render()
        with col_obs:
            st.caption(f"{row.observation_count} obs.")
        with col_ic:
            ic_str = f"IC: {row.ic_estimate:.3f}" if row.ic_estimate is not None else "IC: —"
            st.caption(ic_str)


def _render_tab_llm(st) -> None:  # pragma: no cover
    """Tab 4 — LLM Status: Ollama."""
    st.markdown("### Ollama LLM")
    status = _load_ollama_status()

    if status["running"]:
        models = status["models"]
        st.success(f"✅ Ollama attivo · {len(models)} modell{'o' if len(models)==1 else 'i'} caricati")

        if models:
            preferred = "mistral:7b-q4"
            if preferred in models:
                st.info(f"🎯 Modello preferito disponibile: `{preferred}`")
            else:
                st.warning(
                    f"⚠️ `{preferred}` non trovato. "
                    f"Modelli disponibili: {', '.join(f'`{m}`' for m in models)}"
                )
            st.dataframe(
                [{"Modello": m} for m in models],
                use_container_width=True,
                hide_index=True,
            )
    else:
        StatusDot(
            label="Ollama",
            status="error",
            detail=status.get("error", "Non raggiungibile su localhost:11434"),
        ).render()
        st.info(
            "💡 Per abilitare il LLM locale:\n"
            "1. Installa Ollama: https://ollama.ai\n"
            "2. Esegui: `ollama pull mistral:7b-q4`\n"
            "3. Avvia il server: `ollama serve`"
        )
        st.caption("Quando Ollama non è attivo, MarketAI usa template deterministici.")


def _render_tab_news_ib(st) -> None:  # pragma: no cover
    """Tab 5 — News & IB: News Engine + IB Forecast status."""
    st.markdown("### News Engine")
    try:
        from engine.market_data.news.rss_fetcher import RSSFetcher  # type: ignore[import]
        StatusDot("News Engine", status="ok", detail="RSSFetcher disponibile").render()
    except ImportError:
        EmptyState(
            "News Engine non ancora attivo",
            hint=(
                "Sarà disponibile con la Fase 6 (News Engine). "
                "Attiva il feature flag 'news_engine_enabled' in S2 → Feature Flags."
            ),
            severity="info",
        ).render()

    st.divider()
    st.markdown("### IB Forecast")
    try:
        from engine.market_data.ib_forecast.ib_rss_fetcher import IBRSSFetcher  # type: ignore[import]
        StatusDot("IB Forecast", status="ok", detail="IBRSSFetcher disponibile").render()
    except ImportError:
        EmptyState(
            "IB Forecast non ancora attivo",
            hint=(
                "Sarà disponibile con la Fase 8 (IB Consensus). "
                "Il parser regex/LLM viene configurato in S2 → IB Settings."
            ),
            severity="info",
        ).render()


def _render_tab_scheduler(st) -> None:  # pragma: no cover
    """Tab 6 — Scheduler: Job status."""
    try:
        from shared.scheduler import get_scheduler  # type: ignore[import]
        sched = get_scheduler()
        jobs = sched.get_jobs()
        if jobs:
            rows = [
                {
                    "Job": j.id,
                    "Prossima esecuzione": str(j.next_run_time),
                    "Trigger": str(j.trigger),
                }
                for j in jobs
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            EmptyState("Nessun job schedulato", severity="info").render()
    except Exception:
        EmptyState(
            "Scheduler non configurato",
            hint="Il modulo scheduler sarà attivo con la Fase 9 (Background Jobs).",
            severity="info",
        ).render()


def _render_tab_log(st) -> None:  # pragma: no cover
    """Tab 7 — System Log: ultimi eventi strutturati."""
    try:
        from shared.monitoring.log_store import get_recent_logs
        entries = get_recent_logs(limit=50)
    except Exception:
        entries = []

    if not entries:
        EmptyState(
            "Log non disponibile",
            hint=(
                "Il log in-memory è attivo solo durante l'esecuzione dei motori analitici. "
                "Avvia un'analisi per vedere i log qui."
            ),
            severity="info",
        ).render()
        return

    st.dataframe(
        entries,
        use_container_width=True,
        hide_index=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def body_s0_health(tokens: DesignTokens) -> None:  # pragma: no cover
    """S0 Health Monitor — 7 tab."""
    import streamlit as st
    from shared.monitoring.system_status import get_system_status

    # Header + refresh button
    h_col, r_col = st.columns([5, 1])
    with h_col:
        status = get_system_status()
        status_color = {
            "OPERATIONAL": tokens.colors.health_operational,
            "DEGRADED":    tokens.colors.health_degraded,
            "DOWN":        tokens.colors.health_down,
        }.get(status, tokens.colors.neutral)
        st.markdown(
            f"## 🏥 Health Monitor "
            f'<span style="font-size:14px;color:{status_color}">● {status}</span>',
            unsafe_allow_html=True,
        )
    with r_col:
        if st.button("🔄 Aggiorna", key="s0_refresh"):
            st.session_state[SK.API_HEALTH_RESULTS] = None
            st.cache_data.clear()
            st.rerun()

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📡 Sorgenti",
        "⚙️ Motori",
        "📊 Signal Quality",
        "🤖 LLM",
        "📰 News & IB",
        "⏰ Scheduler",
        "📋 Log",
    ])

    with tab1:
        _render_tab_sources(st)
    with tab2:
        _render_tab_engines(st)
    with tab3:
        _render_tab_signal_quality(st)
    with tab4:
        _render_tab_llm(st)
    with tab5:
        _render_tab_news_ib(st)
    with tab6:
        _render_tab_scheduler(st)
    with tab7:
        _render_tab_log(st)


if __name__ == "__main__":  # pragma: no cover
    tokens = setup_page("S0 Health Monitor", icon="🏥")
    body_s0_health(tokens)
