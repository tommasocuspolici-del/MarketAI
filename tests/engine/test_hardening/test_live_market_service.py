"""Test dei bugfix v7.1.1 in LiveMarketService.

Verifica:
  1. get_live_market_service() e' un vero singleton thread-safe.
  2. get_kpi_snapshot() concorrente non scatena fetch HTTP paralleli.
  3. delta_pct con override attivo riflette il movimento del prezzo API,
     non il delta artificiale dell'override.
"""
from __future__ import annotations

import threading
import time

import pytest

from engine.market_data.live_market_service import (
    LiveMarketService,
    MarketKpi,
    MarketSnapshot,
    _reset_singleton_for_testing,
    get_live_market_service,
)


# ===================================================== singleton thread-safety
def test_singleton_returns_same_instance() -> None:
    """get_live_market_service() restituisce sempre la stessa istanza."""
    a = get_live_market_service()
    b = get_live_market_service()
    assert a is b


def test_singleton_concurrent_construction() -> None:
    """100 thread che chiamano get_live_market_service() devono ottenere
    un'unica istanza, mai due istanze separate.

    Bugfix v7.1.1: il pattern precedente
        if _singleton is None:
            _singleton = LiveMarketService()
    poteva creare 2 istanze se due thread superavano il check 'is None'
    contemporaneamente. Ora con double-checked locking il problema e' risolto.
    """
    # Reset singleton per test pulito
    _reset_singleton_for_testing()

    instances = []
    barrier = threading.Barrier(50)

    def worker() -> None:
        barrier.wait()  # Sync di partenza
        instances.append(get_live_market_service())

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(instances) == 50
    # TUTTE le istanze devono essere la stessa
    first = instances[0]
    assert all(inst is first for inst in instances)


# ============================================== get_kpi_snapshot single-flight
class _MockService(LiveMarketService):
    """Sottoclasse di LiveMarketService che traccia quante volte fa fetch."""

    def __init__(self, fetch_delay: float = 0.5) -> None:
        super().__init__()
        self.fetch_count = 0
        self.fetch_delay = fetch_delay

    def _fetch_snapshot(self) -> MarketSnapshot:
        # Simula un fetch lento (che e' la condizione per la race condition)
        self.fetch_count += 1
        time.sleep(self.fetch_delay)
        snap = MarketSnapshot()
        snap.fetched_at = time.time()
        snap.kpis = [
            MarketKpi(
                term="VIX",
                yf_ticker="^VIX",
                value=18.5,
                delta_pct=0.02,
                currency="USD",
                format_spec=".2f",
            )
        ]
        return snap


def test_concurrent_get_snapshot_single_fetch() -> None:
    """10 thread che chiamano get_kpi_snapshot() simultaneamente con cache
    fredda devono produrre ESATTAMENTE 1 fetch HTTP, non 10.

    Bugfix v7.1.1: prima di questo fix, il lock veniva rilasciato PRIMA di
    chiamare _fetch_and_cache(), quindi se la cache era scaduta tutti i
    thread superavano il check e correvano a fare il proprio download.
    """
    svc = _MockService(fetch_delay=0.3)

    barrier = threading.Barrier(10)
    results = []

    def worker() -> None:
        barrier.wait()
        results.append(svc.get_kpi_snapshot())

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    # CRITICAL: solo UN fetch HTTP deve essere stato eseguito
    assert svc.fetch_count == 1, (
        f"Race condition: {svc.fetch_count} fetch eseguiti, atteso 1"
    )
    # Tutti i risultati devono essere lo stesso snapshot
    assert all(r.kpis[0].value == 18.5 for r in results)


def test_concurrent_get_snapshot_uses_valid_cache() -> None:
    """Se la cache e' valida (sotto TTL), 100 thread leggono la stessa cache
    senza nessun fetch HTTP."""
    svc = _MockService(fetch_delay=0.1)
    # Pre-popola cache valida
    svc.get_kpi_snapshot()
    initial_fetch_count = svc.fetch_count

    barrier = threading.Barrier(100)
    results = []

    def worker() -> None:
        barrier.wait()
        results.append(svc.get_kpi_snapshot())

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Nessun nuovo fetch
    assert svc.fetch_count == initial_fetch_count
    assert len(results) == 100


def test_force_refresh_works_concurrently() -> None:
    """Con force=True, il primo thread fa il fetch e gli altri leggono
    il risultato fresco (non scatenano rispettivi fetch)."""
    svc = _MockService(fetch_delay=0.3)

    barrier = threading.Barrier(5)
    results = []

    def worker() -> None:
        barrier.wait()
        results.append(svc.get_kpi_snapshot(force=True))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 1 fetch sufficiente, gli altri 4 thread aspettano e leggono cache
    assert svc.fetch_count == 1
    assert len(results) == 5


# =========================================== delta_pct con override (bugfix)
def test_delta_pct_uses_api_price_not_override(tmp_path) -> None:
    """Con override manuale attivo, il delta_pct mostrato in UI deve
    riflettere il movimento del PREZZO API (last_close vs prev_close),
    NON la differenza artificiale (override - prev_close).

    Bugfix v7.1.1: il vecchio codice calcolava
        delta_pct = (final_value - prev_close) / prev_close
    dove final_value era l'override, producendo un delta fuorviante.
    Ora delta_pct e' sempre calcolato come (last_close - prev_close)/prev_close,
    indipendentemente dall'override applicato al value mostrato.
    """
    import pandas as pd

    from personal.data_entry.override_store import ManualOverrideStore

    # Setup override store con un override manuale attivo
    db_path = tmp_path / "test.db"
    store = ManualOverrideStore(db_path=db_path)
    # API ritornerebbe 100, ma utente ha forzato 999
    store.set("price", "VIX", user_value=999.0, api_value=100.0)

    svc = LiveMarketService(override_store=store)

    # Mock del DataFrame yf con close=100 (API), prev_close=95
    fake_data = pd.DataFrame(
        {"Close": [95.0, 100.0]},
        index=pd.date_range("2025-01-01", periods=2),
    )

    kpi = svc._extract_kpi(
        data=fake_data,
        term="VIX",
        yf_ticker="^VIX",
        currency="USD",
        fmt=".2f",
    )

    # Override attivo: value mostrato e' 999 (utente)
    assert kpi.value == 999.0
    assert kpi.is_override is True
    # MA il delta_pct deve essere quello del PREZZO API: (100-95)/95 = 0.0526
    expected_delta = (100.0 - 95.0) / 95.0
    assert kpi.delta_pct is not None
    assert abs(kpi.delta_pct - expected_delta) < 1e-6
    # Verifica che NON sia il delta artificiale (999-95)/95 = 9.52
    artificial_delta = (999.0 - 95.0) / 95.0
    assert abs(kpi.delta_pct - artificial_delta) > 1.0  # molto distante


def test_delta_pct_without_override(tmp_path) -> None:
    """Senza override, delta_pct e' lo stesso del prezzo API (sanity check)."""
    import pandas as pd

    from personal.data_entry.override_store import ManualOverrideStore

    store = ManualOverrideStore(db_path=tmp_path / "test.db")
    svc = LiveMarketService(override_store=store)

    fake_data = pd.DataFrame(
        {"Close": [95.0, 100.0]},
        index=pd.date_range("2025-01-01", periods=2),
    )
    kpi = svc._extract_kpi(
        data=fake_data,
        term="VIX",
        yf_ticker="^VIX",
        currency="USD",
        fmt=".2f",
    )

    assert kpi.value == 100.0
    assert kpi.is_override is False
    expected_delta = (100.0 - 95.0) / 95.0
    assert kpi.delta_pct is not None
    assert abs(kpi.delta_pct - expected_delta) < 1e-6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
