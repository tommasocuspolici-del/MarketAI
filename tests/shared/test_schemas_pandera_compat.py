"""Test compatibility import pandera (v7.1.4 fix B7).

Verifica che ``shared/db/schemas.py`` carichi correttamente sia con
pandera 0.18/0.19 (path ``import pandera as pa``) sia con pandera 0.20+
(path ``import pandera.pandas as pa``).
"""
from __future__ import annotations

import pandera
import pytest


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


# ─── v12.0 schemas ────────────────────────────────────────────────────────────

class TestV12Schemas:
    """7 positive + 7 negative tests for the v12.0 Pandera schemas."""

    def test_signal_scorecard_valid(self) -> None:
        import pandas as pd
        from shared.db.schemas import validate_signal_scorecard
        df = pd.DataFrame([{
            "signal_id": "vix_signal",
            "snapshot_date": pd.Timestamp("2024-01-01"),
            "horizon_days": 21,
            "hit_rate": 0.62,
            "is_significant": True,
        }])
        validate_signal_scorecard(df)

    def test_signal_scorecard_missing_column_raises(self) -> None:
        import pandas as pd
        from shared.exceptions import DataValidationError
        from shared.db.schemas import validate_signal_scorecard
        df = pd.DataFrame([{"signal_id": "vix", "snapshot_date": pd.Timestamp("2024-01-01")}])
        with pytest.raises(DataValidationError):
            validate_signal_scorecard(df)

    def test_model_registry_valid(self) -> None:
        import pandas as pd
        from shared.db.schemas import validate_model_registry
        df = pd.DataFrame([{
            "model_id": "m1",
            "model_type": "ridge",
            "horizon_days": 63,
            "directional_acc": 0.65,
        }])
        validate_model_registry(df)

    def test_model_registry_missing_column_raises(self) -> None:
        import pandas as pd
        from shared.exceptions import DataValidationError
        from shared.db.schemas import validate_model_registry
        df = pd.DataFrame([{"model_id": "m1"}])
        with pytest.raises(DataValidationError):
            validate_model_registry(df)

    def test_wfo_results_valid(self) -> None:
        import pandas as pd
        from shared.db.schemas import validate_wfo_results
        df = pd.DataFrame([{"model_id": "m1", "fold_n": 0, "sharpe_fold": 1.2, "directional_acc": 0.6}])
        validate_wfo_results(df)

    def test_wfo_results_missing_column_raises(self) -> None:
        import pandas as pd
        from shared.exceptions import DataValidationError
        from shared.db.schemas import validate_wfo_results
        df = pd.DataFrame([{"model_id": "m1"}])
        with pytest.raises(DataValidationError):
            validate_wfo_results(df)

    def test_macro_regime_timeline_valid(self) -> None:
        import pandas as pd
        from shared.db.schemas import validate_macro_regime_timeline
        df = pd.DataFrame([{
            "regime_label": "expansion",
            "prob_expansion": 0.7,
            "prob_slowdown": 0.15,
            "prob_contraction": 0.1,
            "prob_recovery": 0.05,
        }])
        validate_macro_regime_timeline(df)

    def test_macro_regime_timeline_bad_label_raises(self) -> None:
        import pandas as pd
        from shared.exceptions import DataValidationError
        from shared.db.schemas import validate_macro_regime_timeline
        df = pd.DataFrame([{"regime_label": "unknown_regime"}])
        with pytest.raises(DataValidationError):
            validate_macro_regime_timeline(df)

    def test_portfolio_risk_metrics_valid(self) -> None:
        import pandas as pd
        from shared.db.schemas import validate_portfolio_risk_metrics
        df = pd.DataFrame([{"var_95": -0.05, "max_drawdown_1y": -0.12}])
        validate_portfolio_risk_metrics(df)

    def test_portfolio_risk_metrics_positive_var_raises(self) -> None:
        import pandas as pd
        from shared.exceptions import DataValidationError
        from shared.db.schemas import validate_portfolio_risk_metrics
        df = pd.DataFrame([{"var_95": 0.05, "max_drawdown_1y": -0.12}])
        with pytest.raises(DataValidationError):
            validate_portfolio_risk_metrics(df)

    def test_position_risk_contribution_valid(self) -> None:
        import pandas as pd
        from shared.db.schemas import validate_position_risk_contribution
        df = pd.DataFrame([{"ticker": "AAPL", "pct_risk": 0.15}])
        validate_position_risk_contribution(df)

    def test_position_risk_contribution_missing_column_raises(self) -> None:
        import pandas as pd
        from shared.exceptions import DataValidationError
        from shared.db.schemas import validate_position_risk_contribution
        df = pd.DataFrame([{"pct_risk": 0.15}])
        with pytest.raises(DataValidationError):
            validate_position_risk_contribution(df)

    def test_vol_surface_snapshots_valid(self) -> None:
        import pandas as pd
        from shared.db.schemas import validate_vol_surface_snapshots
        df = pd.DataFrame([{
            "snapshot_at": pd.Timestamp("2024-01-01", tz="UTC"),
            "vix_spot": 18.5,
        }])
        validate_vol_surface_snapshots(df)

    def test_vol_surface_snapshots_missing_column_raises(self) -> None:
        import pandas as pd
        from shared.exceptions import DataValidationError
        from shared.db.schemas import validate_vol_surface_snapshots
        df = pd.DataFrame([{"vix_spot": 18.5}])
        with pytest.raises(DataValidationError):
            validate_vol_surface_snapshots(df)
