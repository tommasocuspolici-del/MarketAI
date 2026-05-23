# ruff: noqa: N999
"""M1 — Macro Dashboard (v8.0). Sostituisce E6_Macro.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_m1_macro_dashboard"]


def _load_series_data() -> dict:
    from shared.db.macro_repo import get_macro_repository
    from presentation.ui.components.macro_heatmap import build_series_data_from_repo
    repo = get_macro_repository()
    return build_series_data_from_repo(repo)


def body_m1_macro_dashboard(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.macro_heatmap import render_macro_heatmap

    require_auth()
    from presentation.ui.components.macro_heatmap import _FRED_THRESHOLDS
    _TOTAL_SERIES = len(_FRED_THRESHOLDS)

    st.title("🌍 Macro — Dashboard FRED")
    st.caption(
        f"{_TOTAL_SERIES} serie macroeconomiche FRED con semaforo "
        "(🟢 ok · 🟡 attenzione · 🔴 critico)."
    )

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("📥 Carica da FRED", key="m1_load_fred",
                     help="Scarica tutte le serie macro da FRED (richiede FRED_API_KEY)"):
            with st.spinner("Fetch FRED in corso…"):
                try:
                    import asyncio
                    import yaml
                    from pathlib import Path
                    from engine.market_data.fetchers.fred_fetcher import FREDFetcher
                    from shared.db.macro_repo import get_macro_repository

                    cfg_path = Path(__file__).parents[3] / "config" / "macro_extended.yaml"
                    with cfg_path.open() as f:
                        config = yaml.safe_load(f)

                    fetcher = FREDFetcher()
                    repo = get_macro_repository()
                    series_ok = rows_total = 0
                    errors = []

                    async def _fetch_all():
                        nonlocal series_ok, rows_total
                        for _cat, series_list in config.items():
                            if not isinstance(series_list, list):
                                continue
                            for entry in series_list:
                                sid = entry.get("id", "")
                                if not sid:
                                    continue
                                try:
                                    outcome = await fetcher.fetch(series_id=sid)
                                    if outcome and not outcome.cleaned_df.empty:
                                        rows_total += repo.write_macro_series(
                                            series_id=sid, df=outcome.cleaned_df,
                                            source="fred", frequency=entry.get("freq"),
                                        )
                                        series_ok += 1
                                except Exception as exc:
                                    errors.append(f"{sid}: {exc!s:.60}")

                    asyncio.run(_fetch_all())
                    msg = f"✅ {series_ok} serie · {rows_total} righe scritte"
                    if errors:
                        msg += f" · {len(errors)} errori"
                    st.success(msg)
                    if errors:
                        st.warning("\n".join(errors[:5]))
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Errore fetch FRED: {type(exc).__name__}: {exc}")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="m1_refresh"):
            st.cache_data.clear()
            st.rerun()

    try:
        series_data = _load_series_data()
        available = sum(1 for v in series_data.values() if v is not None)
        st.caption(f"Serie disponibili: {available}/{_TOTAL_SERIES}")
        render_macro_heatmap(st, series_data)
    except Exception as exc:
        st.warning(f"⚠️ Dati FRED non ancora disponibili: {exc}")
        st.info(
            "Premi **📥 Carica da FRED** per scaricare le serie, "
            "oppure avvia lo scheduler: `python scripts/run_scheduler.py`"
        )

    # ── Metriche chiave in dettaglio ───────────────────────────────────────
    st.divider()
    st.subheader("📊 Indicatori Chiave")
    try:
        from shared.db.macro_repo import get_macro_repository
        repo = get_macro_repository()

        key_series = {
            "CPI YoY (%)": "CPIAUCSL",
            "Fed Funds (%)": "FEDFUNDS",
            "10Y Treasury (%)": "DGS10",
            "HY OAS (bps)": "BAMLH0A0HYM2",
            "Initial Claims": "ICSA",
            "Unemployment (%)": "UNRATE",
        }

        cols = st.columns(3)
        for i, (label, sid) in enumerate(key_series.items()):
            with cols[i % 3]:
                try:
                    obs = repo.read_latest_macro(sid)
                    val = obs["value"] if obs else None
                    st.metric(label, f"{val:.2f}" if val is not None else "N/D")
                except Exception:
                    st.metric(label, "N/D")
    except Exception:
        pass
