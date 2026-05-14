#!/usr/bin/env python3
"""diagnose_and_fix.py — MarketAI Settimana 2: diagnostica + fix adattivo

Questo script:
  1. Legge il contenuto REALE dei file nel tuo progetto
  2. Identifica cosa deve essere modificato (indipendentemente dalle variazioni di testo)
  3. Applica le modifiche usando regex robuste invece di exact-match

Uso:
    python diagnose_and_fix.py [--root PERCORSO] [--dry-run] [--diagnose-only]

Flags:
    --dry-run        mostra le modifiche senza scrivere
    --diagnose-only  mostra solo la diagnostica (non applica niente)
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

# ────────────────────────────────────────────────────────────── helpers


def _n(text: str) -> str:
    return text.replace("\r\n", "\n")


def read(path: pathlib.Path) -> str:
    return _n(path.read_text(encoding="utf-8", errors="replace"))


def write(path: pathlib.Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def show_context(content: str, pattern: str, n_lines: int = 4) -> None:
    """Mostra le righe intorno al match di pattern nel contenuto."""
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if pattern.lower() in line.lower():
            start = max(0, i - 1)
            end = min(len(lines), i + n_lines)
            for j, l in enumerate(lines[start:end], start=start + 1):
                marker = ">>>" if j == i + 1 else "   "
                print(f"  {marker} {j:4d}: {l}")
            print()


# ────────────────────────────────────────────────────────── diagnostics


def diagnose_etoro_client(path: pathlib.Path) -> dict:
    """Analizza etoro_client.py e restituisce lo stato delle modifiche."""
    if not path.exists():
        return {"found": False}

    txt = read(path)
    result = {
        "found": True,
        "has_op_config_import": "from shared.config.operational_config import OP_CONFIG" in txt,
        "has_default_timeout_literal": "_DEFAULT_TIMEOUT = 15.0" in txt,
        "has_default_timeout_op": "_DEFAULT_TIMEOUT: float = OP_CONFIG" in txt
                                   or "_DEFAULT_TIMEOUT = OP_CONFIG" in txt,
        "has_default_retries_literal": "_DEFAULT_MAX_RETRIES = 3" in txt,
        "has_2048_literal": "exc.read(2048)" in txt,
        "has_2048_op": "OP_CONFIG.http.error_body_preview_bytes" in txt,
        "content": txt,
    }

    # Pattern per trovare il blocco _DEFAULT_* nella variante reale
    result["default_block_match"] = re.search(
        r"_DEFAULT_TIMEOUT\s*=\s*\d+\.?\d*.*\n"
        r"_DEFAULT_MAX_RETRIES\s*=\s*\d+.*\n"
        r"_DEFAULT_RETRY_BASE_DELAY\s*=\s*\d+\.?\d*",
        txt
    )
    return result


def diagnose_live_market_service(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"found": False}

    txt = read(path)
    result = {
        "found": True,
        "has_op_config_import": "from shared.config.operational_config import OP_CONFIG" in txt,
        "has_ttl_literal": re.search(r"_TTL_SECONDS\s*=\s*60", txt) is not None,
        "has_ttl_op": "OP_CONFIG.cache.live_market_ttl_s" in txt,
        "content": txt,
    }

    # Cerca la riga esatta del TTL
    ttl_match = re.search(r"^.*_TTL_SECONDS\s*=.*$", txt, re.MULTILINE)
    result["ttl_line"] = ttl_match.group(0) if ttl_match else None

    # Cerca dove importare OP_CONFIG (dopo ultimo import nella sezione import)
    result["import_section_end"] = re.search(
        r"(from shared\.logger import get_logger\n|"
        r"from shared\..*import.*\n|"
        r"from engine\..*import.*\n|"
        r"from personal\..*import.*\n)"
        r"(?!\s*from|\s*import)",
        txt
    )
    return result


# ────────────────────────────────────────────────────────────── fixers


def fix_etoro_client(path: pathlib.Path, diag: dict, *, dry_run: bool) -> None:
    txt = diag["content"]
    changed = False

    print(f"\n[2.D] etoro_client.py — fix adattivo")

    # Step 1: Aggiunge import OP_CONFIG se mancante
    if not diag["has_op_config_import"]:
        # Cerca il blocco import da etoro_models (varie formattazioni possibili)
        pattern = re.compile(
            r"(from personal\.data_entry\.etoro_models import\s*\([^)]+\)\n)",
            re.DOTALL
        )
        m = pattern.search(txt)
        if m:
            old_block = m.group(1)
            new_block = old_block + "from shared.config.operational_config import OP_CONFIG\n"
            txt = txt.replace(old_block, new_block, 1)
            changed = True
            print("  ✅  Aggiunto: from shared.config.operational_config import OP_CONFIG")
        else:
            # Fallback: aggiunge dopo tutti gli import locali
            pattern2 = re.compile(r"(from personal\.data_entry\.\w+ import[^\n]+\n)(?!from personal)")
            m2 = pattern2.search(txt)
            if m2:
                old = m2.group(0)
                txt = txt.replace(old, old + "from shared.config.operational_config import OP_CONFIG\n", 1)
                changed = True
                print("  ✅  Aggiunto: import OP_CONFIG (fallback position)")
            else:
                print("  ❌  Non riesco a trovare dove inserire import OP_CONFIG")
                print("       Aggiungi manualmente: from shared.config.operational_config import OP_CONFIG")
    else:
        print("  ⚠️  import OP_CONFIG già presente — skip")

    # Step 2: Sostituisce _DEFAULT_TIMEOUT/MAX_RETRIES/RETRY_DELAY con OP_CONFIG
    if diag["has_default_timeout_literal"] or diag["has_default_retries_literal"]:
        # Pattern robusto: cattura il blocco con commento opzionale
        pattern = re.compile(
            r"(?:# .*timeout.*\n|# Default timeouts?\n)?"
            r"(_DEFAULT_TIMEOUT\s*=\s*\d+\.?\d*\s*(?:#[^\n]*)?\n)"
            r"(_DEFAULT_MAX_RETRIES\s*=\s*\d+\s*(?:#[^\n]*)?\n)"
            r"(_DEFAULT_RETRY_BASE_DELAY\s*=\s*\d+\.?\d*\s*(?:#[^\n]*)?\n)",
            re.MULTILINE
        )
        m = pattern.search(txt)
        if m:
            full_match = m.group(0)
            replacement = (
                "# [v8.1.0 FIX-P4] Costanti operative → config/operational_defaults.yaml\n"
                "# Per modificare questi valori, aggiornare il YAML e riavviare.\n"
                "_DEFAULT_TIMEOUT: float = OP_CONFIG.http.default_timeout_s\n"
                "_DEFAULT_MAX_RETRIES: int = OP_CONFIG.http.max_retries\n"
                "_DEFAULT_RETRY_BASE_DELAY: float = OP_CONFIG.http.retry_base_delay_s\n"
            )
            txt = txt.replace(full_match, replacement, 1)
            changed = True
            print("  ✅  Sostituiti _DEFAULT_TIMEOUT/MAX_RETRIES/RETRY_DELAY con OP_CONFIG")
        else:
            # Prova a sostituirli individualmente
            print("  ⚠️  Blocco _DEFAULT_* non trovato come gruppo — provo sostituzione individuale")
            subs = [
                (re.compile(r"_DEFAULT_TIMEOUT\s*=\s*\d+\.?\d*\s*(?:#[^\n]*)?"),
                 "_DEFAULT_TIMEOUT: float = OP_CONFIG.http.default_timeout_s  # [v8.1.0 FIX-P4]"),
                (re.compile(r"_DEFAULT_MAX_RETRIES\s*=\s*\d+\s*(?:#[^\n]*)?"),
                 "_DEFAULT_MAX_RETRIES: int = OP_CONFIG.http.max_retries  # [v8.1.0 FIX-P4]"),
                (re.compile(r"_DEFAULT_RETRY_BASE_DELAY\s*=\s*\d+\.?\d*\s*(?:#[^\n]*)?"),
                 "_DEFAULT_RETRY_BASE_DELAY: float = OP_CONFIG.http.retry_base_delay_s  # [v8.1.0 FIX-P4]"),
            ]
            for pat, rep in subs:
                new_txt = pat.sub(rep, txt, count=1)
                if new_txt != txt:
                    txt = new_txt
                    changed = True
                    print(f"  ✅  Sostituito: {pat.pattern[:40]}...")
                else:
                    print(f"  ⚠️  Non trovato: {pat.pattern[:40]}...")
    elif diag["has_default_timeout_op"]:
        print("  ⚠️  _DEFAULT_* già puntano a OP_CONFIG — skip")
    else:
        print("  ❌  _DEFAULT_* non trovati. Verifica il file manualmente.")

    # Step 3: Sostituisce 2048 con OP_CONFIG
    if diag["has_2048_literal"]:
        # Pattern robusto per .read(2048)
        pattern = re.compile(r"exc\.read\(\s*2048\s*\)")
        m = pattern.search(txt)
        if m:
            txt = pattern.sub("exc.read(OP_CONFIG.http.error_body_preview_bytes)", txt, count=1)
            changed = True
            print("  ✅  Sostituito exc.read(2048) con OP_CONFIG.http.error_body_preview_bytes")
        else:
            # Cerca con body_preview
            pattern2 = re.compile(r"body_preview\s*=\s*exc\.read\(2048\)")
            if pattern2.search(txt):
                txt = pattern2.sub(
                    "body_preview = exc.read(OP_CONFIG.http.error_body_preview_bytes)", txt, count=1
                )
                changed = True
                print("  ✅  Sostituito body_preview = exc.read(2048)")
    elif diag["has_2048_op"]:
        print("  ⚠️  2048 già sostituito con OP_CONFIG — skip")
    else:
        print("  ❌  Pattern exc.read(2048) non trovato")

    if changed and not dry_run:
        write(path, txt)
        print(f"  💾  etoro_client.py salvato")
    elif changed and dry_run:
        print(f"  [DRY-RUN] etoro_client.py NON salvato")


def fix_live_market_service(path: pathlib.Path, diag: dict, *, dry_run: bool) -> None:
    txt = diag["content"]
    changed = False

    print(f"\n[2.D] live_market_service.py — fix adattivo")

    # Step 1: Aggiunge import OP_CONFIG
    if not diag["has_op_config_import"]:
        # Cerca 'from shared.logger import get_logger' o l'ultimo import shared/engine/personal
        patterns_to_try = [
            re.compile(r"(from shared\.logger import get_logger\n)"),
            re.compile(r"(from shared\.\w+ import[^\n]+\n)(?!from shared)"),
            re.compile(r"(from engine\.\w[^\n]+\n)(?!from engine|from personal)"),
        ]
        inserted = False
        for pat in patterns_to_try:
            m = pat.search(txt)
            if m:
                anchor = m.group(1)
                txt = txt.replace(
                    anchor,
                    "from shared.config.operational_config import OP_CONFIG\n" + anchor,
                    1
                )
                inserted = True
                changed = True
                print("  ✅  Aggiunto: from shared.config.operational_config import OP_CONFIG")
                break
        if not inserted:
            print("  ❌  Non riesco a trovare dove inserire import OP_CONFIG")
            print("       Aggiungi manualmente PRIMA di: from shared.logger import get_logger")
    else:
        print("  ⚠️  import OP_CONFIG già presente — skip")

    # Step 2: Sostituisce _TTL_SECONDS = 60.0 (in qualsiasi variante)
    if diag["has_ttl_literal"]:
        # Cerca il blocco con commento opzionale sopra
        pattern = re.compile(
            r"(# TTL della cache[^\n]*\n)?"
            r"(_TTL_SECONDS\s*=\s*60\.?\d*\s*(?:#[^\n]*)?)",
            re.MULTILINE
        )
        m = pattern.search(txt)
        if m:
            full = m.group(0)
            replacement = (
                "# [v8.1.0 FIX-P4] TTL centralizzato → config/operational_defaults.yaml\n"
                "# (cache.live_market_ttl_s). Regola 25: latency real-time ≤ 60s.\n"
                "_TTL_SECONDS: float = OP_CONFIG.cache.live_market_ttl_s"
            )
            txt = txt.replace(full, replacement, 1)
            changed = True
            print("  ✅  Sostituito _TTL_SECONDS = 60.0 con OP_CONFIG.cache.live_market_ttl_s")
        else:
            # Sostituzione più aggressiva: qualsiasi _TTL_SECONDS = numero
            pattern2 = re.compile(r"_TTL_SECONDS\s*=\s*\d+\.?\d*(?:\s*#[^\n]*)?")
            new_txt = pattern2.sub(
                "_TTL_SECONDS: float = OP_CONFIG.cache.live_market_ttl_s  # [v8.1.0 FIX-P4]",
                txt, count=1
            )
            if new_txt != txt:
                txt = new_txt
                changed = True
                print("  ✅  Sostituito _TTL_SECONDS (pattern aggressivo)")
            else:
                print("  ❌  _TTL_SECONDS non trovato")
    elif diag["has_ttl_op"]:
        print("  ⚠️  _TTL_SECONDS già usa OP_CONFIG — skip")
    else:
        print("  ❌  _TTL_SECONDS non trovato nel file")

    if changed and not dry_run:
        write(path, txt)
        print(f"  💾  live_market_service.py salvato")
    elif changed and dry_run:
        print(f"  [DRY-RUN] live_market_service.py NON salvato")


# ────────────────────────────────────────────────────────────── main


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MarketAI — Diagnostica e fix adattivo Settimana 2"
    )
    parser.add_argument("--root", default=".", help="Cartella radice del progetto")
    parser.add_argument("--dry-run", action="store_true", help="Mostra senza scrivere")
    parser.add_argument(
        "--diagnose-only", action="store_true",
        help="Stampa solo la diagnostica senza applicare modifiche"
    )
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    dry_run = args.dry_run or args.diagnose_only

    if not root.exists() or not (root / "personal").exists():
        print(f"❌  '{root}' non sembra la radice di MarketAI.")
        sys.exit(1)

    mode = "DIAGNOSI ONLY" if args.diagnose_only else ("DRY-RUN" if dry_run else "FIX REALE")
    print(f"\n{'='*62}")
    print(f"  MarketAI — Fix Adattivo Settimana 2  |  Modalità: {mode}")
    print(f"  Cartella: {root}")
    print(f"{'='*62}")

    ec_path = root / "personal" / "data_entry" / "etoro_client.py"
    lms_path = root / "engine" / "market_data" / "live_market_service.py"

    ec_diag = diagnose_etoro_client(ec_path)
    lms_diag = diagnose_live_market_service(lms_path)

    # ── Diagnostica ──────────────────────────────────────────────────────
    print("\n[DIAGNOSTICA] etoro_client.py")
    if not ec_diag["found"]:
        print("  ❌  File non trovato!")
    else:
        def ck(label: str, ok: bool) -> None:
            print(f"  {'✅' if ok else '❌'}  {label}")
        ck("import OP_CONFIG presente", ec_diag["has_op_config_import"])
        ck("_DEFAULT_TIMEOUT ancora hardcoded (15.0)", ec_diag["has_default_timeout_literal"])
        ck("_DEFAULT_TIMEOUT già usa OP_CONFIG", ec_diag["has_default_timeout_op"])
        ck("exc.read(2048) ancora hardcoded", ec_diag["has_2048_literal"])
        ck("exc.read usa OP_CONFIG", ec_diag["has_2048_op"])
        if ec_diag["default_block_match"]:
            print(f"\n  Blocco _DEFAULT_* trovato (righe):")
            show_context(ec_diag["content"], "_DEFAULT_TIMEOUT")

    print("\n[DIAGNOSTICA] live_market_service.py")
    if not lms_diag["found"]:
        print("  ❌  File non trovato!")
    else:
        ck = lambda label, ok: print(f"  {'✅' if ok else '❌'}  {label}")
        ck("import OP_CONFIG presente", lms_diag["has_op_config_import"])
        ck("_TTL_SECONDS ancora hardcoded (60.0)", lms_diag["has_ttl_literal"])
        ck("_TTL_SECONDS già usa OP_CONFIG", lms_diag["has_ttl_op"])
        if lms_diag["ttl_line"]:
            print(f"\n  Riga TTL trovata: {lms_diag['ttl_line']!r}")

    if args.diagnose_only:
        print(f"\n{'='*62}")
        print("  Diagnosi completata. Riesegui senza --diagnose-only per applicare.")
        print(f"{'='*62}\n")
        return

    # ── Fix ──────────────────────────────────────────────────────────────
    needs_fix_ec = (
        ec_diag["found"]
        and (
            not ec_diag["has_op_config_import"]
            or ec_diag["has_default_timeout_literal"]
            or ec_diag["has_2048_literal"]
        )
    )
    needs_fix_lms = (
        lms_diag["found"]
        and (not lms_diag["has_op_config_import"] or lms_diag["has_ttl_literal"])
    )

    if not needs_fix_ec:
        print("\n[2.D] etoro_client.py — già completamente aggiornato ✅")
    else:
        fix_etoro_client(ec_path, ec_diag, dry_run=dry_run)

    if not needs_fix_lms:
        print("\n[2.D] live_market_service.py — già completamente aggiornato ✅")
    else:
        fix_live_market_service(lms_path, lms_diag, dry_run=dry_run)

    # ── Verifica finale ──────────────────────────────────────────────────
    print(f"\n{'─'*62}")
    print("  VERIFICA FINALE")
    print(f"{'─'*62}")

    def final_check(path: pathlib.Path, checks: list[tuple[str, str, bool]]) -> None:
        if not path.exists():
            return
        txt = read(path)
        for label, needle, want_present in checks:
            found = needle in txt
            ok = found == want_present
            status = "✅" if ok else "❌"
            note = "" if ok else f" (atteso: {'presente' if want_present else 'assente'})"
            print(f"  {status}  [{path.name}] {label}{note}")

    final_check(ec_path, [
        ("import OP_CONFIG", "from shared.config.operational_config import OP_CONFIG", True),
        ("_DEFAULT_TIMEOUT usa OP_CONFIG", "OP_CONFIG.http.default_timeout_s", True),
        ("_DEFAULT_TIMEOUT hardcoded rimosso", "_DEFAULT_TIMEOUT = 15.0", False),
        ("2048 rimosso", "exc.read(2048)", False),
        ("body_preview usa OP_CONFIG", "OP_CONFIG.http.error_body_preview_bytes", True),
    ])

    final_check(lms_path, [
        ("import OP_CONFIG", "from shared.config.operational_config import OP_CONFIG", True),
        ("_TTL_SECONDS usa OP_CONFIG", "OP_CONFIG.cache.live_market_ttl_s", True),
        ("_TTL_SECONDS hardcoded rimosso", "_TTL_SECONDS = 60", False),
    ])

    print(f"\n{'='*62}")
    if not dry_run:
        print("  ✅  Fix completato!")
        print()
        print("  PROSSIMI PASSI:")
        print("  pytest tests/shared/test_operational_config.py -v")
        print("  pytest --tb=short -q")
    else:
        print("  Riesegui senza --dry-run per applicare le modifiche.")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
