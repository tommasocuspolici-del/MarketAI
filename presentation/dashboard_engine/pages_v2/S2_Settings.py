# ruff: noqa: N999
"""S2 — Impostazioni Sistema (v1.0 — Fase 9).

Sezione LLM: master switch, modello, stato Ollama, hardware assessment,
istruzioni installazione, test inferenza.
"""
from __future__ import annotations

import pathlib

__version__ = "1.0.0"
__all__ = ["body_s2_settings"]

_FLAGS_FILE = pathlib.Path(__file__).parent.parent.parent.parent.parent / "config" / "feature_flags.yaml"


def _load_flags() -> dict[str, object]:
    try:
        import yaml
        return yaml.safe_load(_FLAGS_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_flags(flags: dict[str, object]) -> bool:
    try:
        import yaml
        _FLAGS_FILE.write_text(
            yaml.dump(flags, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def body_s2_settings(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("⚙️ Impostazioni")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="s2_refresh"):
            st.cache_data.clear()
            st.rerun()

    flags = _load_flags()

    tab_llm, tab_data, tab_system = st.tabs(["🤖 LLM", "📡 Dati", "🔧 Sistema"])

    # ── Tab LLM ──────────────────────────────────────────────────────────────
    with tab_llm:
        st.subheader("LLM — Configurazione")
        st.caption(
            "L'LLM funziona **localmente** via Ollama (nessun dato trasmesso a server esterni). "
            "Privacy garantita — Regola PRIVACY."
        )

        # Hardware assessment
        try:
            from engine.llm.hardware_detector import detect_hardware
            hw = detect_hardware()
            col_ram, col_disk, col_model = st.columns(3)
            col_ram.metric("RAM Disponibile", f"{hw.available_ram_gb:.1f} GB")
            col_disk.metric("Disco Libero", f"{hw.free_disk_gb:.1f} GB")
            if hw.recommended_model:
                col_model.metric("Modello Consigliato", hw.recommended_model)
                st.success(f"✅ Hardware compatibile con **{hw.recommended_model}**")
            else:
                col_model.metric("Modello Consigliato", "—")
                for err in hw.errors:
                    st.error(err)
        except Exception as exc:
            st.warning(f"Hardware detection non disponibile: {exc}")

        st.divider()

        # Master switch
        llm_enabled = bool(flags.get("llm_engine_enabled", False))
        new_enabled = st.toggle(
            "🔌 Abilita LLM (Master Switch)",
            value=llm_enabled,
            key="s2_llm_master",
            help="Disabilitato per default. Richiede Ollama installato e avviato.",
        )
        if new_enabled != llm_enabled:
            flags["llm_engine_enabled"] = new_enabled
            if _save_flags(flags):
                st.success(f"LLM {'abilitato' if new_enabled else 'disabilitato'}. Riavvia l'app.")
            else:
                st.error("Impossibile salvare la configurazione.")

        if not new_enabled:
            st.info(
                "**Procedura di attivazione LLM:**\n\n"
                "1. Installa Ollama: https://ollama.ai\n"
                "2. Scarica il modello: `ollama pull mistral:7b-q4`\n"
                "3. Avvia Ollama: `ollama serve`\n"
                "4. Abilita il Master Switch qui sopra\n"
                "5. Verifica stato in S0_Health → LLM Status"
            )
        else:
            # Stato Ollama live
            try:
                from shared.llm.llm_gateway import get_llm_gateway
                gw = get_llm_gateway()
                status = gw.status()
                icons = {"available": "✅", "degraded": "🟡", "down": "🔴", "disabled": "⚫"}
                st.metric("Stato Ollama", f"{icons.get(status.value, '?')} {status.value.upper()}")
            except Exception as exc:
                st.warning(f"Status Ollama non disponibile: {exc}")

            st.divider()
            st.subheader("Sotto-moduli LLM")
            st.caption("Questi moduli sono attivi solo se il Master Switch è ON.")

            sub_flags = [
                ("llm_narrative_generator", "📝 Narrativa mercato giornaliera"),
                ("llm_news_semantic",        "📰 Analisi notizie semantica"),
                ("llm_market_qa",            "❓ Q&A mercato"),
                ("llm_portfolio_comment",    "💼 Commento portafoglio"),
                ("llm_earnings_summary",     "💰 Riassunto earnings"),
                ("llm_alert_explain",        "🔔 Spiegazione alert"),
                ("ib_llm_extraction",        "🏦 IB Forecast LLM parsing (Stage 2)"),
            ]
            changed = False
            for flag_key, label in sub_flags:
                current = bool(flags.get(flag_key, False))
                new_val = st.checkbox(label, value=current, key=f"s2_{flag_key}")
                if new_val != current:
                    flags[flag_key] = new_val
                    changed = True

            if changed:
                if _save_flags(flags):
                    st.success("Sotto-moduli aggiornati. Riavvia l'app.")
                else:
                    st.error("Impossibile salvare la configurazione.")

            st.divider()

            # Test inferenza
            st.subheader("🧪 Test Inferenza")
            if st.button("▶️ Test mistral:7b-q4", key="s2_llm_test"):
                try:
                    from shared.llm.llm_gateway import get_llm_gateway
                    gw = get_llm_gateway()
                    result = gw.generate(
                        template="market_narrative",
                        context={"regime": "test", "vix": 20.0},
                        max_tokens=64,
                    )
                    st.code(result.text)
                    st.caption(f"Latenza: {result.latency_ms:.0f}ms · Fonte: {result.source}")
                except Exception as exc:
                    st.error(f"Test fallito: {exc}")

    # ── Tab Dati ──────────────────────────────────────────────────────────────
    with tab_data:
        st.subheader("Sorgenti Dati — Stato Feature Flags")
        data_flags = [
            ("imf_fetcher",        "🌐 IMF WEO Fetcher"),
            ("ecb_fetcher",        "🏦 ECB SDW Fetcher"),
            ("oecd_fetcher",       "📊 OECD CLI Fetcher"),
            ("coingecko_fetcher",  "₿  CoinGecko Fetcher"),
            ("news_engine_enabled","📰 News Engine"),
            ("ib_forecast_enabled","🏦 IB Forecast Engine"),
            ("market_data_refresh","📈 Market Data Refresh"),
        ]
        for flag_key, label in data_flags:
            val = bool(flags.get(flag_key, False))
            icon = "🟢" if val else "🔴"
            st.markdown(f"{icon} **{label}** — `{flag_key}`: `{val}`")

    # ── Tab Sistema ────────────────────────────────────────────────────────────
    with tab_system:
        st.subheader("Configurazione Sistema")
        try:
            from shared.config.cache_ttl_config import CACHE_TTL
            st.markdown("**Cache TTL configurati:**")
            for key in ["prezzi_realtime", "prezzi_daily", "macro_fred",
                        "news", "llm_narrativa", "ib_forecast", "pe_metrics"]:
                ttl = CACHE_TTL.get(key)
                st.markdown(f"- `{key}`: **{ttl}s** ({ttl // 60} min)")
        except Exception as exc:
            st.warning(f"Cache config non disponibile: {exc}")

        st.divider()
        st.markdown("**Versione:**")
        st.code("MarketAI v1.0.0-rc · Python 3.11 · DuckDB · SQLite")
