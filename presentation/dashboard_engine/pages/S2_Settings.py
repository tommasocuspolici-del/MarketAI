# ruff: noqa: N999
"""S2 — Impostazioni (v8.2.0).

7 sezioni via st.tabs():
  1. API Keys & Connessioni  — chiavi API, test connessione live
  2. Feature Flags           — toggle visuale da feature_flags.yaml
  3. LLM Configuration       — Ollama status + selezione modello
  4. Data Retention          — slider retention + preview spazio DB
  5. Scheduler               — toggle e orari job
  6. Backup & Restore        — backup manuale + lista + restore
  7. Notifiche               — soglie alert + test notifica

Design: ogni funzione _load_*() è pura e testabile senza Streamlit.
Ogni funzione _render_*() è pragma: no cover.
Ogni modifica persiste sul YAML corrispondente (non solo session_state).
"""
from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from presentation.ui.components import EmptyState, StatusDot
from presentation.ui.layout import setup_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"
__all__ = ["body_s2_settings"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _flags_path() -> Path:
    from shared.constants import FEATURE_FLAGS_PATH
    return FEATURE_FLAGS_PATH


def _retention_path() -> Path:
    from shared.constants import DATA_RETENTION_PATH
    return DATA_RETENTION_PATH


def _backup_dir() -> Path:
    from shared.constants import BACKUP_DIR
    p = BACKUP_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders — pure, testable without Streamlit
# ─────────────────────────────────────────────────────────────────────────────

def _load_feature_flags() -> dict[str, bool]:
    """Load feature flags from YAML (only bool values)."""
    from shared.feature_flags import all_flags
    return all_flags()


def _load_retention_config() -> dict:
    """Load data retention config from YAML."""
    path = _retention_path()
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw


def _load_db_sizes() -> dict[str, float]:
    """Return DB file sizes in MB."""
    from shared.constants import DUCKDB_PATH, SQLITE_PATH

    sizes: dict[str, float] = {}
    for label, p in [("DuckDB (market)", DUCKDB_PATH), ("SQLite (personal)", SQLITE_PATH)]:
        try:
            sizes[label] = p.stat().st_size / (1024 * 1024) if p.exists() else 0.0
        except Exception:
            sizes[label] = 0.0
    return sizes


def _list_backups() -> list[dict]:
    """Return backup files sorted by modification time (newest first)."""
    backup_dir = _backup_dir()
    files = sorted(backup_dir.glob("*.duckdb"), key=lambda f: f.stat().st_mtime, reverse=True)
    result = []
    for f in files:
        stat = f.stat()
        result.append({
            "file": f.name,
            "path": str(f),
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created": datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M"),
        })
    return result


def _save_feature_flags(flags: dict[str, bool]) -> None:
    """Persist modified feature flags to YAML. Clears the flag cache after write."""
    path = _flags_path()
    # Read the full raw file (preserves non-bool keys like llm_model)
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        raw = {}
    raw.update(flags)
    path.write_text(yaml.safe_dump(raw, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    from shared.feature_flags import reload_flags
    reload_flags()


def _save_retention_config(config: dict) -> None:
    """Persist retention config to YAML."""
    path = _retention_path()
    path.write_text(yaml.safe_dump(config, default_flow_style=False, allow_unicode=True), encoding="utf-8")


def _create_backup() -> Path:
    """Create a timestamped backup of the DuckDB file. Returns the backup path."""
    from shared.constants import DUCKDB_PATH

    backup_dir = _backup_dir()
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"market_data_{ts}.duckdb"
    if DUCKDB_PATH.exists():
        shutil.copy2(DUCKDB_PATH, dest)
    else:
        dest.write_bytes(b"")   # empty placeholder for testing
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# Section renderers — pragma: no cover
# ─────────────────────────────────────────────────────────────────────────────

_API_KEYS = [
    ("FRED_API_KEY",       "FRED (macroeconomia)",      "https://fred.stlouisfed.org/"),
    ("FINNHUB_API_KEY",    "Finnhub (equity, options)", "https://finnhub.io/"),
    ("ALPHA_VANTAGE_KEY",  "Alpha Vantage (fondamentali)", "https://www.alphavantage.co/"),
]


def _render_tab_api_keys(st) -> None:  # pragma: no cover
    """Sezione 1: API Keys e test connessione."""
    from engine.market_data.hardening.api_health_checker import ApiHealthChecker

    st.markdown("### Chiavi API")
    st.caption(
        "Le chiavi sono lette dal file `.env`. "
        "Modificale nel file per renderle permanenti."
    )

    for env_var, label, docs_url in _API_KEYS:
        current = os.getenv(env_var, "")
        masked = (current[:4] + "…" + current[-4:]) if len(current) > 8 else ("●" * len(current) if current else "")
        col_label, col_val, col_status = st.columns([2, 2, 1])
        with col_label:
            st.markdown(f"**{label}**")
            st.caption(f"`{env_var}`")
        with col_val:
            if current:
                st.code(masked)
            else:
                st.caption("Non configurata")
        with col_status:
            if current:
                StatusDot(label="", status="ok", detail="Configurata").render()
            else:
                StatusDot(label="", status="degraded", detail="Mancante").render()

    st.divider()
    if st.button("🔌 Test connessione API", key="s2_test_api"):
        with st.spinner("Ping API in corso..."):
            checker = ApiHealthChecker(timeout=5.0)
            results = checker.check_all()
        for r in results:
            dot_status = {"ONLINE": "ok", "DEGRADED": "degraded", "OFFLINE": "error"}.get(r.state, "unknown")
            latency = f"{r.latency_ms:.0f}ms" if r.latency_ms else "—"
            StatusDot(r.name, status=dot_status, detail=f"{r.message} · {latency}").render()


# ── Category labels for feature flags UI ──────────────────────────────────────
_FLAG_CATEGORIES: dict[str, list[str]] = {
    "Sorgenti dati": [
        "edgar_bulk_download", "realtime_websocket", "alpha_vantage_premium",
        "imf_fetcher", "ecb_fetcher", "oecd_fetcher", "coingecko_fetcher",
    ],
    "Motori analitici": [
        "composite_signal_v2", "composite_signal_v3", "advanced_correlation",
        "dcc_garch_full", "lead_lag_granger", "hmm_regime_detection",
    ],
    "LLM": [
        "llm_engine_enabled", "llm_narrative_generator", "ollama_narrative",
        "llm_news_semantic", "llm_market_qa",
    ],
    "News & IB": [
        "news_engine_enabled", "news_rss_fetcher", "news_signal_generator",
        "ib_forecast_enabled", "ib_llm_extraction",
    ],
    "Custom Indicators": [
        "custom_indicators_enabled", "custom_indicator_dsl",
        "alpha_decay_monitor", "indicator_quality_gate",
    ],
    "Portfolio & Personal": [
        "personal_etoro_import", "rebalancing_engine",
        "wealth_monte_carlo", "personal_tax_report",
    ],
    "Sistema": [
        "auto_backup_daily", "health_monitoring",
        "desktop_notifications", "quality_gate_enabled",
    ],
}


def _render_tab_feature_flags(st) -> None:  # pragma: no cover
    """Sezione 2: Feature Flags — toggle visuale da feature_flags.yaml."""
    flags = _load_feature_flags()
    modified: dict[str, bool] = {}

    st.markdown("### Feature Flags")
    st.caption(
        "I toggle modificano `config/feature_flags.yaml`. "
        "Alcune modifiche richiedono il riavvio di Streamlit per avere effetto."
    )

    for category, flag_names in _FLAG_CATEGORIES.items():
        with st.expander(category, expanded=False):
            for name in flag_names:
                if name not in flags:
                    continue
                current_val = flags[name]
                new_val = st.toggle(
                    label=name.replace("_", " ").title(),
                    value=current_val,
                    key=f"flag_{name}",
                )
                if new_val != current_val:
                    modified[name] = new_val

    if modified:
        _save_feature_flags(modified)
        st.success(
            f"✅ {len(modified)} flag aggiornati. "
            "⚠️ Riavvia Streamlit se hai modificato flag di backend."
        )
        st.rerun()


def _render_tab_llm(st) -> None:  # pragma: no cover
    """Sezione 3: LLM Configuration."""
    from presentation.dashboard_engine.pages.S0_Health import _load_ollama_status

    # System resources
    st.markdown("### Risorse sistema")
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        ram_avail = psutil.virtual_memory().available / (1024 ** 3)
        st.metric("RAM totale", f"{ram_gb:.1f} GB", delta=f"{ram_avail:.1f} GB disponibili")
    except ImportError:
        st.caption("psutil non disponibile — installa con `pip install psutil`")

    st.divider()
    st.markdown("### Ollama")
    status = _load_ollama_status()

    if status["running"]:
        st.success(f"✅ Ollama attivo · Modelli: {', '.join(f'`{m}`' for m in status['models'])}")
        preferred = "mistral:7b-q4"
        if preferred not in status["models"]:
            st.warning(f"Il modello consigliato `{preferred}` non è installato.")
            st.code(f"ollama pull {preferred}", language="bash")

        if st.button("🧪 Test inference", key="s2_test_llm"):
            with st.spinner("Invio prompt di test..."):
                try:
                    import urllib.request, json
                    payload = json.dumps({
                        "model": preferred if preferred in status["models"] else status["models"][0],
                        "prompt": "Rispondi in 5 parole: qual è il colore del cielo?",
                        "stream": False,
                    }).encode()
                    req = urllib.request.Request(
                        "http://localhost:11434/api/generate",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        result = json.loads(resp.read())
                    st.success(f"✅ Risposta: {result.get('response', '—')}")
                except Exception as exc:
                    st.error(f"❌ Inference fallita: {exc}")
    else:
        StatusDot("Ollama", status="error", detail="Non raggiungibile su localhost:11434").render()
        st.info(
            "Per abilitare il LLM locale:\n"
            "1. `pip install ollama` oppure scarica da https://ollama.ai\n"
            "2. `ollama pull mistral:7b-q4`\n"
            "3. `ollama serve`"
        )

    st.divider()
    st.markdown("### Configurazione flag LLM")
    st.caption("Shortcut ai flag principali (stesso effetto di Sezione 2 → LLM).")
    flags = _load_feature_flags()
    master = st.toggle("LLM Engine abilitato", value=flags.get("llm_engine_enabled", False), key="s2_llm_master")
    if master != flags.get("llm_engine_enabled", False):
        _save_feature_flags({"llm_engine_enabled": master})
        st.rerun()


def _render_tab_retention(st) -> None:  # pragma: no cover
    """Sezione 4: Data Retention — slider per ogni tipo + spazio DB."""
    st.markdown("### Retention per tipo di dato")
    config = _load_retention_config()
    db_sizes = _load_db_sizes()

    for label, size in db_sizes.items():
        st.metric(label, f"{size:.1f} MB")

    st.divider()
    modified = False
    new_config: dict = {k: dict(v) if isinstance(v, dict) else v for k, v in config.items()}

    for section_key, section_label in [("duckdb", "DuckDB (mercato)"), ("sqlite", "SQLite (personale)")]:
        section = config.get(section_key, {})
        if not section:
            continue
        st.markdown(f"**{section_label}**")
        for field_name, current_years in section.items():
            if not isinstance(current_years, int):
                continue
            new_years = st.slider(
                field_name.replace("_", " ").title(),
                min_value=1, max_value=50, value=current_years,
                key=f"ret_{section_key}_{field_name}",
                help=f"Attuale: {current_years} anni",
            )
            if new_years != current_years:
                new_config[section_key][field_name] = new_years
                modified = True

    if modified:
        if st.button("💾 Salva retention", key="s2_save_retention"):
            _save_retention_config(new_config)
            st.success("✅ Retention salvata in `config/data_retention.yaml`")


def _render_tab_scheduler(st) -> None:  # pragma: no cover
    """Sezione 5: Scheduler — flag per ogni job."""
    st.markdown("### Scheduler Jobs")
    st.caption("I toggle abilitano/disabilitano i job scheduler in `feature_flags.yaml`.")

    job_flags = {
        "market_data_refresh":         "Market data refresh (ogni 4h, lun-ven)",
        "analysis_pipeline_scheduled": "Pipeline analitica (ogni 4h)",
        "sentiment_refresh_hourly":    "Sentiment (orario — costoso)",
        "labour_market_scheduler":     "Labour Market (giovedì 17:00)",
        "surprise_scheduler":          "Economic Surprise (lunedì 08:00 UTC)",
        "auto_backup_daily":           "Backup giornaliero (02:00)",
        "auto_retention_cleanup":      "Pulizia retention (mensile 03:00)",
        "custom_indicator_scheduler":  "Custom Indicators (ogni 30 min lun-ven)",
    }
    flags = _load_feature_flags()
    modified: dict[str, bool] = {}

    for flag_name, description in job_flags.items():
        current = flags.get(flag_name, False)
        new_val = st.toggle(description, value=current, key=f"sched_{flag_name}")
        if new_val != current:
            modified[flag_name] = new_val

    if modified:
        _save_feature_flags(modified)
        st.success(f"✅ {len(modified)} job aggiornati.")
        st.rerun()

    st.divider()
    EmptyState(
        "Stato job",
        hint="Il pannello di stato job in tempo reale è disponibile in S0 → Scheduler.",
        severity="info",
    ).render()


def _render_tab_backup(st) -> None:  # pragma: no cover
    """Sezione 6: Backup & Restore."""
    from shared.constants import DUCKDB_PATH

    st.markdown("### Backup manuale")
    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("💾 Crea backup ora", key="s2_backup_now", type="primary"):
            with st.spinner("Backup in corso..."):
                dest = _create_backup()
            st.success(f"✅ Backup creato: `{dest.name}` ({dest.stat().st_size / 1024:.0f} KB)")
            st.rerun()
    with col_info:
        if DUCKDB_PATH.exists():
            size_mb = DUCKDB_PATH.stat().st_size / (1024 * 1024)
            st.caption(f"DuckDB: `{DUCKDB_PATH.name}` · {size_mb:.1f} MB")
        else:
            st.caption("DuckDB non trovato.")

    st.divider()
    st.markdown("### Backup disponibili")
    backups = _list_backups()

    if not backups:
        EmptyState(
            "Nessun backup disponibile",
            hint="Crea il primo backup con il bottone qui sopra.",
            severity="info",
        ).render()
        return

    rows = [
        {"File": b["file"], "Dimensione": f"{b['size_mb']} MB", "Creato": b["created"]}
        for b in backups
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    selected = st.selectbox(
        "Ripristina da backup",
        options=["—"] + [b["file"] for b in backups],
        key="s2_restore_select",
    )
    if selected != "—":
        st.warning(
            f"⚠️ Ripristino di `{selected}` sovrascriverà il database attuale. "
            "Assicurati di aver fatto un backup recente."
        )
        if st.button("🔄 Ripristina", key="s2_restore_confirm", type="secondary"):
            backup_path = next(b["path"] for b in backups if b["file"] == selected)
            shutil.copy2(backup_path, DUCKDB_PATH)
            st.success(f"✅ Database ripristinato da `{selected}`.")


def _render_tab_notifications(st) -> None:  # pragma: no cover
    """Sezione 7: Notifiche — soglie alert."""
    flags = _load_feature_flags()
    modified: dict[str, bool] = {}

    st.markdown("### Notifiche desktop")
    notif_enabled = st.toggle(
        "Abilita notifiche desktop",
        value=flags.get("desktop_notifications", True),
        key="s2_notif_desktop",
    )
    if notif_enabled != flags.get("desktop_notifications", True):
        modified["desktop_notifications"] = notif_enabled

    dedup_enabled = st.toggle(
        "Deduplica alert (no ripetizioni entro 1h)",
        value=flags.get("alert_deduplication", True),
        key="s2_notif_dedup",
    )
    if dedup_enabled != flags.get("alert_deduplication", True):
        modified["alert_deduplication"] = dedup_enabled

    if modified:
        _save_feature_flags(modified)
        st.rerun()

    st.divider()
    st.markdown("### Soglie alert")
    st.caption("Configurazione delle soglie in `config/operational_defaults.yaml`.")

    try:
        from shared.config.operational_config import OP_CONFIG
        vix_threshold = st.slider(
            "VIX spike alert (soglia)",
            min_value=15, max_value=60,
            value=int(getattr(getattr(OP_CONFIG, "analytics", None) or object(), "vix_spike_threshold", 35)),
            key="s2_vix_threshold",
            help="Alert quando VIX supera questa soglia.",
        )
        st.caption(f"Soglia corrente: {vix_threshold}. Modifica in `config/operational_defaults.yaml`.")
    except Exception:
        st.caption("Caricamento config soglie non disponibile.")

    if st.button("🧪 Test notifica", key="s2_test_notif"):
        try:
            from plyer import notification   # type: ignore[import]
            notification.notify(
                title="MarketAI — Test",
                message="Notifica di test da S2 Impostazioni.",
                timeout=5,
            )
            st.success("✅ Notifica inviata.")
        except Exception as exc:
            st.warning(f"⚠️ Notifica non inviata: {exc}. Installa `plyer` per le notifiche desktop.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def body_s2_settings(tokens: DesignTokens) -> None:  # pragma: no cover
    """S2 Settings — 7 tab."""
    import streamlit as st

    h_col, r_col = st.columns([5, 1])
    with h_col:
        st.markdown("## ⚙️ Impostazioni")
    with r_col:
        if st.button("🔄 Aggiorna", key="s2_refresh"):
            st.cache_data.clear()
            st.rerun()

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "🔑 API Keys",
        "🚦 Feature Flags",
        "🤖 LLM",
        "🗄️ Retention",
        "⏰ Scheduler",
        "💾 Backup",
        "🔔 Notifiche",
    ])

    with tab1:
        _render_tab_api_keys(st)
    with tab2:
        _render_tab_feature_flags(st)
    with tab3:
        _render_tab_llm(st)
    with tab4:
        _render_tab_retention(st)
    with tab5:
        _render_tab_scheduler(st)
    with tab6:
        _render_tab_backup(st)
    with tab7:
        _render_tab_notifications(st)


if __name__ == "__main__":  # pragma: no cover
    tokens = setup_page("S2 Impostazioni", icon="⚙️")
    body_s2_settings(tokens)
