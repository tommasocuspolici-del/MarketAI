# ruff: noqa: N999
"""S0 — Health & API Status (v8.0).

Eredita ApiHealthChecker (v7.1.1) + aggiunge status scheduler e DB.
Sostituisce E0_API_Health.py.
"""
from __future__ import annotations

__version__ = "8.1.0"
__all__ = ["body_s0_health_api_status"]


def body_s0_health_api_status(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.health_status_bar import render_health_status_bar

    require_auth()
    st.title("📡 Sistema — Health & API Status")
    st.caption("Stato in tempo reale di tutti i componenti e le fonti dati.")

    # ── Health check componenti ────────────────────────────────────────────
    st.subheader("🔧 Componenti Sistema")
    try:
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.sqlite_client import get_sqlite_client
        from shared.health import HealthChecker

        checker = HealthChecker(
            duckdb_client=get_duckdb_client(),
            sqlite_client=get_sqlite_client(),
            cache_manager=None,
        )
        health = checker.check_all()
        render_health_status_bar(st, health)

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
        from engine.market_data.api_health_checker import ApiHealthChecker
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

    # ── Bottone refresh ────────────────────────────────────────────────────
    if st.button("🔄 Aggiorna stato"):
        st.cache_data.clear()
        st.rerun()
