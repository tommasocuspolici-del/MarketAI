# ruff: noqa: N999
"""S0 — Health & API Status (v8.2.0).

Eredita ApiHealthChecker (v7.1.1) + aggiunge status scheduler e DB.
Sostituisce E0_API_Health.py.
v8.2.0: aggiunta sezione SLO / Error Budget.
"""
from __future__ import annotations

from presentation.ui.cache_policy import CACHE_TTL

__version__ = "8.2.0"
__all__ = ["body_s0_health_api_status", "load_slo_metrics"]

# ── SLO targets (module-level, documentano i contratti di qualità) ────────────
_SLO_TARGETS: dict[str, tuple[float, str]] = {
    "api_success_rate_7d":     (0.995, "≥ 99.5%"),
    "scheduler_uptime_7d":     (0.990, "≥ 99.0%"),
    "data_freshness_critical": (1800.0, "≤ 30 min"),
    "p95_query_latency_ms":    (2000.0, "≤ 2000 ms"),
    "error_budget_monthly":    (0.005, "≤ 0.5%"),
}

_SLO_LABELS: dict[str, str] = {
    "api_success_rate_7d":     "API Success Rate 7d",
    "scheduler_uptime_7d":     "Scheduler Uptime 7d",
    "data_freshness_critical": "Data Freshness (s)",
    "p95_query_latency_ms":    "p95 Query Latency",
    "error_budget_monthly":    "Error Budget (mese)",
}

_SLO_DEFINITIONS: list[tuple[str, str, str]] = [
    ("API Success Rate 7d", "≥ 99.5%", "% chiamate API con outcome='success' negli ultimi 7 giorni (da audit_log)"),
    ("Scheduler Uptime 7d", "≥ 99.0%", "Percentuale di run scheduler completati senza errore nelle ultime 168h"),
    ("Data Freshness Critical", "≤ 30 min", "Secondi dall'ultimo aggiornamento per le serie critiche (VIX, macro)"),
    ("p95 Query Latency", "≤ 2000 ms", "Latenza al 95° percentile per le query DuckDB (da audit_log.duration_ms)"),
    ("Error Budget Mensile", "≤ 0.5%", "Quota di errori permessa nel mese corrente (1 - success_rate_30d)"),
]


def load_slo_metrics() -> dict[str, float]:  # pragma: no cover
    """Carica le metriche SLI correnti da DuckDB audit_log.

    Restituisce 0.0 per le metriche non ancora disponibili (nessun dato).
    Regola 12: solo letture DB, nessuna chiamata API.
    """
    from shared.db.duckdb_client import get_duckdb_client  # lazy import

    metrics: dict[str, float] = {k: 0.0 for k in _SLO_TARGETS}
    try:
        db = get_duckdb_client()

        # 1. API success rate 7d
        try:
            rows = db.query(
                """
                SELECT
                    CAST(COUNT(*) FILTER (WHERE outcome = 'success') AS DOUBLE)
                    / NULLIF(COUNT(*), 0)
                FROM audit_log
                WHERE event_ts >= NOW() - INTERVAL '7 days'
                """
            )
            if rows and rows[0][0] is not None:
                metrics["api_success_rate_7d"] = float(rows[0][0])
        except Exception:
            pass

        # 2. Scheduler uptime 7d — approssimato da % run scheduler senza errore
        try:
            rows = db.query(
                """
                SELECT
                    CAST(COUNT(*) FILTER (WHERE outcome = 'success') AS DOUBLE)
                    / NULLIF(COUNT(*), 0)
                FROM audit_log
                WHERE event_ts >= NOW() - INTERVAL '7 days'
                  AND operation LIKE '%scheduler%'
                """
            )
            if rows and rows[0][0] is not None:
                metrics["scheduler_uptime_7d"] = float(rows[0][0])
        except Exception:
            pass

        # 3. p95 query latency ms
        try:
            rows = db.query(
                """
                SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)
                FROM audit_log
                WHERE event_ts >= NOW() - INTERVAL '7 days'
                  AND duration_ms IS NOT NULL
                """
            )
            if rows and rows[0][0] is not None:
                metrics["p95_query_latency_ms"] = float(rows[0][0])
        except Exception:
            pass

        # 4. Error budget monthly = 1 - success_rate_30d
        try:
            rows = db.query(
                """
                SELECT
                    CAST(COUNT(*) FILTER (WHERE outcome = 'success') AS DOUBLE)
                    / NULLIF(COUNT(*), 0)
                FROM audit_log
                WHERE event_ts >= NOW() - INTERVAL '30 days'
                """
            )
            if rows and rows[0][0] is not None:
                metrics["error_budget_monthly"] = round(1.0 - float(rows[0][0]), 6)
        except Exception:
            pass

    except Exception:
        pass  # DB non disponibile: restituisce tutti 0.0

    return metrics


def body_s0_health_api_status(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.health_status_bar import render_health_status_bar

    require_auth()
    st.title("📡 Sistema — Health & API Status")
    st.caption("Stato in tempo reale di tutti i componenti e le fonti dati.")

    # ── Health check componenti ────────────────────────────────────────────
    st.subheader("🔧 Componenti Sistema")
    try:
        from shared.health import HealthChecker

        checker = HealthChecker()
        health = checker.check_all()
        render_health_status_bar(tokens, health)

        cols = st.columns(len(health.components))
        for col, comp in zip(cols, health.components):
            status_icon = {"operational": "🟢", "degraded": "🟡", "down": "🔴"}.get(
                comp.status.value, "⚪")
            latency_str = f"{comp.latency_ms:.0f}ms" if comp.latency_ms else "—"
            col.metric(
                label=f"{status_icon} {comp.name.upper()}",
                value=comp.status.value.upper(),
                delta=latency_str,
            )
    except Exception as exc:
        st.error(f"Health check non disponibile: {exc}")

    st.divider()

    # ── Status API fonti dati ──────────────────────────────────────────────
    st.subheader("🌐 Fonti Dati API")
    try:
        from engine.market_data.hardening.api_health_checker import ApiHealthChecker
        checker_api = ApiHealthChecker()
        results = checker_api.check_all()

        for name, result in results.items():
            ok = result.get("ok", False)
            icon = "🟢" if ok else "🔴"
            latency = result.get("latency_ms")
            lat_str = f"{latency:.0f}ms" if latency else "—"
            st.markdown(f"{icon} **{name}** — {lat_str}")
    except Exception as exc:
        st.warning(f"API health checker non disponibile: {exc}")

    st.divider()

    # ── Scheduler status ───────────────────────────────────────────────────
    st.subheader("⏰ Scheduler")
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()

        rows = db.query(
            "SELECT computed_at FROM engine_composite_signal "
            "ORDER BY computed_at DESC LIMIT 1"
        )
        if rows:
            st.success(f"✅ Ultimo composite signal: {rows[0][0]}")
        else:
            st.warning("⚠️ Nessun composite signal ancora calcolato.")

        vix_rows = db.query(
            "SELECT computed_at, action FROM vix_strategy_outputs "
            "ORDER BY computed_at DESC LIMIT 1"
        )
        if vix_rows:
            st.info(f"VIX Strategy: {vix_rows[0][1]} — {vix_rows[0][0]}")
    except Exception as exc:
        st.error(f"DB non raggiungibile: {exc}")

    st.divider()

    # ── LLM Status ────────────────────────────────────────────────────────────
    st.subheader("🤖 LLM Status")
    try:
        from shared.llm.llm_gateway import get_llm_gateway
        from engine.llm.hardware_detector import detect_hardware

        gateway = get_llm_gateway()
        status = gateway.status()
        hw = detect_hardware()

        status_icons = {
            "disabled":  "⚫ DISABLED",
            "available": "✅ AVAILABLE",
            "degraded":  "🟡 DEGRADED",
            "down":      "🔴 DOWN",
        }
        col_llm1, col_llm2, col_llm3 = st.columns(3)
        col_llm1.metric("LLM Status", status_icons.get(status.value, status.value))
        col_llm2.metric("RAM Disponibile", f"{hw.available_ram_gb:.1f} GB")
        col_llm3.metric("Disco Libero", f"{hw.free_disk_gb:.1f} GB")

        if hw.recommended_model:
            st.info(f"🎯 Modello raccomandato per il tuo hardware: **{hw.recommended_model}**")
        elif hw.errors:
            for err in hw.errors:
                st.warning(err)

        if status.value == "disabled":
            st.caption(
                "LLM disabilitato (default). "
                "Per attivarlo: S2_Impostazioni → sezione LLM → abilita Master Switch."
            )
        elif status.value == "available":
            st.success("Ollama risponde correttamente.")
        elif status.value == "down":
            from engine.llm.hardware_detector import LLM_ERROR_MESSAGES, LLMErrorCode
            st.error(LLM_ERROR_MESSAGES[LLMErrorCode.OLLAMA_UNAVAILABLE])
    except Exception as exc:
        st.warning(f"LLM status non disponibile: {exc}")

    st.divider()

    # ── SLO / Error Budget ────────────────────────────────────────────────────
    st.subheader("📊 SLO / Error Budget")

    @st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
    def _cached_slo_metrics() -> dict[str, float]:
        return load_slo_metrics()

    slo_data = _cached_slo_metrics()

    slo_cols = st.columns(5)
    slo_keys = list(_SLO_TARGETS.keys())
    for col, key in zip(slo_cols, slo_keys):
        target_val, target_label = _SLO_TARGETS[key]
        current = slo_data.get(key, 0.0)
        label = _SLO_LABELS[key]
        no_data = current == 0.0

        # Format display value
        if key in ("api_success_rate_7d", "scheduler_uptime_7d"):
            display = f"{current * 100:.2f}%" if not no_data else "—"
            delta = f"target {target_label}"
            meeting = current >= target_val
        elif key == "data_freshness_critical":
            display = f"{current:.0f}s" if not no_data else "—"
            delta = f"target {target_label}"
            meeting = current <= target_val and not no_data
        elif key == "p95_query_latency_ms":
            display = f"{current:.0f} ms" if not no_data else "—"
            delta = f"target {target_label}"
            meeting = current <= target_val and not no_data
        else:  # error_budget_monthly
            display = f"{current * 100:.3f}%" if not no_data else "—"
            delta = f"target {target_label}"
            meeting = current <= target_val

        delta_color = "normal" if (meeting and not no_data) else "inverse"
        col.metric(label=label, value=display, delta=delta, delta_color=delta_color)

    # Error budget progress bar
    budget_used = slo_data.get("error_budget_monthly", 0.0)
    budget_limit = _SLO_TARGETS["error_budget_monthly"][0]  # 0.005
    if budget_used > 0.0:
        consumption_pct = min(budget_used / budget_limit, 1.0)
        st.caption(
            f"🔋 Error budget mensile consumato: {consumption_pct * 100:.1f}%"
            f" ({budget_used * 100:.3f}% / {budget_limit * 100:.1f}% limite)"
        )
        st.progress(consumption_pct)
    else:
        st.caption("🔋 Error budget mensile: nessun dato disponibile (audit_log vuoto o assente).")

    with st.expander("ℹ️ SLO Definizioni"):
        import pandas as pd
        df_slo = pd.DataFrame(
            _SLO_DEFINITIONS,
            columns=["Metrica", "Target", "Descrizione"],
        )
        st.dataframe(df_slo, use_container_width=True, hide_index=True)

    # ── Bottone refresh ────────────────────────────────────────────────────
    if st.button("🔄 Aggiorna stato"):
        st.cache_data.clear()
        st.rerun()
