#!/usr/bin/env python3
"""apply_patch_settimana3.py — MarketAI v8.1.0 · Blocco B, Settimana 3
ROADMAP_CODE_QUALITY_v1.0

Problema risolto (P2 🔴 Critica):
  BUG ATTIVO in live_market_service._extract_kpi:
  Ticker LSE (es. SWDA.L, CSPX.L) vengono trattati come USD invece di GBX.
  Un prezzo di 10426 GBX (pence) compariva come $10426 invece di ~$132.

Soluzione:
  3.A Crea engine/market_data/currency_converter.py (nuovo modulo)
  3.B Aggiorna live_market_service.py: _extract_kpi usa CurrencyConverter
  3.C etoro_importer.py: NON richiede modifiche (FX helpers già rimossi in v7.3.0)

Prerequisiti: Settimane 1 e 2 completate.

Uso:
    python apply_patch_settimana3.py [--root PERCORSO] [--dry-run]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys

# ──────────────────────────────────────────────────────────────── helpers


def _n(text: str) -> str:
    return text.replace("\r\n", "\n")


def read(path: pathlib.Path) -> str:
    return _n(path.read_text(encoding="utf-8", errors="replace"))


def write(path: pathlib.Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def copy_file(src: pathlib.Path, dst: pathlib.Path, label: str, *, dry_run: bool) -> bool:
    if dst.exists():
        print(f"  ⚠️  [{dst.name}] SKIP — esiste già ({label})")
        return False
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"  ✅  [{dst.name}] CREATO — {label}")
    return True


def apply_str_replace(
    path: pathlib.Path, old: str, new: str, label: str, *, dry_run: bool
) -> bool:
    txt = read(path)
    if _n(old) not in txt:
        return False
    if not dry_run:
        write(path, txt.replace(_n(old), _n(new), 1))
    print(f"  ✅  [{path.name}] OK — {label}")
    return True


def apply_regex_replace(
    path: pathlib.Path,
    pattern: str,
    replacement: str,
    label: str,
    *,
    dry_run: bool,
    flags: int = re.MULTILINE,
) -> bool:
    txt = read(path)
    new_txt, n = re.subn(pattern, replacement, txt, count=1, flags=flags)
    if n == 0:
        return False
    if not dry_run:
        write(path, new_txt)
    print(f"  ✅  [{path.name}] OK — {label}")
    return True


# ──────────────────────────────────────────────────────────── patch 3.A


def patch_create_new_files(
    root: pathlib.Path, files_dir: pathlib.Path, *, dry_run: bool
) -> None:
    """3.A: Crea currency_converter.py e il suo file di test."""
    print("\n[3.A] engine/market_data/currency_converter.py — nuovo modulo")
    copy_file(
        src=files_dir / "engine" / "market_data" / "currency_converter.py",
        dst=root / "engine" / "market_data" / "currency_converter.py",
        label="CurrencyConverter + get_instrument_native_currency",
        dry_run=dry_run,
    )

    print("\n[TEST] tests/engine/test_currency_converter.py — test unitari")
    copy_file(
        src=files_dir / "tests" / "engine" / "test_currency_converter.py",
        dst=root / "tests" / "engine" / "test_currency_converter.py",
        label="Test DoD Settimana 3: GBX range, EUR range, ticker wrapper",
        dry_run=dry_run,
    )


# ──────────────────────────────────────────────────────────── patch 3.B


def patch_live_market_service(root: pathlib.Path, *, dry_run: bool) -> None:
    """3.B: Aggiunge CurrencyConverter a LiveMarketService._extract_kpi.

    BUG CORRETTO: _extract_kpi usava last_close (in GBX) direttamente come
    valore USD. SWDA.L a 10426 GBX compariva come $10426 invece di ~$132.

    Modifiche:
      1. Import CurrencyConverter e get_instrument_native_currency
      2. self._currency_converter = CurrencyConverter() in __init__
      3. _extract_kpi: converte last_close_raw → last_close (USD)
         Il delta_pct è calcolato sui raw (ratio FX-invariante)
    """
    print("\n[3.B] live_market_service.py — integrazione CurrencyConverter (fix GBX bug)")
    path = root / "engine" / "market_data" / "live_market_service.py"
    if not path.exists():
        print(f"  ❌  File non trovato: {path}")
        return

    # Step 1: Aggiunge import CurrencyConverter
    # Cerca dopo l'import di SilentFailureError (già presente nel file)
    import_added = False
    for anchor in [
        "from engine.market_data.hardening.silent_failure_detector import (\n    SilentFailureError,\n)\n",
        "from engine.market_data.hardening.silent_failure_detector import SilentFailureError\n",
    ]:
        if apply_str_replace(
            path,
            old=anchor,
            new=(
                anchor
                + "from engine.market_data.currency_converter import (\n"
                "    CurrencyConverter,\n"
                "    get_instrument_native_currency,\n"
                ")\n"
            ),
            label="Aggiunge import CurrencyConverter",
            dry_run=dry_run,
        ):
            import_added = True
            break

    if not import_added:
        # Fallback: aggiunge dopo shared.logger
        if not apply_regex_replace(
            path,
            pattern=r"(from shared\.config\.operational_config import OP_CONFIG\n)",
            replacement=(
                r"\1"
                "from engine.market_data.currency_converter import (\n"
                "    CurrencyConverter,\n"
                "    get_instrument_native_currency,\n"
                ")\n"
            ),
            label="Aggiunge import CurrencyConverter (fallback position)",
            dry_run=dry_run,
        ):
            print("  ❌  Non riesco ad aggiungere import CurrencyConverter")
            print("       Aggiungi manualmente:")
            print("       from engine.market_data.currency_converter import (")
            print("           CurrencyConverter, get_instrument_native_currency")
            print("       )")

    # Step 2: Aggiunge self._currency_converter = CurrencyConverter() in __init__
    # Cerca dopo self._sanity = sanity or SanityChecker()
    conv_added = False
    for sanity_line in [
        "        self._sanity = sanity or SanityChecker()\n",
    ]:
        if apply_str_replace(
            path,
            old=sanity_line,
            new=(
                sanity_line
                + "        # [v8.1.0 FIX Sett3] Converter per GBX→USD, EUR→USD ecc.\n"
                "        self._currency_converter = CurrencyConverter()\n"
            ),
            label="Aggiunge self._currency_converter = CurrencyConverter()",
            dry_run=dry_run,
        ):
            conv_added = True
            break

    if not conv_added:
        # Regex fallback: self._sanity = ... qualunque riga
        if not apply_regex_replace(
            path,
            pattern=r"(        self\._sanity\s*=\s*sanity or SanityChecker\(\)\n)",
            replacement=(
                r"\1"
                "        # [v8.1.0 FIX Sett3] Converter per GBX→USD, EUR→USD ecc.\n"
                "        self._currency_converter = CurrencyConverter()\n"
            ),
            label="Aggiunge self._currency_converter (regex fallback)",
            dry_run=dry_run,
        ):
            print("  ❌  Non riesco ad aggiungere self._currency_converter in __init__")
            print("       Aggiungi manualmente dopo self._sanity = ...")
            print("       self._currency_converter = CurrencyConverter()")

    # Step 3: Aggiorna _extract_kpi per convertire GBX→USD
    # Sostituisce il blocco last_close/prev_close/sanity/delta con la versione corretta
    #
    # Il testo ORIGINALE da sostituire:
    old_extract_block = (
        "            last_close = float(ticker_data[close_col].iloc[-1])\n"
        "            prev_close = (\n"
        "                float(ticker_data[close_col].iloc[-2])\n"
        "                if len(ticker_data) >= 2\n"
        "                else last_close\n"
        "            )\n"
        "\n"
        "            # Sanity check\n"
        "            violations = self._sanity.check_price_data(\n"
        "                yf_ticker, last_close, prev_close=prev_close\n"
        "            )\n"
        "            if not self._sanity.is_safe_to_store(violations):\n"
        "                cached = self._lookup_cached(term)\n"
        "                if cached is not None:\n"
        "                    return MarketKpi(\n"
        "                        term=term,\n"
        "                        yf_ticker=yf_ticker,\n"
        "                        value=cached.value,\n"
        "                        delta_pct=cached.delta_pct,\n"
        "                        currency=cached.currency,\n"
        "                        format_spec=fmt,\n"
        "                        is_stale=True,\n"
        "                        error=\"sanity violation, using last good value\",\n"
        "                    )\n"
        "\n"
        "            # \u2500\u2500\u2500 BUGFIX v7.1.1: delta_pct calcolato SEMPRE sul prezzo API, \u2500\u2500\u2500\n"
        "            # non sull'override. Il delta deve riflettere il vero movimento\n"
        "            # del mercato (last_close vs prev_close), indipendentemente dal\n"
        "            # fatto che l'utente abbia inserito un override sul valore corrente.\n"
        "            api_delta_pct: float | None = None\n"
        "            if prev_close > 0:\n"
        "                api_delta_pct = (last_close - prev_close) / prev_close\n"
        "\n"
        "            # Override manuale (Rule 43): l'utente puo' aver corretto il prezzo.\n"
        "            final_value, is_override = self._override_store.resolve(\n"
        "                \"price\", term, last_close\n"
        "            )\n"
    )

    new_extract_block = (
        "            # Legge i prezzi raw nella valuta nativa del ticker\n"
        "            last_close_raw = float(ticker_data[close_col].iloc[-1])\n"
        "            prev_close_raw = (\n"
        "                float(ticker_data[close_col].iloc[-2])\n"
        "                if len(ticker_data) >= 2\n"
        "                else last_close_raw\n"
        "            )\n"
        "\n"
        "            # Sanity check sul prezzo raw (prima della conversione FX)\n"
        "            violations = self._sanity.check_price_data(\n"
        "                yf_ticker, last_close_raw, prev_close=prev_close_raw\n"
        "            )\n"
        "            if not self._sanity.is_safe_to_store(violations):\n"
        "                cached = self._lookup_cached(term)\n"
        "                if cached is not None:\n"
        "                    return MarketKpi(\n"
        "                        term=term,\n"
        "                        yf_ticker=yf_ticker,\n"
        "                        value=cached.value,\n"
        "                        delta_pct=cached.delta_pct,\n"
        "                        currency=cached.currency,\n"
        "                        format_spec=fmt,\n"
        "                        is_stale=True,\n"
        "                        error=\"sanity violation, using last good value\",\n"
        "                    )\n"
        "\n"
        "            # BUGFIX v7.1.1 (invariato): delta calcolato sul prezzo API.\n"
        "            # Delta su raw (stessa valuta numeratore/denominatore) = FX-invariante.\n"
        "            api_delta_pct: float | None = None\n"
        "            if prev_close_raw > 0:\n"
        "                api_delta_pct = (last_close_raw - prev_close_raw) / prev_close_raw\n"
        "\n"
        "            # [v8.1.0 FIX Sett3] Converti prezzo nativo → USD\n"
        "            # SWDA.L: 10426 GBX → ~132 USD (era bug: mostrava 10426 come USD)\n"
        "            native_ccy = get_instrument_native_currency(yf_ticker)\n"
        "            last_close = self._currency_converter.to_usd(last_close_raw, native_ccy)\n"
        "\n"
        "            # Override manuale (Rule 43): l'utente puo' aver corretto il prezzo.\n"
        "            final_value, is_override = self._override_store.resolve(\n"
        "                \"price\", term, last_close\n"
        "            )\n"
    )

    if not apply_str_replace(
        path, old=old_extract_block, new=new_extract_block,
        label="Aggiunge FX conversion in _extract_kpi (fix GBX bug)",
        dry_run=dry_run,
    ):
        # Fallback regex: cerca il blocco con pattern più flessibile
        print("  ⚠️  Exact match fallito per _extract_kpi — provo regex fallback")
        _patch_extract_kpi_regex(path, dry_run=dry_run)


def _patch_extract_kpi_regex(path: pathlib.Path, *, dry_run: bool) -> None:
    """Fallback regex per _extract_kpi quando l'exact match fallisce."""
    txt = read(path)

    # Cerca il blocco: last_close = float(...) fino a override_store.resolve(...)
    pattern = re.compile(
        r"( {12})(last_close = float\(ticker_data\[close_col\]\.iloc\[-1\]\)\n"
        r" {12}prev_close = \(\n"
        r" {16}float\(ticker_data\[close_col\]\.iloc\[-2\]\)\n"
        r" {16}if len\(ticker_data\) >= 2\n"
        r" {16}else last_close\n"
        r" {12}\)\n)"
        r".*?"
        r"( {12}final_value, is_override = self\._override_store\.resolve\(\n"
        r" {16}\"price\", term, last_close\n"
        r" {12}\)\n)",
        re.DOTALL
    )

    m = pattern.search(txt)
    if not m:
        print("  ❌  _extract_kpi regex fallback: blocco non trovato")
        print("       Modifica manuale richiesta — vedi ISTRUZIONI_MANUALI.md")
        _create_manual_instructions(path.parent.parent.parent)
        return

    full_match = m.group(0)
    indent = "            "  # 12 spazi

    replacement = (
        f"{indent}# Legge i prezzi raw nella valuta nativa del ticker\n"
        f"{indent}last_close_raw = float(ticker_data[close_col].iloc[-1])\n"
        f"{indent}prev_close_raw = (\n"
        f"{indent}    float(ticker_data[close_col].iloc[-2])\n"
        f"{indent}    if len(ticker_data) >= 2\n"
        f"{indent}    else last_close_raw\n"
        f"{indent})\n"
        "\n"
        f"{indent}# Sanity check sul prezzo raw (prima della conversione FX)\n"
        f"{indent}violations = self._sanity.check_price_data(\n"
        f"{indent}    yf_ticker, last_close_raw, prev_close=prev_close_raw\n"
        f"{indent})\n"
        f"{indent}if not self._sanity.is_safe_to_store(violations):\n"
        f"{indent}    cached = self._lookup_cached(term)\n"
        f"{indent}    if cached is not None:\n"
        f"{indent}        return MarketKpi(\n"
        f"{indent}            term=term,\n"
        f"{indent}            yf_ticker=yf_ticker,\n"
        f"{indent}            value=cached.value,\n"
        f"{indent}            delta_pct=cached.delta_pct,\n"
        f"{indent}            currency=cached.currency,\n"
        f"{indent}            format_spec=fmt,\n"
        f"{indent}            is_stale=True,\n"
        f'{indent}            error="sanity violation, using last good value",\n'
        f"{indent}        )\n"
        "\n"
        f"{indent}# Delta FX-invariante (stesso numeratore/denominatore)\n"
        f"{indent}api_delta_pct: float | None = None\n"
        f"{indent}if prev_close_raw > 0:\n"
        f"{indent}    api_delta_pct = (last_close_raw - prev_close_raw) / prev_close_raw\n"
        "\n"
        f"{indent}# [v8.1.0 FIX Sett3] Converti prezzo nativo → USD\n"
        f"{indent}native_ccy = get_instrument_native_currency(yf_ticker)\n"
        f"{indent}last_close = self._currency_converter.to_usd(last_close_raw, native_ccy)\n"
        "\n"
        f"{indent}# Override manuale (Rule 43)\n"
        f"{indent}final_value, is_override = self._override_store.resolve(\n"
        f'{indent}    "price", term, last_close\n'
        f"{indent})\n"
    )

    new_txt = txt.replace(full_match, replacement, 1)
    if not dry_run:
        write(path, new_txt)
    print("  ✅  [live_market_service.py] OK — _extract_kpi aggiornato (regex fallback)")


def _create_manual_instructions(root: pathlib.Path) -> None:
    """Crea un file con istruzioni manuali se tutti i patch falliscono."""
    instr = (
        "ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py\n"
        "=" * 60 + "\n\n"
        "Se il patch automatico non riesce, modifica manualmente:\n\n"
        "1. Trova la funzione _extract_kpi\n"
        "2. Dopo le righe:\n"
        "     last_close = float(ticker_data[close_col].iloc[-1])\n"
        "     prev_close = ...\n\n"
        "   Rinomina le variabili in last_close_raw e prev_close_raw\n\n"
        "3. Dopo la sezione 'api_delta_pct', aggiungi:\n"
        "     native_ccy = get_instrument_native_currency(yf_ticker)\n"
        "     last_close = self._currency_converter.to_usd(last_close_raw, native_ccy)\n\n"
        "4. Usa last_close (in USD) per l'override_store.resolve()\n"
    )
    dst = root / "ISTRUZIONI_MANUALI_SETT3.md"
    dst.write_text(instr, encoding="utf-8")
    print(f"  📄  Istruzioni manuali create: {dst.name}")


# ──────────────────────────────────────────────────────────── verify


def verify_definition_of_done(root: pathlib.Path) -> int:
    """Verifica i criteri del Definition of Done. Ritorna n° di ❌."""
    print("\n" + "─" * 62)
    print("  VERIFICA DEFINITION OF DONE — Settimana 3")
    print("─" * 62)

    fails = 0

    def ck(ok: bool, label: str) -> None:
        nonlocal fails
        if ok:
            print(f"  ✅  {label}")
        else:
            fails += 1
            print(f"  ❌  {label}")

    cc_path = root / "engine" / "market_data" / "currency_converter.py"
    lms_path = root / "engine" / "market_data" / "live_market_service.py"
    test_path = root / "tests" / "engine" / "test_currency_converter.py"

    ck(cc_path.exists(), "currency_converter.py creato")
    ck(test_path.exists(), "test_currency_converter.py creato")

    if lms_path.exists():
        txt = _n(lms_path.read_text(encoding="utf-8", errors="ignore"))
        ck("from engine.market_data.currency_converter import" in txt,
           "live_market_service: import CurrencyConverter")
        ck("self._currency_converter = CurrencyConverter()" in txt,
           "live_market_service: self._currency_converter in __init__")
        ck("get_instrument_native_currency(yf_ticker)" in txt,
           "live_market_service: _extract_kpi usa get_instrument_native_currency")
        ck("self._currency_converter.to_usd(" in txt,
           "live_market_service: _extract_kpi usa CurrencyConverter.to_usd")
        ck("last_close_raw" in txt,
           "live_market_service: variabili raw rinominate")
    else:
        fails += 5
        print("  ❌  live_market_service.py non trovato")

    print(f"\n  Risultato: {(7 - fails)} ✅  {fails} ❌")
    return fails


# ──────────────────────────────────────────────────────────────── main


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MarketAI v8.1.0 — Patch Settimana 3 (CurrencyConverter)"
    )
    parser.add_argument("--root", default=".", help="Cartella radice del progetto")
    parser.add_argument("--dry-run", action="store_true", help="Simula senza scrivere")
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    dry_run: bool = args.dry_run
    files_dir = pathlib.Path(__file__).parent / "files"

    if not root.exists() or not (root / "personal").exists():
        print(f"❌  '{root}' non sembra la radice di MarketAI.")
        sys.exit(1)

    if not files_dir.exists():
        print(f"❌  Cartella 'files/' non trovata accanto allo script.")
        sys.exit(1)

    mode = "DRY-RUN" if dry_run else "APPLICAZIONE REALE"
    print(f"\n{'='*62}")
    print(f"  MarketAI v8.1.0  |  Patch Settimana 3 — CurrencyConverter")
    print(f"  Modalità : {mode}")
    print(f"  Cartella : {root}")
    print(f"{'='*62}")

    patch_create_new_files(root, files_dir, dry_run=dry_run)
    patch_live_market_service(root, dry_run=dry_run)

    if not dry_run:
        fails = verify_definition_of_done(root)

    print(f"\n{'='*62}")
    if dry_run:
        print("  Dry-run completato. Riesegui senza --dry-run per applicare.")
    else:
        if fails == 0:
            print("  ✅  Patch applicata con successo!")
        else:
            print(f"  ⚠️  Patch applicata con {fails} problemi — verifica sopra")
        print()
        print("  VERIFICA:")
        print("  pytest tests/engine/test_currency_converter.py -v")
        print("  pytest tests/engine/test_hardening/test_live_market_service.py -v")
        print("  pytest --tb=short -q")
        print()
        print("  PROSSIMA SESSIONE: Settimana 4 — InstrumentRegistry su DuckDB")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
