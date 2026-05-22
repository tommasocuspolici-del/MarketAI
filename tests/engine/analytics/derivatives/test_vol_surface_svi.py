from __future__ import annotations

import math
import pytest
import numpy as np

from engine.analytics.derivatives.vol_surface_svi import (
    SVIModel,
    SVIParameters,
    SVISurface,
    FALLBACK_RMSE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_svi_params(
    a: float = 0.04,
    b: float = 0.1,
    rho: float = -0.3,
    m: float = 0.0,
    sigma: float = 0.1,
    expiry_days: int = 30,
) -> SVIParameters:
    return SVIParameters(a=a, b=b, rho=rho, m=m, sigma=sigma, expiry_days=expiry_days, fit_rmse=0.0)


@pytest.fixture()
def model() -> SVIModel:
    return SVIModel()


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_instantiates(self) -> None:
        m = SVIModel()
        assert isinstance(m, SVIModel)


# ---------------------------------------------------------------------------
# w_svi
# ---------------------------------------------------------------------------

class TestWSVI:
    def test_returns_array(self, model: SVIModel) -> None:
        params = _make_svi_params()
        k = np.array([-0.2, 0.0, 0.2])
        w = model.w_svi(params, k)
        assert isinstance(w, np.ndarray)
        assert len(w) == 3

    def test_atm_variance_known_params(self, model: SVIModel) -> None:
        """For a=0.04, b=0.1, rho=-0.3, m=0.0, sigma=0.1, k=0:
        w(0) = 0.04 + 0.1 * (-0.3 * 0 + sqrt(0 + 0.01)) = 0.04 + 0.1 * 0.1 = 0.05
        """
        params = _make_svi_params(a=0.04, b=0.1, rho=-0.3, m=0.0, sigma=0.1)
        w = model.w_svi(params, np.array([0.0]))
        expected = 0.04 + 0.1 * (0.0 + math.sqrt(0.01))
        assert math.isclose(float(w[0]), expected, rel_tol=1e-9)

    def test_w_at_atm_ge_a(self, model: SVIModel) -> None:
        """For b > 0 and sigma > 0: w(m) = a + b*sigma >= a."""
        params = _make_svi_params(a=0.04, b=0.1, rho=-0.3, m=0.0, sigma=0.1)
        w = model.w_svi(params, np.array([0.0]))
        assert float(w[0]) >= 0.04

    def test_scalar_k_works(self, model: SVIModel) -> None:
        params = _make_svi_params()
        w = model.w_svi(params, np.array([0.0]))
        assert w.shape == (1,)

    def test_symmetry_around_m(self, model: SVIModel) -> None:
        """With rho=0: w(m+x) == w(m-x)."""
        params = _make_svi_params(rho=0.0, m=0.0)
        k_pos = np.array([0.1, 0.2, 0.3])
        k_neg = np.array([-0.1, -0.2, -0.3])
        w_pos = model.w_svi(params, k_pos)
        w_neg = model.w_svi(params, k_neg)
        np.testing.assert_allclose(w_pos, w_neg, rtol=1e-9)


# ---------------------------------------------------------------------------
# iv_from_svi
# ---------------------------------------------------------------------------

class TestIVFromSVI:
    def test_returns_positive_ivs(self, model: SVIModel) -> None:
        params = _make_svi_params(expiry_days=30)
        k = np.array([-0.2, -0.1, 0.0, 0.1, 0.2])
        ivs = model.iv_from_svi(params, k)
        assert (ivs >= 0).all()

    def test_iv_positive_for_typical_params(self, model: SVIModel) -> None:
        params = _make_svi_params(a=0.04, b=0.1, rho=-0.3, m=0.0, sigma=0.1, expiry_days=30)
        k = np.linspace(-0.3, 0.3, 7)
        ivs = model.iv_from_svi(params, k)
        assert (ivs > 0).all()

    def test_zero_expiry_returns_zeros(self, model: SVIModel) -> None:
        params = _make_svi_params(expiry_days=0)
        k = np.array([0.0, 0.1])
        ivs = model.iv_from_svi(params, k)
        np.testing.assert_array_equal(ivs, 0.0)


# ---------------------------------------------------------------------------
# fit
# ---------------------------------------------------------------------------

class TestFit:
    def test_fit_returns_svi_parameters(self, model: SVIModel) -> None:
        pytest.importorskip("scipy")
        k = np.linspace(-0.3, 0.3, 10)
        params_true = _make_svi_params(a=0.04, b=0.1, rho=-0.2, m=0.0, sigma=0.15, expiry_days=30)
        w = model.w_svi(params_true, k)
        result = model.fit(k, w, expiry_days=30)
        assert isinstance(result, SVIParameters)

    def test_fit_all_params_finite(self, model: SVIModel) -> None:
        pytest.importorskip("scipy")
        k = np.linspace(-0.3, 0.3, 10)
        params_true = _make_svi_params(expiry_days=60)
        w = model.w_svi(params_true, k)
        result = model.fit(k, w, expiry_days=60)
        for attr in ("a", "b", "rho", "m", "sigma"):
            assert math.isfinite(getattr(result, attr)), f"{attr} is not finite"

    def test_fit_expiry_days_stored(self, model: SVIModel) -> None:
        pytest.importorskip("scipy")
        k = np.linspace(-0.2, 0.2, 8)
        params_true = _make_svi_params(expiry_days=45)
        w = model.w_svi(params_true, k)
        result = model.fit(k, w, expiry_days=45)
        assert result.expiry_days == 45

    def test_fit_rmse_finite(self, model: SVIModel) -> None:
        pytest.importorskip("scipy")
        k = np.linspace(-0.3, 0.3, 10)
        params_true = _make_svi_params(expiry_days=30)
        w = model.w_svi(params_true, k)
        result = model.fit(k, w, expiry_days=30)
        assert math.isfinite(result.fit_rmse)

    def test_fit_insufficient_points_fallback(self, model: SVIModel) -> None:
        """With < 3 points, returns fallback parameters."""
        k = np.array([0.0, 0.1])
        w = np.array([0.04, 0.05])
        result = model.fit(k, w, expiry_days=30)
        assert isinstance(result, SVIParameters)
        assert result.expiry_days == 30

    def test_fit_no_scipy_fallback(self, model: SVIModel, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without scipy, fit should return fallback params."""
        import builtins
        _real_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[override]
            if name == "scipy.optimize":
                raise ImportError("mocked")
            return _real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        k = np.linspace(-0.3, 0.3, 10)
        w = np.ones(10) * 0.04
        result = model.fit(k, w, expiry_days=30)
        assert isinstance(result, SVIParameters)
        assert result.fit_rmse == FALLBACK_RMSE
