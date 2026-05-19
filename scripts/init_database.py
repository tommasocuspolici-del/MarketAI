#!/usr/bin/env python3
"""MarketAI — Inizializzazione database (DuckDB + SQLite).

Esegue:
  1. Crea DuckDB in db/market_data.duckdb
  2. Applica tutte le migration DuckDB pendenti
  3. Crea SQLite in db/personal.sqlite
  4. Applica tutte le migration SQLite (Alembic)
  5. Verifica le tabelle create

Uso:
  python scripts/init_database.py
  python scripts/init_database.py --force   # ricrea da zero (ATTENZIONE: cancella dati)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def _info(msg: str) -> None:
    print(f"  ℹ️  {msg}")


def _err(msg: str) -> None:
    print(f"  ❌ {msg}")


def _progress(step: int, total: int, label: str) -> None:
    pct = int(step / total * 100)
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"  [{bar}] {pct:3d}% {label}", end="\r" if pct < 100 else "\n", flush=True)


def init_duckdb(force: bool = False) -> bool:
    """Crea DuckDB e applica migration."""
    print("\n→ DuckDB (market data)")
    try:
        from shared.env_loader import load_environment
        load_environment()

        from shared.db.duckdb_client import get_duckdb_client
        client = get_duckdb_client()

        from shared.db.duckdb_migrator import DuckDBMigrator
        migrator = DuckDBMigrator(client=client)

        # Conta migration disponibili
        migrations = migrator.list_migrations()
        total = len(migrations)
        _info(f"{total} migration DuckDB trovate")

        t0 = time.monotonic()
        for i, mig in enumerate(migrations, 1):
            _progress(i, total, mig.get("name", f"migration_{i}"))
            time.sleep(0.01)  # prevent flicker

        applied = migrator.apply_pending()
        elapsed = (time.monotonic() - t0) * 1000

        _ok(f"{applied} migration applicate in {elapsed:.0f}ms")

        # Verifica tabelle chiave
        key_tables = [
            "ohlcv_data", "macro_data", "vix_strategy_outputs",
            "engine_composite_signal", "news_articles",
        ]
        rows = client.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        )
        existing = {r[0] for r in (rows or [])}
        missing  = [t for t in key_tables if t not in existing]

        if missing:
            _warn(f"Tabelle non ancora create (saranno create allo scheduler): {', '.join(missing[:3])}")
        else:
            _ok("Tabelle chiave presenti")

        return True

    except Exception as exc:
        _err(f"DuckDB init fallito: {exc}")
        return False


def init_sqlite() -> bool:
    """Crea SQLite e applica migration Alembic."""
    print("\n→ SQLite (dati personali)")
    try:
        from shared.db.migrations_runner import apply_sqlite_migrations
        report = apply_sqlite_migrations()

        if report.error:
            _warn(f"SQLite migration con warning: {report.error[:100]}")
        else:
            n = len(report.applied) if report.applied else 0
            _ok(f"SQLite pronto — {n} migration applicate")
        return True

    except Exception as exc:
        _err(f"SQLite init fallito: {exc}")
        return False


def verify_installation() -> bool:
    """Verifica rapida che tutto sia in ordine."""
    print("\n→ Verifica installazione")
    checks = 0
    passed = 0

    # DuckDB connessione
    checks += 1
    try:
        from shared.db.duckdb_client import get_duckdb_client
        client = get_duckdb_client()
        client.query("SELECT 1")
        passed += 1
        _ok("DuckDB connessione OK")
    except Exception as e:
        _err(f"DuckDB: {e}")

    # SQLite connessione
    checks += 1
    try:
        from shared.db.sqlite_client import get_sqlite_client
        sc = get_sqlite_client()
        passed += 1
        _ok("SQLite connessione OK")
    except Exception as e:
        _err(f"SQLite: {e}")

    # Config loaded
    checks += 1
    try:
        from shared.config.cache_ttl_config import CACHE_TTL
        assert CACHE_TTL.get("prezzi_daily") is not None
        passed += 1
        _ok("Config cache_ttl.yaml OK")
    except Exception as e:
        _err(f"Config: {e}")

    # Feature flags
    checks += 1
    try:
        from shared.feature_flags import is_enabled
        assert is_enabled("news_engine_enabled") is not None
        passed += 1
        _ok("Feature flags OK")
    except Exception as e:
        _err(f"Feature flags: {e}")

    print(f"\n  Verifica: {passed}/{checks} check superati")
    return passed == checks


def main() -> int:
    parser = argparse.ArgumentParser(description="MarketAI — Init Database")
    parser.add_argument("--force", action="store_true",
                        help="Ricrea DB da zero (ATTENZIONE: cancella dati esistenti)")
    args = parser.parse_args()

    print("=" * 50)
    print("  MarketAI — Inizializzazione Database")
    print("=" * 50)

    if args.force:
        print("\n  ⚠️  MODALITÀ FORCE: i dati esistenti saranno eliminati.")
        resp = input("  Conferma (digita 'SI' per procedere): ").strip()
        if resp != "SI":
            print("  Operazione annullata.")
            return 0
        # Elimina DB esistenti
        for db_file in [ROOT / "db" / "market_data.duckdb",
                        ROOT / "db" / "personal.sqlite"]:
            if db_file.exists():
                db_file.unlink()
                print(f"  Eliminato: {db_file.name}")

    ok_duck  = init_duckdb(force=args.force)
    ok_sql   = init_sqlite()
    ok_check = verify_installation()

    print("\n" + "=" * 50)
    if ok_duck and ok_sql:
        print("  ✅ DATABASE PRONTI")
        if not ok_check:
            print("  ⚠️  Alcuni check di verifica non superati.")
            print("     Controlla i log sopra.")
    else:
        print("  ❌ INIZIALIZZAZIONE CON ERRORI")
        print("     Controlla i log sopra e riprova.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
