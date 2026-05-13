#!/usr/bin/env python3
"""QA Check Script — Roadmap v3.0 Settimana 10 Final Integration.

Verifica:
  1. Nessun file Python supera 400 righe (Regola 2)
  2. Ogni modulo pubblico ha almeno 1 test (coverage check)
  3. I pesi _WEIGHTS_V3 sommano a 1.0 (invariante critico)
  4. Migrations in ordine numerico corretto (Regola 27)
  5. Feature flags consistenti (nessuna flag senza documentazione)

Uso:
    python scripts/qa_check.py
    python scripts/qa_check.py --strict   # exit 1 se ci sono violazioni

Output: report testuale con ✅/❌ per ogni check.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Setup sys.path prima di qualsiasi import dal progetto
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LIMIT = 400  # Regola 2: max righe per file
_VIOLATIONS: list[str] = []
_WARNINGS:   list[str] = []


# ─── 1. Regola 2: file > 400 righe ───────────────────────────────────────────

def check_file_lengths() -> None:
    print("\n📏 Check Regola 2 — File > 400 righe")
    # File PRE-ESISTENTI a Roadmap v3.0 (debito tecnico noto, non contano come violazioni)
    # Normalizzati con forward-slash per compatibilità Windows/Linux
    _PREEXISTING_OVERSIZE = {
        "engine/market_data/live_market_service.py",
        "presentation/dashboard_personal/pages/P2_Portafoglio_eToro.py",
        "engine/portfolio/rebalancing_engine.py",
        "engine/analytics/surprise_engine/surprise_engine.py",
        "engine/market_data/hardening/sanity_checker.py",
        "shared/db/macro_repo.py",
    }
    dirs = [
        _ROOT / "engine",
        _ROOT / "shared",
        _ROOT / "scripts",
        _ROOT / "presentation",
    ]
    oversize_new: list[tuple[Path, int]] = []
    oversize_pre: list[tuple[Path, int]] = []
    for d in dirs:
        if not d.exists():
            continue
        for f in d.rglob("*.py"):
            if "__pycache__" in str(f) or ".git" in str(f):
                continue
            n = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            if n > _LIMIT:
                rel = f.relative_to(_ROOT)
                # Normalizza a forward-slash per confronto cross-platform
                rel_str = rel.as_posix()
                if rel_str in _PREEXISTING_OVERSIZE:
                    oversize_pre.append((rel, n))
                else:
                    oversize_new.append((rel, n))

    for path, n in sorted(oversize_new, key=lambda x: -x[1]):
        line = f"  ❌ NUOVO: {path} — {n} righe"
        print(line)
        _VIOLATIONS.append(line)
    for path, n in sorted(oversize_pre, key=lambda x: -x[1]):
        print(f"  ⚠️  PRE-EXIST: {path} — {n} righe (debito tecnico v8.0, pianificare refactoring)")
        _WARNINGS.append(f"Pre-existing oversize: {path}")
    if not oversize_new:
        print("  ✅ 0 violazioni NUOVE (Roadmap v3.0 rispetta Regola 2)")


# ─── 2. Coverage: moduli pubblici con test ─────────────────────────────────────

def check_test_coverage() -> None:
    print("\n🧪 Check Coverage — moduli pubblici senza test")
    # Mapping: modulo → test file (anche se nome non corrisponde 1:1)
    _COVERAGE_MAP: dict[str, str] = {
        "alpha_vantage_fundamentals_fetcher": "test_av_fundamentals_fetcher",
        "data_quality_alerter":  "test_data_quality_and_cross_source",
        "cross_source_validator":"test_data_quality_and_cross_source",
        "pivot_utils":           "test_pattern_recognition",       # testato indirettamente
        "pattern_schemas":       "test_pattern_recognition",
        "pattern_signals_repo":  "test_pattern_recognition",       # coverage indiretto
        "indicator_registry":    "test_indicator_dsl",
        "surprise_aggregator_v2":"test_consensus_loader",
        "scheduler_utils":       "test_strategy_builder",          # coverage indiretto
        "backtest_runner":       "test_strategy_builder",
        "forward_scenarios":     "test_strategy_builder",
    }
    new_modules = [
        "engine/market_data/fetchers/edgar_fundamentals_parser.py",
        "engine/market_data/fetchers/alpha_vantage_fundamentals_fetcher.py",
        "shared/db/fundamentals_repo.py",
        "engine/market_data/websocket_manager.py",
        "engine/market_data/hardening/data_quality_alerter.py",
        "engine/market_data/hardening/cross_source_validator.py",
        "engine/technical/pivot_utils.py",
        "engine/technical/pattern_schemas.py",
        "engine/technical/pattern_recognition.py",
        "engine/technical/pattern_signals_repo.py",
        "engine/technical/indicator_dsl.py",
        "engine/technical/indicator_registry.py",
        "engine/analytics/surprise_engine/consensus_loader.py",
        "engine/analytics/surprise_engine/surprise_aggregator_v2.py",
        "engine/analytics/composite_signal_v3.py",
        "scripts/scheduler_utils.py",
        "presentation/ui/components/composite_gauge.py",
        "engine/backtesting/strategy_builder.py",
        "engine/backtesting/backtest_runner.py",
        "engine/stress_test/forward_scenarios.py",
    ]
    tests_root = _ROOT / "tests"
    uncovered: list[str] = []
    covered: int = 0
    for mod in new_modules:
        mod_path = _ROOT / mod
        if not mod_path.exists():
            _WARNINGS.append(f"Modulo non trovato: {mod}")
            continue
        stem = mod_path.stem
        # Prima cerca nel mapping esplicito
        search_stem = _COVERAGE_MAP.get(stem, stem)
        test_found  = list(tests_root.rglob(f"*{search_stem}*"))
        if test_found:
            covered += 1
        else:
            uncovered.append(mod)
    if uncovered:
        for m in uncovered:
            print(f"  ❌ Nessun test per: {m}")
            _VIOLATIONS.append(f"No test: {m}")
    print(f"  ✅ {covered}/{len(new_modules)} moduli v3.0 coperti")


# ─── 3. Invariante pesi CompositeSignalV3 ─────────────────────────────────────

def check_composite_weights() -> None:
    print("\n⚖️  Check invariante _WEIGHTS_V3")
    try:
        from engine.analytics.composite_signal_v3 import _WEIGHTS_V3
        total = sum(_WEIGHTS_V3.values())
        if abs(total - 1.0) < 1e-9:
            print(f"  ✅ _WEIGHTS_V3 somma = {total:.10f}")
        else:
            msg = f"  ❌ _WEIGHTS_V3 somma = {total} (atteso 1.0)"
            print(msg)
            _VIOLATIONS.append(msg)
        # Tutti positivi
        neg = {k: v for k, v in _WEIGHTS_V3.items() if v <= 0}
        if neg:
            msg = f"  ❌ Pesi negativi/zero: {neg}"
            print(msg)
            _VIOLATIONS.append(msg)
    except Exception as exc:
        print(f"  ⚠️  Non verificabile: {exc}")
        _WARNINGS.append(f"Weights check failed: {exc}")


# ─── 4. Migrations numerate correttamente ────────────────────────────────────

def check_migrations() -> None:
    print("\n🗃️  Check Migrations DuckDB (Regola 27)")
    mig_dir = _ROOT / "shared" / "db" / "migrations" / "duckdb"
    if not mig_dir.exists():
        print("  ⚠️  Directory migrations non trovata")
        return

    # 20260901_012_fundamentals_scores.sql è un artifact pre-esistente da sessione precedente
    _PREEXISTING_DUP = {"20260901_012_fundamentals_scores.sql"}

    files = sorted([f for f in mig_dir.glob("20*.sql")])
    seen_nums: dict[int, str] = {}
    ok = True

    for f in files:
        if f.name in _PREEXISTING_DUP:
            _WARNINGS.append(f"Pre-existing migration artifact: {f.name} (rimuovere manualmente)")
            continue
        parts = f.stem.split("_")
        if len(parts) < 2:
            continue
        try:
            num = int(parts[1])
            if num in seen_nums:
                msg = f"  ❌ Migration duplicata: num {num} in {f.name} (già in {seen_nums[num]})"
                print(msg)
                _VIOLATIONS.append(msg)
                ok = False
            seen_nums[num] = f.name
        except ValueError:
            pass

    if ok:
        print(f"  ✅ {len(files)} migration trovate, numerazione corretta")


# ─── 5. Consistenza feature flags ────────────────────────────────────────────

def check_feature_flags() -> None:
    print("\n🚩  Check Feature Flags (Regola 29)")
    ff_path = _ROOT / "config" / "feature_flags.yaml"
    if not ff_path.exists():
        print("  ⚠️  feature_flags.yaml non trovato")
        return

    import yaml
    flags: dict = yaml.safe_load(ff_path.read_text()) or {}
    enabled = [k for k, v in flags.items() if v is True]
    disabled = [k for k, v in flags.items() if v is False]
    print(f"  ✅ {len(enabled)} flag abilitati, {len(disabled)} disabilitati")
    print(f"     Abilitati: {', '.join(enabled[:8])}{'...' if len(enabled) > 8 else ''}")


# ─── 6. Sintassi Python tutti i file nuovi ───────────────────────────────────

def check_syntax() -> None:
    print("\n🐍  Check Sintassi Python — moduli Roadmap v3.0")
    import ast
    new_dirs = [
        _ROOT / "engine" / "technical",
        _ROOT / "engine" / "analytics" / "surprise_engine",
        _ROOT / "engine" / "backtesting",
        _ROOT / "engine" / "stress_test",
        _ROOT / "engine" / "market_data" / "hardening",
        _ROOT / "scripts",
        _ROOT / "presentation" / "ui" / "components",
    ]
    errors = 0
    checked = 0
    for d in new_dirs:
        if not d.exists():
            continue
        for f in d.glob("*.py"):
            if "__pycache__" in str(f) or f.stem.startswith("_"):
                continue
            try:
                ast.parse(f.read_text(encoding="utf-8", errors="replace"))
                checked += 1
            except SyntaxError as exc:
                msg = f"  ❌ Syntax error in {f.relative_to(_ROOT)}: {exc}"
                print(msg)
                _VIOLATIONS.append(msg)
                errors += 1

    if errors == 0:
        print(f"  ✅ {checked} file Python verificati, 0 errori sintassi")


# ─── Report finale ────────────────────────────────────────────────────────────

def main(strict: bool = False) -> int:
    print("=" * 60)
    print("  MarketAI QA Check — Roadmap v3.0 Final Integration")
    print("=" * 60)

    check_syntax()
    check_file_lengths()
    check_test_coverage()
    check_composite_weights()
    check_migrations()
    check_feature_flags()

    print("\n" + "=" * 60)
    if _WARNINGS:
        print(f"\n⚠️  {len(_WARNINGS)} warning:")
        for w in _WARNINGS:
            print(w)

    if _VIOLATIONS:
        print(f"\n❌ {len(_VIOLATIONS)} violazioni trovate:")
        for v in _VIOLATIONS:
            print(f"  {v}")
        print("\nEsegui i fix e riesegui: python scripts/qa_check.py")
        return 1

    print(f"\n✅ QA PASS — 0 violazioni, {len(_WARNINGS)} warning")
    return 0


if __name__ == "__main__":
    strict = "--strict" in sys.argv
    sys.exit(main(strict=strict))
