"""Test compatibility import pandera (v7.1.4 fix B7).

Verifica che ``shared/db/schemas.py`` carichi correttamente sia con
pandera 0.18/0.19 (path ``import pandera as pa``) sia con pandera 0.20+
(path ``import pandera.pandas as pa``).
"""
from __future__ import annotations

import pandera


def test_schemas_module_imports_successfully():
    """schemas.py si importa senza ModuleNotFoundError indipendentemente
    dalla versione di pandera installata.

    Riproduce il bug B7: con pandera < 0.20 il path ``pandera.pandas``
    non esiste e schemas.py crashava all'import. Il try/except in
    schemas.py risolve il problema.
    """
    import shared.db.schemas as schemas

    # Le API che usiamo devono essere accessibili in entrambi i path
    assert hasattr(schemas, "pa")
    assert hasattr(schemas.pa, "Check")
    assert hasattr(schemas.pa, "Column")
    assert hasattr(schemas.pa, "DataFrameSchema")


def test_pandera_namespace_path_used():
    """Il modulo pa caricato da schemas.py deve essere uno dei due path
    riconosciuti: 'pandera' (vecchio) o 'pandera.pandas' (nuovo).
    """
    import shared.db.schemas as schemas

    pa_name = schemas.pa.__name__
    assert pa_name in ("pandera", "pandera.pandas"), (
        f"Inaspettato: pa.__name__ = {pa_name}"
    )


def test_ohlcv_schema_is_dataframeschema():
    """OHLCV_SCHEMA deve essere istanziato correttamente come DataFrameSchema."""
    from shared.db.schemas import OHLCV_SCHEMA, validate_ohlcv

    assert OHLCV_SCHEMA is not None
    assert callable(validate_ohlcv)
    # DataFrameSchema esiste in entrambe le versioni di pandera
    assert type(OHLCV_SCHEMA).__name__ == "DataFrameSchema"


def test_macro_series_schema_is_dataframeschema():
    """MACRO_SERIES_SCHEMA caricato e tipato correttamente."""
    from shared.db.schemas import MACRO_SERIES_SCHEMA, validate_macro_series

    assert MACRO_SERIES_SCHEMA is not None
    assert callable(validate_macro_series)
    assert type(MACRO_SERIES_SCHEMA).__name__ == "DataFrameSchema"


def test_pandera_version_is_supported():
    """La versione di pandera installata e' nel range supportato (>=0.18, <1.0)."""
    version = pandera.__version__
    major, minor = version.split(".")[:2]
    major_i, minor_i = int(major), int(minor)
    # >= 0.18 (sopra)
    assert (major_i, minor_i) >= (0, 18), (
        f"pandera {version} troppo vecchia, richiesta >= 0.18"
    )
    # < 1.0 (vincolo pyproject)
    assert major_i < 1, f"pandera {version} non testata per major versions >= 1"
