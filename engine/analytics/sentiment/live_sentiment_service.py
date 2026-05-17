"""LiveSentimentService — fetch sentiment scores from free public APIs (sync).

Sources (all free, no paid subscription required):
  · CNN Fear & Greed  — production.dataviz.cnn.io  (no key)
  · Crypto Fear & Greed — api.alternative.me/fng/   (no key)
  · CBOE Put/Call Ratio — cdn.cboe.com               (no key)
  · Finnhub news-sentiment — finnhub.io              (FINNHUB_API_KEY in .env)

All scores are normalized to [-1, +1]:
  -1 = extreme fear / bearish
  +1 = extreme greed / bullish

Returns None for sources that are unavailable (missing key, network error, etc.).
"""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.request
from typing import Any

from shared.logger import get_logger

__version__ = "1.0.0"

__all__ = ["LiveSentimentService", "SentimentScores"]

log = get_logger(__name__)

_TIMEOUT_S = 8.0
_CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_CRYPTO_FG_URL = "https://api.alternative.me/fng/?limit=1"
_CBOE_PC_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/CBOE_Total_PC.csv"
_FINNHUB_BASE = "https://finnhub.io/api/v1"

# Put/Call ratio normalization bounds (based on historical CBOE data)
_PC_BULLISH_THRESH = 0.70   # below → bullish (+1)
_PC_BEARISH_THRESH = 1.25   # above → bearish (-1)


class SentimentScores:
    """Container for per-source sentiment scores with availability metadata."""

    __slots__ = (
        "cnn_fg",
        "crypto_fg",
        "put_call",
        "finnhub",
        "aaii",
        "cot",
        "insider",
        "short_int",
        "errors",
    )

    def __init__(self) -> None:
        self.cnn_fg: float | None = None
        self.crypto_fg: float | None = None
        self.put_call: float | None = None
        self.finnhub: float | None = None
        # These sources have no free public API — always None unless added later
        self.aaii: float | None = None
        self.cot: float | None = None
        self.insider: float | None = None
        self.short_int: float | None = None
        self.errors: dict[str, str] = {}

    def to_display_dict(self, fallbacks: dict[str, float] | None = None) -> dict[str, float]:
        """Return dict[label → score] for rendering, using fallbacks where None."""
        fb = fallbacks or {}
        mapping = {
            "CNN F&G":    self.cnn_fg,
            "Crypto F&G": self.crypto_fg,
            "Put/Call":   self.put_call,
            "Finnhub":    self.finnhub,
            "AAII":       self.aaii,
            "COT":        self.cot,
            "Insider":    self.insider,
            "Short Int":  self.short_int,
        }
        return {
            label: (score if score is not None else fb.get(label, 0.0))
            for label, score in mapping.items()
        }

    @property
    def live_sources(self) -> list[str]:
        """Labels of sources that have real data (not None)."""
        mapping = {
            "CNN F&G":    self.cnn_fg,
            "Crypto F&G": self.crypto_fg,
            "Put/Call":   self.put_call,
            "Finnhub":    self.finnhub,
            "AAII":       self.aaii,
            "COT":        self.cot,
            "Insider":    self.insider,
            "Short Int":  self.short_int,
        }
        return [label for label, v in mapping.items() if v is not None]

    @property
    def demo_sources(self) -> list[str]:
        """Labels of sources falling back to demo values."""
        all_labels = ["CNN F&G", "Crypto F&G", "Put/Call", "Finnhub",
                      "AAII", "COT", "Insider", "Short Int"]
        live = set(self.live_sources)
        return [l for l in all_labels if l not in live]


class LiveSentimentService:
    """Sync sentiment fetcher for Streamlit pages.

    All network calls use urllib (stdlib, no extra deps). Designed to be
    wrapped with ``@st.cache_data(ttl=900)`` in the UI layer.
    """

    def __init__(self, finnhub_api_key: str | None = None) -> None:
        self._finnhub_key: str = (
            finnhub_api_key
            or os.getenv("FINNHUB_API_KEY", "").strip()
        )

    def fetch_all(self) -> SentimentScores:
        """Fetch all available sources. Errors are logged and ignored."""
        scores = SentimentScores()

        scores.cnn_fg = self._fetch_cnn_fg(scores)
        scores.crypto_fg = self._fetch_crypto_fg(scores)
        scores.put_call = self._fetch_cboe_put_call(scores)

        if self._finnhub_key:
            scores.finnhub = self._fetch_finnhub(scores)
        else:
            scores.errors["Finnhub"] = "FINNHUB_API_KEY non configurata in .env"

        return scores

    # ── Private fetchers ───────────────────────────────────────────────────

    def _fetch_cnn_fg(self, scores: SentimentScores) -> float | None:
        """CNN Fear & Greed index — score 0..100 → normalized [-1,+1]."""
        try:
            data = self._get_json(_CNN_FG_URL, headers={
                "User-Agent": "Mozilla/5.0 (compatible; MarketAI/1.0)",
                "Accept": "application/json",
            })
            score_raw = data.get("fear_and_greed", {}).get("score")
            if score_raw is None:
                # Try alternative path
                score_raw = data.get("score")
            if score_raw is None:
                raise ValueError("score field missing from CNN F&G response")
            return self._normalize_0_100(float(score_raw))
        except Exception as exc:
            log.warning("live_sentiment.cnn_fg_error", error=str(exc))
            scores.errors["CNN F&G"] = str(exc)
            return None

    def _fetch_crypto_fg(self, scores: SentimentScores) -> float | None:
        """Crypto Fear & Greed — value 0..100 → normalized [-1,+1]."""
        try:
            data = self._get_json(_CRYPTO_FG_URL)
            items = data.get("data", [])
            if not items:
                raise ValueError("empty data array from alternative.me")
            value_raw = items[0].get("value")
            if value_raw is None:
                raise ValueError("value field missing")
            return self._normalize_0_100(float(value_raw))
        except Exception as exc:
            log.warning("live_sentiment.crypto_fg_error", error=str(exc))
            scores.errors["Crypto F&G"] = str(exc)
            return None

    def _fetch_cboe_put_call(self, scores: SentimentScores) -> float | None:
        """CBOE Total Put/Call ratio from daily CSV — ratio → normalized [-1,+1].

        Low ratio (< 0.70) = lots of calls = bullish → +1
        High ratio (> 1.25) = lots of puts = bearish → -1
        """
        try:
            body = self._get_bytes(_CBOE_PC_URL)
            text = body.decode("utf-8", errors="replace")
            reader = csv.reader(io.StringIO(text))
            last_ratio: float | None = None
            for row in reader:
                if len(row) >= 2:
                    try:
                        last_ratio = float(row[1].strip())
                    except (ValueError, IndexError):
                        pass
            if last_ratio is None:
                raise ValueError("no valid put/call ratio found in CSV")
            return self._normalize_put_call(last_ratio)
        except Exception as exc:
            log.warning("live_sentiment.cboe_pc_error", error=str(exc))
            scores.errors["Put/Call"] = str(exc)
            return None

    def _fetch_finnhub(self, scores: SentimentScores) -> float | None:
        """Finnhub news-sentiment for SPY — bullish% - bearish% → [-1,+1]."""
        try:
            url = f"{_FINNHUB_BASE}/news-sentiment?symbol=SPY&token={self._finnhub_key}"
            data = self._get_json(url)
            sent = data.get("sentiment", {})
            bullish = float(sent.get("bullishPercent", 0.0))
            bearish = float(sent.get("bearishPercent", 0.0))
            if bullish == 0.0 and bearish == 0.0:
                raise ValueError("Finnhub returned zero sentiment for SPY")
            return float(bullish - bearish)
        except Exception as exc:
            log.warning("live_sentiment.finnhub_error", error=str(exc))
            scores.errors["Finnhub"] = str(exc)
            return None

    # ── HTTP helpers ───────────────────────────────────────────────────────

    def _get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            raw = resp.read()
        return dict(json.loads(raw))

    def _get_bytes(
        self, url: str, headers: dict[str, str] | None = None
    ) -> bytes:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return bytes(resp.read())

    # ── Normalization helpers ──────────────────────────────────────────────

    @staticmethod
    def _normalize_0_100(value: float) -> float:
        """Map [0, 100] → [-1, +1]."""
        return float(max(-1.0, min(1.0, (value / 100.0) * 2.0 - 1.0)))

    @staticmethod
    def _normalize_put_call(ratio: float) -> float:
        """Map put/call ratio to [-1, +1] with inversion (low ratio = bullish)."""
        if ratio <= _PC_BULLISH_THRESH:
            return 1.0
        if ratio >= _PC_BEARISH_THRESH:
            return -1.0
        # Linear interpolation in [bullish, bearish] range → [+1, -1]
        span = _PC_BEARISH_THRESH - _PC_BULLISH_THRESH
        pos = (ratio - _PC_BULLISH_THRESH) / span  # 0..1
        return float(1.0 - 2.0 * pos)


_DEMO_SCORES: dict[str, float] = {
    "CNN F&G":    0.45,
    "AAII":       0.25,
    "Crypto F&G": -0.15,
    "Put/Call":   0.10,
    "COT":        0.30,
    "Insider":    -0.05,
    "Short Int":  0.15,
    "Finnhub":    0.40,
}

_service_singleton: LiveSentimentService | None = None


def get_live_sentiment_service() -> LiveSentimentService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = LiveSentimentService()
    return _service_singleton
