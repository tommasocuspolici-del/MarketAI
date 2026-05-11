"""Test del GlossaryService."""
from __future__ import annotations

import pytest

from shared.glossary import get_glossary
from shared.glossary.lookup import GlossaryEntry, GlossaryService


def test_glossary_loads_terms() -> None:
    """Il glossario deve caricare almeno 50 termini base."""
    g = get_glossary()
    assert len(g.all_terms()) >= 50


def test_glossary_get_known_term() -> None:
    """Termini noti come VIX devono essere recuperabili."""
    g = get_glossary()
    entry = g.get("VIX")
    assert entry is not None
    assert "Volatility" in entry.full_name
    assert entry.category == "index"


def test_glossary_get_or_stub_returns_stub() -> None:
    """Termini sconosciuti ritornano stub, non None."""
    g = get_glossary()
    entry = g.get_or_stub("INESISTENTE_XYZ_999")
    assert isinstance(entry, GlossaryEntry)
    assert entry.term == "INESISTENTE_XYZ_999"
    assert entry.full_name == "INESISTENTE_XYZ_999"


def test_glossary_synonyms_resolved() -> None:
    """Sinonimi/varianti devono entrambi essere recuperabili."""
    g = get_glossary()
    spx = g.get("SPX")
    sp_full = g.get("S&P 500")
    # Entrambi devono essere accessibili (stessa entry o entrate separate)
    assert spx is not None
    assert sp_full is not None
    # Entrambi devono riferirsi all'S&P 500
    assert "S&P 500" in spx.full_name or spx.term == "SPX"
    assert "S&P 500" in sp_full.full_name or sp_full.term == "SPX"


def test_max_dd_synonyms_resolved() -> None:
    """'Max DD' e 'MaxDD' devono mappare allo stesso concetto."""
    g = get_glossary()
    a = g.get("Max DD")
    b = g.get("MaxDD")
    assert a is not None
    assert b is not None
    # Almeno uno e' Maximum Drawdown
    assert "Drawdown" in a.full_name or "Drawdown" in b.full_name


def test_glossary_case_insensitive() -> None:
    """Lookup deve essere case-insensitive."""
    g = get_glossary()
    a = g.get("vix")
    b = g.get("VIX")
    c = g.get("Vix")
    assert a is not None
    assert b is not None
    assert c is not None
    assert a.term == b.term == c.term


def test_tooltip_text_levels() -> None:
    """tooltip_text deve produrre output diverso per livelli diversi."""
    g = get_glossary()
    entry = g.get("Sharpe")
    assert entry is not None
    beginner = entry.tooltip_text(level="beginner")
    intermediate = entry.tooltip_text(level="intermediate")
    expert = entry.tooltip_text(level="expert")
    # Beginner = solo descrizione
    assert "Interpretazione" not in beginner
    # Intermediate include interpretazione
    assert "Interpretazione" in intermediate
    # Expert include formula
    assert "Formula" in expert


def test_short_label() -> None:
    """short_label produce 'TERM · Full Name'."""
    g = get_glossary()
    entry = g.get("VIX")
    assert entry is not None
    label = entry.short_label()
    assert "VIX" in label
    assert " · " in label


def test_has_method() -> None:
    """has() ritorna boolean coerente con get()."""
    g = get_glossary()
    assert g.has("VIX") is True
    assert g.has("NONESISTE_999") is False


def test_glossary_singleton_consistency() -> None:
    """get_glossary() ritorna la stessa istanza."""
    a = get_glossary()
    b = get_glossary()
    assert a is b


def test_glossary_handles_missing_yaml(tmp_path) -> None:
    """Se il file YAML non esiste, il servizio resta vuoto ma non crasha."""
    fake_path = tmp_path / "nonexistent.yaml"
    svc = GlossaryService(path=fake_path)
    assert svc.all_terms() == []
    # get_or_stub deve comunque funzionare
    stub = svc.get_or_stub("X")
    assert stub.term == "X"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
