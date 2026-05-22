"""Tests per engine.data_universe.universe_loader — UniverseLoader / DataUniverse."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from engine.data_universe.universe_loader import (
    DataUniverse,
    SeriesDefinition,
    UniverseLoader,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def minimal_yaml(tmp_path: Path) -> Path:
    """YAML minimale con 3 serie in 2 categorie."""
    content = textwrap.dedent("""\
        version: "1.0"
        generated: "2026-05-22"
        fred_series:
          labour:
            existing:
              - id: ICSA
                name: "Initial Jobless Claims"
                frequency: weekly
                publication_lag_days: 4
                revision_frequency: none
                retention_years: 25
              - id: UNRATE
                name: "Unemployment Rate"
                frequency: monthly
                publication_lag_days: 7
                revision_frequency: monthly
                retention_years: 30
            new:
              - id: JTSJOL
                name: "Job Openings: Total Nonfarm (JOLTS)"
                frequency: monthly
                publication_lag_days: 35
                revision_frequency: monthly
                retention_years: 20
          inflation:
            existing:
              - id: CPIAUCSL
                name: "Consumer Price Index (CPI-U)"
                frequency: monthly
                publication_lag_days: 14
                revision_frequency: annual
                retention_years: 30
            new:
              - id: T10YIE
                name: "10-Year Breakeven Inflation Rate"
                frequency: daily
                publication_lag_days: 1
                revision_frequency: none
                retention_years: 15
    """)
    p = tmp_path / "data_universe.yaml"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def full_universe() -> DataUniverse:
    """Carica il file data_universe.yaml reale del progetto."""
    return UniverseLoader().load()


# ─── UniverseLoader tests ─────────────────────────────────────────────────────


class TestUniverseLoader:
    def test_load_minimal_yaml(self, minimal_yaml: Path) -> None:
        """Verifica che un YAML minimale venga caricato senza errori."""
        universe = UniverseLoader(config_path=minimal_yaml).load()
        assert isinstance(universe, DataUniverse)
        assert universe.count() == 5

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """FileNotFoundError se il file YAML non esiste."""
        with pytest.raises(FileNotFoundError, match="data_universe.yaml"):
            UniverseLoader(config_path=tmp_path / "nonexistent.yaml").load()

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        """ValueError se il contenuto YAML non è un mapping."""
        p = tmp_path / "bad.yaml"
        p.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="mapping YAML"):
            UniverseLoader(config_path=p).load()

    def test_skips_entry_with_missing_required_field(self, tmp_path: Path) -> None:
        """Entries con campi mancanti vengono saltate silenziosamente."""
        content = textwrap.dedent("""\
            version: "1.0"
            generated: "2026-05-22"
            fred_series:
              labour:
                existing:
                  - id: ICSA
                    name: "Initial Jobless Claims"
                    frequency: weekly
                    publication_lag_days: 4
                    revision_frequency: none
                    retention_years: 25
                  - id: BROKEN
                    name: "Missing fields"
                    # frequency mancante
        """)
        p = tmp_path / "partial.yaml"
        p.write_text(content, encoding="utf-8")
        universe = UniverseLoader(config_path=p).load()
        assert universe.count() == 1
        assert "ICSA" in universe.series
        assert "BROKEN" not in universe.series

    def test_skips_invalid_frequency(self, tmp_path: Path) -> None:
        """Entries con frequency non valida vengono saltate."""
        content = textwrap.dedent("""\
            version: "1.0"
            generated: "2026-05-22"
            fred_series:
              labour:
                existing:
                  - id: ICSA
                    name: "Initial Jobless Claims"
                    frequency: biweekly
                    publication_lag_days: 4
                    revision_frequency: none
                    retention_years: 25
        """)
        p = tmp_path / "bad_freq.yaml"
        p.write_text(content, encoding="utf-8")
        universe = UniverseLoader(config_path=p).load()
        assert universe.count() == 0

    def test_skips_duplicate_ids(self, tmp_path: Path) -> None:
        """ID duplicati vengono ignorati (solo il primo viene caricato)."""
        content = textwrap.dedent("""\
            version: "1.0"
            generated: "2026-05-22"
            fred_series:
              labour:
                existing:
                  - id: ICSA
                    name: "Initial Jobless Claims"
                    frequency: weekly
                    publication_lag_days: 4
                    revision_frequency: none
                    retention_years: 25
                new:
                  - id: ICSA
                    name: "Duplicate"
                    frequency: daily
                    publication_lag_days: 1
                    revision_frequency: none
                    retention_years: 10
        """)
        p = tmp_path / "dup.yaml"
        p.write_text(content, encoding="utf-8")
        universe = UniverseLoader(config_path=p).load()
        assert universe.count() == 1
        assert universe.get("ICSA").name == "Initial Jobless Claims"

    def test_default_source_is_fred(self, minimal_yaml: Path) -> None:
        """Le serie senza campo 'source' usano 'fred' come default."""
        universe = UniverseLoader(config_path=minimal_yaml).load()
        assert universe.get("ICSA").source == "fred"


# ─── DataUniverse tests ───────────────────────────────────────────────────────


class TestDataUniverse:
    def test_count_returns_number_of_series(self, minimal_yaml: Path) -> None:
        universe = UniverseLoader(config_path=minimal_yaml).load()
        assert universe.count() == 5

    def test_get_existing_series(self, minimal_yaml: Path) -> None:
        universe = UniverseLoader(config_path=minimal_yaml).load()
        defn = universe.get("ICSA")
        assert defn is not None
        assert isinstance(defn, SeriesDefinition)
        assert defn.id == "ICSA"
        assert defn.name == "Initial Jobless Claims"
        assert defn.frequency == "weekly"
        assert defn.publication_lag_days == 4
        assert defn.revision_frequency == "none"
        assert defn.retention_years == 25
        assert defn.category == "labour"

    def test_get_missing_series_returns_none(self, minimal_yaml: Path) -> None:
        universe = UniverseLoader(config_path=minimal_yaml).load()
        assert universe.get("NONEXISTENT_XYZ") is None

    def test_by_category_filters_correctly(self, minimal_yaml: Path) -> None:
        universe = UniverseLoader(config_path=minimal_yaml).load()
        labour = universe.by_category("labour")
        inflation = universe.by_category("inflation")
        missing = universe.by_category("nonexistent")

        assert len(labour) == 3
        assert all(s.category == "labour" for s in labour)
        assert len(inflation) == 2
        assert all(s.category == "inflation" for s in inflation)
        assert missing == []

    def test_all_ids_returns_sorted_list(self, minimal_yaml: Path) -> None:
        universe = UniverseLoader(config_path=minimal_yaml).load()
        ids = universe.all_ids()
        assert ids == sorted(ids)
        assert len(ids) == 5

    def test_categories_returns_distinct_sorted(self, minimal_yaml: Path) -> None:
        universe = UniverseLoader(config_path=minimal_yaml).load()
        cats = universe.categories()
        assert "labour" in cats
        assert "inflation" in cats
        assert cats == sorted(cats)
        assert len(cats) == len(set(cats))  # no duplicates


# ─── Integration: real data_universe.yaml ────────────────────────────────────


class TestRealDataUniverse:
    def test_count_at_least_85(self, full_universe: DataUniverse) -> None:
        """Il file reale deve contenere almeno 85 serie."""
        assert full_universe.count() >= 85

    def test_key_series_present(self, full_universe: DataUniverse) -> None:
        """Serie chiave standard devono essere presenti."""
        key_series = [
            "ICSA", "UNRATE", "PAYEMS",
            "CPIAUCSL", "PCEPI",
            "DGS10", "T10Y2Y",
            "VIXCLS", "BAMLH0A0HYM2",
            "GDP", "GDPC1",
        ]
        for sid in key_series:
            defn = full_universe.get(sid)
            assert defn is not None, f"Serie mancante nel Data Universe: {sid}"

    def test_all_series_have_valid_frequency(self, full_universe: DataUniverse) -> None:
        """Tutte le serie devono avere una frequenza valida."""
        valid = {"daily", "weekly", "monthly", "quarterly", "annual"}
        for defn in full_universe.series.values():
            assert defn.frequency in valid, (
                f"{defn.id} ha frequenza non valida: {defn.frequency}"
            )

    def test_all_series_have_positive_lag(self, full_universe: DataUniverse) -> None:
        """Il publication_lag_days deve essere >= 0."""
        for defn in full_universe.series.values():
            assert defn.publication_lag_days >= 0, (
                f"{defn.id} ha lag negativo: {defn.publication_lag_days}"
            )

    def test_all_series_have_positive_retention(self, full_universe: DataUniverse) -> None:
        """Il retention_years deve essere > 0."""
        for defn in full_universe.series.values():
            assert defn.retention_years > 0, (
                f"{defn.id} ha retention non positiva: {defn.retention_years}"
            )

    def test_categories_are_non_empty(self, full_universe: DataUniverse) -> None:
        """Devono esistere almeno 5 categorie distinte."""
        cats = full_universe.categories()
        assert len(cats) >= 5

    def test_icsa_fields(self, full_universe: DataUniverse) -> None:
        """ICSA deve avere i valori attesi dal YAML."""
        icsa = full_universe.get("ICSA")
        assert icsa is not None
        assert icsa.frequency == "weekly"
        assert icsa.publication_lag_days == 4
        assert icsa.revision_frequency == "none"
        assert icsa.category == "labour"
