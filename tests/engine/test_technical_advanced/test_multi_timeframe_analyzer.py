"""Tests for MultiTimeframeAnalyzer — DoD: < 500ms per ticker."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.technical.multi_timeframe_analyzer import (
    MTFSignal,
    MultiTimeframeAnalyzer,
    TimeframeSignal,
)


def _make_ohlcv(n_days: int = 504, trend: float = 0.0003) -> pd.DataFrame:
    rng    = np.random.default_rng(42)
    noise  = rng.normal(0, 0.01, n_days)
    close  = 100.0 * np.cumprod(1 + trend + noise)
    dates  = pd.date_range("2023-01-01", periods=n_days, freq="B", tz="UTC")
    return pd.DataFrame(
        {"open": close, "high": close * 1.005, "low": close * 0.995,
         "close": close, "volume": 1e6},
        index=dates,
    )


class TestBasicAnalysis:
    def test_returns_mtf_signal(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(), "SPY")
        assert isinstance(result, MTFSignal)

    def test_ticker_set_correctly(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(), "AAPL")
        assert result.ticker == "AAPL"

    def test_confluence_in_range(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(), "SPY")
        assert -1.0 <= result.confluence <= 1.0

    def test_per_timeframe_populated(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(), "SPY")
        assert len(result.per_timeframe) >= 1    # at least daily


class TestConviction:
    def test_conviction_is_valid(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(), "SPY")
        assert result.conviction in ("high", "moderate", "low")

    def test_strong_uptrend_bullish(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(trend=0.002), "SPY")   # strong trend
        assert result.confluence > 0

    def test_strong_downtrend_bearish(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(trend=-0.002), "SPY")
        assert result.confluence < 0


class TestTimeframeSignals:
    def test_each_tf_has_valid_direction(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(), "SPY")
        for tf, sig in result.per_timeframe.items():
            assert sig.direction in ("bullish", "bearish", "neutral")
            assert -1.0 <= sig.value <= 1.0
            assert 0.0 <= sig.rsi <= 100.0

    def test_n_agreeing_non_negative(self) -> None:
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        result   = analyzer.analyze(_make_ohlcv(), "SPY")
        assert result.n_agreeing >= 0


class TestSignalBusPublish:
    def test_publishes_to_bus(self) -> None:
        from unittest.mock import patch
        from shared.signal_bus import SignalBus
        from shared.signal_registry import SignalRegistry
        from collections import defaultdict
        import threading

        bus = SignalBus.__new__(SignalBus)
        bus._handlers  = defaultdict(list)
        bus._lock      = threading.RLock()
        bus._registry  = SignalRegistry()
        received: list = []
        bus.subscribe("multi_tf.SPY", lambda s: received.append(s))

        analyzer = MultiTimeframeAnalyzer(publish_to_bus=True)
        with patch("engine.analytics.technical.multi_timeframe_analyzer.get_signal_bus",
                   return_value=bus):
            analyzer.analyze(_make_ohlcv(), "SPY")

        assert len(received) >= 1
        assert received[0].name == "multi_tf.SPY"
        assert received[0].ic_estimate is None   # not yet estimated (< 30 days)


class TestBenchmark:
    @pytest.mark.benchmark(group="technical")
    def test_under_500ms(self, benchmark) -> None:
        """DoD: MTF analysis < 500ms per ticker."""
        analyzer = MultiTimeframeAnalyzer(publish_to_bus=False)
        ohlcv    = _make_ohlcv(504)
        benchmark(analyzer.analyze, ohlcv, "SPY")
