#!/usr/bin/env python3
"""repair_sett2_sett3.py — MarketAI: Riparazione Patch Settimana 2 e 3
===========================================================================
Cosa fa questo script:

  CRITICO (app crasha senza questi):
    ✦ Crea shared/config/__init__.py + operational_config.py
    ✦ Crea config/operational_defaults.yaml

  SETT 1 — fix residuo:
    ✦ etoro_client.py: avvolge il debug block in ETORO_DEBUG_PAYLOAD guard

  SETT 2 — completamento:
    ✦ live_market_service.py: _TTL_SECONDS = 900.0 → OP_CONFIG

  SETT 3 — completamento:
    ✦ live_market_service.py: aggiunge CurrencyConverter in __init__
    ✦ live_market_service.py: _extract_kpi converte GBX→USD

  FILE MANCANTI:
    ✦ Crea tests/shared/test_operational_config.py
    ✦ Crea tests/engine/test_currency_converter.py

  AVVISO (manuale):
    ⚠  etoro_raw_payload.json trovato su disco (dati finanziari in chiaro)
       → eliminarlo a mano: del etoro_raw_payload.json

Uso:
    python repair_sett2_sett3.py [--root PERCORSO] [--dry-run]
===========================================================================
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys

ROOT_MARKERS = ["personal", "engine", "shared", "presentation"]

# ────────────────────────────────────────────────────────────── helpers


def _n(text: str) -> str:
    return text.replace("\r\n", "\n")


def read(path: pathlib.Path) -> str:
    return _n(path.read_text(encoding="utf-8", errors="replace"))


def write(path: pathlib.Path, content: str, *, dry_run: bool) -> None:
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def copy_file(src: pathlib.Path, dst: pathlib.Path, label: str, *, dry_run: bool) -> None:
    exists = dst.exists()
    tag = "SKIP (esiste)" if exists else ("DRY-RUN" if dry_run else "CREATO")
    if not exists and not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    sym = "⚠️ " if exists else "✅"
    print(f"  {sym} [{dst.name}] {tag} — {label}")


def str_replace(
    path: pathlib.Path, old: str, new: str, label: str, *, dry_run: bool
) -> bool:
    txt = read(path)
    if _n(old) not in txt:
        return False
    if not dry_run:
        write(path, txt.replace(_n(old), _n(new), 1), dry_run=False)
    print(f"  ✅  [{path.name}] {label}")
    return True


def regex_replace(
    path: pathlib.Path, pattern: str, repl: str, label: str,
    *, dry_run: bool, flags: int = re.MULTILINE | re.DOTALL
) -> bool:
    txt = read(path)
    new_txt, n = re.subn(pattern, repl, txt, count=1, flags=flags)
    if n == 0:
        return False
    if not dry_run:
        write(path, new_txt, dry_run=False)
    print(f"  ✅  [{path.name}] {label}")
    return True


def warn(label: str) -> None:
    print(f"  ⚠️   {label}")


def fail(label: str) -> None:
    print(f"  ❌  {label}")


# ──────────────────────────────────────────────────── patch functions


def fix_create_shared_config(root: pathlib.Path, files_dir: pathlib.Path, *, dry_run: bool) -> None:
    """CRITICO: crea shared/config/ package (app crasha senza)."""
    print("\n[CRITICO] shared/config/ — package mancante che causa crash all'avvio")
    copy_file(
        files_dir / "shared/config/__init__.py",
        root / "shared/config/__init__.py",
        "Package init",
        dry_run=dry_run,
    )
    copy_file(
        files_dir / "shared/config/operational_config.py",
        root / "shared/config/operational_config.py",
        "OperationalConfig + _DEFAULTS + OP_CONFIG singleton",
        dry_run=dry_run,
    )


def fix_create_yaml(root: pathlib.Path, files_dir: pathlib.Path, *, dry_run: bool) -> None:
    """CRITICO: crea config/operational_defaults.yaml (mancante)."""
    print("\n[CRITICO] config/operational_defaults.yaml — file mancante")
    dst = root / "config" / "operational_defaults.yaml"
    if dst.exists():
        print(f"  ⚠️  [operational_defaults.yaml] SKIP — esiste già")
        return
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(files_dir / "config_operational_defaults.yaml", dst)
    print(f"  ✅  [operational_defaults.yaml] {'DRY-RUN' if dry_run else 'CREATO'}")


def fix_etoro_client_debug(root: pathlib.Path, *, dry_run: bool) -> None:
    """SETT 1: avvolge il debug block in ETORO_DEBUG_PAYLOAD guard."""
    print("\n[SETT 1] etoro_client.py — fix P1 debug block (ancora non protetto)")
    path = root / "personal" / "data_entry" / "etoro_client.py"
    if not path.exists():
        fail("etoro_client.py non trovato")
        return

    # Pattern esatto rilevato nel file reale
    old = (
        "        # debug: salva payload raw (opzionale)\n"
        "        import json as _json, pathlib as _pathlib\n"
        "        _pathlib.Path(\"etoro_raw_payload.json\").write_text(\n"
        "            _json.dumps(payload, indent=2, ensure_ascii=False)\n"
        "        )\n"
    )
    new = (
        "        # [v8.1.0 FIX-P1] Debug block protetto da env var (mai in produzione).\n"
        "        # Per abilitare in locale: ETORO_DEBUG_PAYLOAD=1 python -m ...\n"
        "        if os.getenv(\"ETORO_DEBUG_PAYLOAD\"):  # pragma: no cover\n"
        "            import json as _json, pathlib as _pathlib\n"
        "            _pathlib.Path(\"etoro_raw_payload.json\").write_text(\n"
        "                _json.dumps(payload, indent=2, ensure_ascii=False)\n"
        "            )\n"
    )
    if not str_replace(path, old, new, "Debug block → guard ETORO_DEBUG_PAYLOAD", dry_run=dry_run):
        # Fallback regex (più flessibile)
        if not regex_replace(
            path,
            r"(        # debug[^\n]*\n"
            r"        import json as _json, pathlib as _pathlib\n"
            r"        _pathlib\.Path\(\"etoro_raw_payload\.json\"\)\.write_text\(\n"
            r"            _json\.dumps\(payload[^\n]*\)\n"
            r"        \)\n)",
            (
                "        # [v8.1.0 FIX-P1] Debug block protetto da env var.\n"
                "        if os.getenv(\"ETORO_DEBUG_PAYLOAD\"):  # pragma: no cover\n"
                "            import json as _json, pathlib as _pathlib\n"
                "            _pathlib.Path(\"etoro_raw_payload.json\").write_text(\n"
                "                _json.dumps(payload, indent=2, ensure_ascii=False)\n"
                "            )\n"
            ),
            "Debug block → guard (regex fallback)",
            dry_run=dry_run,
        ):
            fail("Debug block non trovato — controlla get_real_portfolio()")


def fix_lms_ttl(root: pathlib.Path, *, dry_run: bool) -> None:
    """SETT 2: live_market_service — _TTL_SECONDS = 900.0 → OP_CONFIG."""
    print("\n[SETT 2] live_market_service.py — _TTL_SECONDS → OP_CONFIG (P4)")
    path = root / "engine" / "market_data" / "live_market_service.py"
    if not path.exists():
        fail("live_market_service.py non trovato")
        return

    # Sostituisce il blocco commento+assegnazione con la versione centralizzata
    old = (
        "# TTL della cache in secondi.\n"
        "# ANTI-REGRESSIONE (v9.0 rate-limit fix): TTL aumentato da 60s a 900s (15 min).\n"
        "# Con TTL=60 il live service chiama yfinance ~1440 volte/giorno solo per i KPI\n"
        "# di dashboard — Yahoo Finance blocca l'IP entro poche ore.\n"
        "# Il trade-off è accettabile: i prezzi di dashboard si aggiornano ogni 15 min\n"
        "# invece che ogni minuto. Per prezzi più freschi usa lo scheduler (ogni 4h dal DB).\n"
        "_TTL_SECONDS = 900.0\n"
    )
    new = (
        "# [v8.1.0 FIX-P4] TTL centralizzato in config/operational_defaults.yaml\n"
        "# (cache.live_market_ttl_s = 900s — deliberato per rate-limit Yahoo Finance).\n"
        "# ANTI-REGRESSIONE (v9.0): 900s evita ~1440 chiamate/giorno che bancano l'IP.\n"
        "# Per cambiare il TTL: modificare il YAML, nessuna modifica al codice.\n"
        "_TTL_SECONDS: float = OP_CONFIG.cache.live_market_ttl_s\n"
    )
    if not str_replace(path, old, new, "_TTL_SECONDS → OP_CONFIG.cache.live_market_ttl_s", dry_run=dry_run):
        # Regex fallback
        if not regex_replace(
            path,
            r"_TTL_SECONDS\s*=\s*900\.0\s*(?:#[^\n]*)?",
            "_TTL_SECONDS: float = OP_CONFIG.cache.live_market_ttl_s  # [v8.1.0 FIX-P4]",
            "_TTL_SECONDS = 900.0 → OP_CONFIG (regex)",
            dry_run=dry_run,
            flags=re.MULTILINE,
        ):
            fail("_TTL_SECONDS non trovato — verificare il file")


def fix_lms_currency_converter(root: pathlib.Path, *, dry_run: bool) -> None:
    """SETT 3: live_market_service — CurrencyConverter import + __init__ + _extract_kpi."""
    print("\n[SETT 3] live_market_service.py — CurrencyConverter (fix GBX bug)")
    path = root / "engine" / "market_data" / "live_market_service.py"
    if not path.exists():
        fail("live_market_service.py non trovato")
        return

    txt = read(path)

    # Step 1: import CurrencyConverter
    if "from engine.market_data.currency_converter import" not in txt:
        anchor_candidates = [
            "from engine.market_data.hardening.silent_failure_detector import (\n    SilentFailureError,\n)\n",
            "from engine.market_data.hardening.silent_failure_detector import SilentFailureError\n",
        ]
        added = False
        for anchor in anchor_candidates:
            new_block = (
                anchor
                + "from engine.market_data.currency_converter import (\n"
                "    CurrencyConverter,\n"
                "    get_instrument_native_currency,\n"
                ")\n"
            )
            if str_replace(path, anchor, new_block, "Import CurrencyConverter", dry_run=dry_run):
                added = True
                txt = read(path)  # rileggi dopo modifica
                break
        if not added:
            fail("Impossibile aggiungere import CurrencyConverter — aggiungilo manualmente")
    else:
        warn("Import CurrencyConverter già presente — skip")

    # Step 2: self._currency_converter in __init__
    if "_currency_converter" not in read(path):
        if not str_replace(
            path,
            "        self._sanity = sanity or SanityChecker()\n",
            (
                "        self._sanity = sanity or SanityChecker()\n"
                "        # [v8.1.0 FIX Sett3] Converter GBX/EUR→USD per _extract_kpi\n"
                "        self._currency_converter = CurrencyConverter()\n"
            ),
            "self._currency_converter in __init__",
            dry_run=dry_run,
        ):
            fail("self._sanity = ... non trovato — aggiungere manualmente self._currency_converter")
    else:
        warn("self._currency_converter già presente — skip")

    # Step 3: _extract_kpi — aggiunge conversione FX dopo last_close/prev_close
    txt = read(path)
    if "last_close_raw" in txt or "get_instrument_native_currency" in txt:
        warn("_extract_kpi già aggiornato — skip")
        return

    # Pattern: blocco last_close / prev_close / sanity / delta / override
    pattern = re.compile(
        r"( {12})(last_close = _safe_float\(ticker_data\[close_col\]\.iloc\[-1\]\)\n"
        r" {12}prev_close = \(\n"
        r" {16}_safe_float\(ticker_data\[close_col\]\.iloc\[-2\]\)\n"
        r" {16}if len\(ticker_data\) >= 2\n"
        r" {16}else last_close\n"
        r" {12}\)\n)"
        r"(.*?)"
        r"( {12}# .{0,10}BUGFIX v7\.1\.1[^\n]*\n"
        r"(?:.*?\n){0,4}"
        r" {12}api_delta_pct: float \| None = None\n"
        r" {12}if prev_close > 0:\n"
        r" {12}    api_delta_pct = \(last_close - prev_close\) / prev_close\n)"
        r"(\n {12}# Override[^\n]*\n"
        r" {12}final_value, is_override = self\._override_store\.resolve\(\n"
        r" {16}\"price\", term, last_close\n"
        r" {12}\)\n)",
        re.DOTALL,
    )

    m = pattern.search(txt)
    if not m:
        fail(
            "_extract_kpi: pattern non trovato. Aggiunta manuale richiesta.\n"
            "       Vedi ISTRUZIONI_MANUALI_SETT3.md nella cartella del progetto."
        )
        return

    full_match = m.group(0)
    sanity_block = m.group(3)  # blocco sanity check (già presente, invariato)
    indent = "            "

    replacement = (
        # Variabili raw
        f"{indent}# Prezzi raw nella valuta nativa del ticker\n"
        f"{indent}last_close_raw = _safe_float(ticker_data[close_col].iloc[-1])\n"
        f"{indent}prev_close_raw = (\n"
        f"{indent}    _safe_float(ticker_data[close_col].iloc[-2])\n"
        f"{indent}    if len(ticker_data) >= 2\n"
        f"{indent}    else last_close_raw\n"
        f"{indent})\n"
        # Sanity check invariato (usa raw)
        + sanity_block.replace("last_close,", "last_close_raw,")
                       .replace("prev_close=prev_close", "prev_close=prev_close_raw")
        # Delta FX-invariante
        + f"\n"
        f"{indent}# Delta FX-invariante: stessa valuta num/denom → FX si cancella\n"
        f"{indent}api_delta_pct: float | None = None\n"
        f"{indent}if prev_close_raw > 0:\n"
        f"{indent}    api_delta_pct = (last_close_raw - prev_close_raw) / prev_close_raw\n"
        # Conversione FX
        + f"\n"
        f"{indent}# [v8.1.0 FIX Sett3] GBX→USD: SWDA.L 10426p → ~$132\n"
        f"{indent}# BUG PRECEDENTE: last_close trattato come USD → valore ~80x errato\n"
        f"{indent}native_ccy = get_instrument_native_currency(yf_ticker)\n"
        f"{indent}last_close = self._currency_converter.to_usd(last_close_raw, native_ccy)\n"
        # Override invariato (usa last_close in USD)
        + f"\n"
        f"{indent}# Override manuale (Rule 43): l'utente può correggere il prezzo USD.\n"
        f"{indent}final_value, is_override = self._override_store.resolve(\n"
        f'{indent}    "price", term, last_close\n'
        f"{indent})\n"
    )

    new_txt = txt.replace(full_match, replacement, 1)
    if new_txt == txt:
        fail("_extract_kpi: sostituzione fallita (testo identico)")
        return
    if not dry_run:
        write(path, new_txt, dry_run=False)
    print(f"  ✅  [live_market_service.py] _extract_kpi: FX conversion aggiunta")


# ────────────────────────────────────────── test files


_TEST_OP_CONFIG = '''\
"""Test unitari per shared/config/operational_config.py.

Rif: ROADMAP_CODE_QUALITY_v1.0, Settimana 2 (P4).
"""
from __future__ import annotations
import pathlib
from typing import Any
import pytest
import yaml
from shared.config.operational_config import (
    OP_CONFIG, OperationalConfig, _build_config_from_raw,
)


class TestOpConfigSingleton:
    def test_http_timeout(self) -> None:
        assert OP_CONFIG.http.default_timeout_s == 15.0

    def test_http_max_retries(self) -> None:
        assert OP_CONFIG.http.max_retries == 3

    def test_http_body_preview(self) -> None:
        assert OP_CONFIG.http.error_body_preview_bytes == 2048

    def test_cache_live_market_ttl(self) -> None:
        # 900s: deliberato per rate-limit Yahoo Finance (v9.0)
        assert OP_CONFIG.cache.live_market_ttl_s == 900

    def test_fx_gbp_usd(self) -> None:
        assert OP_CONFIG.fx_fallbacks.gbp_usd == 1.27

    def test_fx_eur_usd(self) -> None:
        assert OP_CONFIG.fx_fallbacks.eur_usd == 1.08

    def test_analytics_var_alpha(self) -> None:
        assert OP_CONFIG.analytics.var_alpha == 0.05


class TestBuildConfigFromRaw:
    def test_empty_uses_defaults(self) -> None:
        cfg = _build_config_from_raw({})
        assert cfg.http.default_timeout_s == 15.0
        assert cfg.cache.live_market_ttl_s == 900

    def test_partial_http_override(self) -> None:
        cfg = _build_config_from_raw({"http": {"default_timeout_s": 30.0}})
        assert cfg.http.default_timeout_s == 30.0
        assert cfg.http.max_retries == 3  # default invariato

    def test_partial_fx_override(self) -> None:
        cfg = _build_config_from_raw({"fx_fallbacks": {"gbp_usd": 1.30, "eur_usd": 1.12, "chf_usd": 1.15}})
        assert cfg.fx_fallbacks.gbp_usd == 1.30
        assert cfg.http.default_timeout_s == 15.0  # invariato

    def test_immutable(self) -> None:
        cfg = _build_config_from_raw({})
        with pytest.raises(Exception):
            cfg.http.default_timeout_s = 999.0  # type: ignore[misc]

    def test_returns_correct_type(self) -> None:
        assert isinstance(_build_config_from_raw({}), OperationalConfig)

    @pytest.mark.parametrize("section,field,value", [
        ("http", "default_timeout_s", 42.0),
        ("http", "max_retries", 7),
        ("cache", "live_market_ttl_s", 1800),
        ("fx_fallbacks", "gbp_usd", 1.40),
        ("alerts", "dedup_window_minutes", 120),
    ])
    def test_yaml_override(self, section: str, field: str, value: Any) -> None:
        cfg = _build_config_from_raw({section: {field: value}})
        assert getattr(getattr(cfg, section), field) == value

    def test_yaml_roundtrip(self, tmp_path: pathlib.Path) -> None:
        custom = {"http": {"default_timeout_s": 99.0}, "cache": {"live_market_ttl_s": 1800}}
        (tmp_path / "x.yaml").write_text(yaml.dump(custom))
        raw = yaml.safe_load((tmp_path / "x.yaml").read_text()) or {}
        cfg = _build_config_from_raw(raw)
        assert cfg.http.default_timeout_s == 99.0
        assert cfg.cache.live_market_ttl_s == 1800
        assert cfg.http.max_retries == 3  # default
'''

_TEST_CURRENCY_CONVERTER = '''\
"""Test unitari per engine/market_data/currency_converter.py.

Coverage target: ≥ 90%.
Rif: ROADMAP_CODE_QUALITY_v1.0, Settimana 3 (DoD).
"""
from __future__ import annotations
from unittest import mock
import pytest
from engine.market_data.currency_converter import (
    CurrencyConverter, get_instrument_native_currency,
)


class TestGetInstrumentNativeCurrency:
    @pytest.mark.parametrize("ticker,expected", [
        ("SWDA.L", "GBX"), ("CSPX.L", "GBX"),
        ("EUN5.DE", "EUR"), ("DAX.DE", "EUR"),
        ("SMI.SW", "CHF"), ("9984.T", "JPY"),
        ("AAPL", "USD"), ("^GSPC", "USD"), ("GC=F", "USD"),
    ])
    def test_mapping(self, ticker: str, expected: str) -> None:
        assert get_instrument_native_currency(ticker) == expected

    def test_case_insensitive(self) -> None:
        assert get_instrument_native_currency("swda.l") == "GBX"

    def test_unknown_suffix_usd(self) -> None:
        assert get_instrument_native_currency("FAKE.XY") == "USD"

    def test_empty_string_usd(self) -> None:
        assert get_instrument_native_currency("") == "USD"


class TestCurrencyConverterToUsd:
    def _conv(self, rates: dict) -> CurrencyConverter:
        c = CurrencyConverter()
        c._rate_cache.update(rates)
        return c

    def test_usd_identity(self) -> None:
        c = CurrencyConverter()
        assert c.to_usd(100.0, "USD") == pytest.approx(100.0)

    def test_usd_no_fetch(self) -> None:
        c = CurrencyConverter()
        with mock.patch.object(c, "_fetch_rate") as m:
            c.to_usd(100.0, "USD")
        m.assert_not_called()

    def test_gbx_conversion_range(self) -> None:
        """[DoD] 10426 GBX con GBP/USD=1.27 → 125-145 USD."""
        c = self._conv({"GBP": 1.27})
        r = c.to_usd(10_426.0, "GBX")
        assert 125.0 < r < 145.0
        assert r == pytest.approx(10_426.0 / 100.0 * 1.27, rel=1e-6)

    def test_gbx_not_10k(self) -> None:
        """Anti-regressione: GBX non deve dare ~10000 USD."""
        c = self._conv({"GBP": 1.27})
        assert c.to_usd(10_426.0, "GBX") < 500.0

    def test_eur_conversion_range(self) -> None:
        """[DoD] 118.88 EUR con EUR/USD=1.08 → 120-140 USD."""
        c = self._conv({"EUR": 1.08})
        r = c.to_usd(118.88, "EUR")
        assert 120.0 < r < 140.0

    def test_chf_conversion(self) -> None:
        c = self._conv({"CHF": 1.12})
        assert c.to_usd(100.0, "CHF") == pytest.approx(112.0)

    def test_fallback_matches_op_config(self) -> None:
        from shared.config.operational_config import OP_CONFIG
        assert CurrencyConverter._FALLBACKS["GBP"] == pytest.approx(OP_CONFIG.fx_fallbacks.gbp_usd)
        assert CurrencyConverter._FALLBACKS["EUR"] == pytest.approx(OP_CONFIG.fx_fallbacks.eur_usd)

    def test_rate_cached_after_first_call(self) -> None:
        c = CurrencyConverter()
        c._rate_cache["EUR"] = 1.09
        r = c._fetch_rate("EUR")
        assert r == pytest.approx(1.09)

    def test_ticker_price_swda_l(self) -> None:
        """[DoD] ticker_price_to_usd("SWDA.L", 10426) == to_usd(10426, "GBX")."""
        c = self._conv({"GBP": 1.27})
        assert c.ticker_price_to_usd(10_426.0, "SWDA.L") == pytest.approx(
            c.to_usd(10_426.0, "GBX")
        )

    def test_ticker_aapl_no_fetch(self) -> None:
        c = CurrencyConverter()
        with mock.patch.object(c, "_fetch_rate") as m:
            r = c.ticker_price_to_usd(185.5, "AAPL")
        assert r == pytest.approx(185.5)
        m.assert_not_called()
'''


def fix_create_test_files(root: pathlib.Path, *, dry_run: bool) -> None:
    print("\n[TEST] Creazione file di test mancanti")

    test_oc = root / "tests" / "shared" / "test_operational_config.py"
    if not test_oc.exists():
        write(test_oc, _TEST_OP_CONFIG, dry_run=dry_run)
        print(f"  ✅  [test_operational_config.py] {'DRY-RUN' if dry_run else 'CREATO'}")
    else:
        warn("test_operational_config.py esiste già — skip")

    test_cc = root / "tests" / "engine" / "test_currency_converter.py"
    if not test_cc.exists():
        write(test_cc, _TEST_CURRENCY_CONVERTER, dry_run=dry_run)
        print(f"  ✅  [test_currency_converter.py] {'DRY-RUN' if dry_run else 'CREATO'}")
    else:
        warn("test_currency_converter.py esiste già — skip")


# ──────────────────────────────────────────────── verify


def verify(root: pathlib.Path) -> int:
    print("\n" + "═" * 60)
    print("  VERIFICA FINALE — Definition of Done Sett 2 + 3")
    print("═" * 60)
    fails = 0

    def ck(ok: bool, label: str) -> None:
        nonlocal fails
        if ok:
            print(f"  ✅  {label}")
        else:
            fails += 1
            print(f"  ❌  {label}")

    # CRITICO
    ck((root / "shared/config/operational_config.py").exists(),
       "shared/config/operational_config.py ESISTE")
    ck((root / "config/operational_defaults.yaml").exists(),
       "config/operational_defaults.yaml ESISTE")

    # Sett 1
    ec = _n((root / "personal/data_entry/etoro_client.py").read_text(encoding="utf-8", errors="ignore"))
    ck("ETORO_DEBUG_PAYLOAD" in ec, "etoro_client.py: guard ETORO_DEBUG_PAYLOAD presente")
    ck(
        not ("        # debug: salva payload raw" in ec and "if os.getenv" not in ec),
        "etoro_client.py: debug block NON esposto in produzione",
    )

    # Sett 2
    lms = _n((root / "engine/market_data/live_market_service.py").read_text(encoding="utf-8", errors="ignore"))
    ck("OP_CONFIG.cache.live_market_ttl_s" in lms,
       "live_market_service.py: _TTL_SECONDS usa OP_CONFIG")

    # Sett 3
    ck("from engine.market_data.currency_converter import" in lms,
       "live_market_service.py: import CurrencyConverter")
    ck("_currency_converter = CurrencyConverter()" in lms,
       "live_market_service.py: self._currency_converter in __init__")
    ck("get_instrument_native_currency(yf_ticker)" in lms,
       "live_market_service.py: _extract_kpi usa get_instrument_native_currency")
    ck("self._currency_converter.to_usd(last_close_raw" in lms,
       "live_market_service.py: _extract_kpi converte raw→USD")

    # Test
    ck((root / "tests/shared/test_operational_config.py").exists(),
       "test_operational_config.py ESISTE")
    ck((root / "tests/engine/test_currency_converter.py").exists(),
       "test_currency_converter.py ESISTE")

    # Avvisi non bloccanti
    if (root / "etoro_raw_payload.json").exists():
        print(f"  ⚠️   etoro_raw_payload.json su disco! Eliminarlo manualmente:")
        print(f"       Windows: del etoro_raw_payload.json")
        print(f"       Linux/Mac: rm etoro_raw_payload.json")

    print(f"\n  Risultato: {11 - fails} ✅  {fails} ❌")
    return fails


# ──────────────────────────────────────────────────────── main


def main() -> None:
    parser = argparse.ArgumentParser(description="MarketAI — Repair Patch Sett 2+3")
    parser.add_argument("--root", default=".", help="Radice del progetto")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    dry_run: bool = args.dry_run
    files_dir = pathlib.Path(__file__).parent / "files"

    if not all((root / m).exists() for m in ROOT_MARKERS):
        print(f"❌  '{root}' non sembra la radice di MarketAI.")
        sys.exit(1)
    if not files_dir.exists():
        print(f"❌  'files/' non trovata accanto allo script.")
        sys.exit(1)

    mode = "DRY-RUN" if dry_run else "APPLICAZIONE REALE"
    print(f"\n{'═'*60}")
    print(f"  MarketAI — Repair Patch Settimane 2+3")
    print(f"  Modalità: {mode}  |  Cartella: {root}")
    print(f"{'═'*60}")

    fix_create_shared_config(root, files_dir, dry_run=dry_run)
    fix_create_yaml(root, files_dir, dry_run=dry_run)
    fix_etoro_client_debug(root, dry_run=dry_run)
    fix_lms_ttl(root, dry_run=dry_run)
    fix_lms_currency_converter(root, dry_run=dry_run)
    fix_create_test_files(root, dry_run=dry_run)

    if not dry_run:
        fails = verify(root)
        print()
        if fails == 0:
            print(f"{'═'*60}")
            print("  ✅  Riparazione completata!")
            print("  pytest tests/shared/test_operational_config.py -v")
            print("  pytest tests/engine/test_currency_converter.py -v")
            print("  pytest --tb=short -q")
            print(f"{'═'*60}")
        else:
            print(f"  ⚠️  {fails} problemi rimanenti — vedi output sopra")
    else:
        print(f"\n{'═'*60}")
        print("  Riesegui senza --dry-run per applicare.")
        print(f"{'═'*60}")


if __name__ == "__main__":
    main()
