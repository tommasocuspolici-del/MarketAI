"""LiveSentimentService — fetch sentiment scores from free public APIs (sync).

Sources (all free, no paid subscription required):
  · CNN Fear & Greed   — production.dataviz.cnn.io  (no key; requests+browser headers)
  · Crypto Fear & Greed — api.alternative.me/fng/   (no key)
  · SPY Put/Call Ratio  — yfinance options chain     (no key)
  · Finnhub news-sentiment — finnhub.io              (FINNHUB_API_KEY in .env)
      fallback: SPY RSI(14) via yfinance when Finnhub is unavailable
  · AAII Investor Survey — aaii.com (HTML scrape; no key)
  · COT E-mini S&P 500  — CFTC Socrata JSON API (no key)
  · Insider Activity     — openinsider.com (HTML scrape; no key)
  · Short Interest       — yfinance SPY shortPercentOfFloat (no key)

All scores are normalized to [-1, +1]:
  -1 = extreme fear / bearish
  +1 = extreme greed / bullish

Returns None for sources that are unavailable (missing key, network error, etc.).
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from shared.logger import get_logger

__version__ = "1.2.0"

__all__ = ["LiveSentimentService", "SentimentScores"]

log = get_logger(__name__)

_TIMEOUT_S = 8.0
_CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_CRYPTO_FG_URL = "https://api.alternative.me/fng/?limit=1"
_FINNHUB_BASE = "https://finnhub.io/api/v1"

# Put/Call ratio normalization bounds (based on historical CBOE data)
_PC_BULLISH_THRESH = 0.70   # below → bullish (+1)
_PC_BEARISH_THRESH = 1.25   # above → bearish (-1)

# AAII — HTML results page
_AAII_URL = "https://www.aaii.com/sentimentsurvey/sent_results"

# COT — CFTC Socrata public API (Legacy Futures Only, Financial Futures dataset)
_CFTC_SOCRATA_URL = "https://publicreporting.cftc.gov/resource/r4w3-av2u.json"
_SP500_FUTURES_SUBSTR = "E-MINI S&P 500"   # substring match against market name

# COT normalization: ±25% of open interest maps to ±1
_COT_OI_SPREAD = 0.25

# Insider — OpenInsider screener: last 30 days, open-market purchases + sales, value ≥ $5k
_OPENINSIDER_URL = (
    "https://openinsider.com/screener"
    "?fd=30&xp=1&xs=1&vl=5&cnt=500&action=1"
)

# Short interest normalization (SPY shortPercentOfFloat)
# Typical SPY range: 0.5–3 %; 1 % = neutral, drift down = bullish, up = bearish
_SHORT_INT_NEUTRAL = 0.01   # 1 % = score 0
_SHORT_INT_SPREAD  = 0.03   # 3 pp from neutral = ±1

# Browser-like headers used for sites that block bare Python UA
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


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

    Designed to be wrapped with ``@st.cache_data(ttl=900)`` in the UI layer.
    """

    def __init__(self, finnhub_api_key: str | None = None) -> None:
        self._finnhub_key: str = (
            finnhub_api_key
            or os.getenv("FINNHUB_API_KEY", "").strip()
        )

    def fetch_all(self) -> SentimentScores:
        """Fetch all available sources. Errors are logged and ignored."""
        scores = SentimentScores()

        scores.cnn_fg    = self._fetch_cnn_fg(scores)
        scores.crypto_fg = self._fetch_crypto_fg(scores)
        scores.put_call  = self._fetch_cboe_put_call(scores)
        scores.finnhub   = self._fetch_finnhub(scores)
        scores.aaii      = self._fetch_aaii(scores)
        scores.cot       = self._fetch_cot(scores)
        scores.insider   = self._fetch_insider(scores)
        scores.short_int = self._fetch_short_int(scores)

        return scores

    # ── Private fetchers ───────────────────────────────────────────────────

    def _fetch_cnn_fg(self, scores: SentimentScores) -> float | None:
        """CNN Fear & Greed index — score 0..100 → normalized [-1,+1].

        Uses requests.Session with full browser headers to bypass anti-bot (418).
        """
        try:
            import requests  # available via requests-cache dependency

            session = requests.Session()
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://www.cnn.com/markets/fear-and-greed",
                "Origin": "https://www.cnn.com",
            })
            resp = session.get(_CNN_FG_URL, timeout=_TIMEOUT_S)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

            score_raw = data.get("fear_and_greed", {}).get("score")
            if score_raw is None:
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
        """SPY options put/call volume ratio via yfinance — ratio → normalized [-1,+1].

        Low ratio (< 0.70) = lots of calls = bullish → +1
        High ratio (> 1.25) = lots of puts = bearish → -1
        """
        try:
            import yfinance as yf  # already a project dependency

            spy = yf.Ticker("SPY")
            exp_dates = spy.options
            if not exp_dates:
                raise ValueError("no options expiry dates available for SPY")
            chain = spy.option_chain(exp_dates[0])
            put_vol = float(chain.puts["volume"].fillna(0).sum())
            call_vol = float(chain.calls["volume"].fillna(0).sum())
            if call_vol == 0:
                raise ValueError("zero call volume in SPY options chain")
            ratio = put_vol / call_vol
            return self._normalize_put_call(ratio)
        except Exception as exc:
            log.warning("live_sentiment.put_call_error", error=str(exc))
            scores.errors["Put/Call"] = str(exc)
            return None

    def _fetch_finnhub(self, scores: SentimentScores) -> float | None:
        """Finnhub news-sentiment for SPY, with SPY RSI(14) fallback via yfinance.

        Finnhub free tier may return 403 on news-sentiment; in that case the RSI
        proxy is used so the source remains live (real data, different origin).
        """
        finnhub_exc: Exception | None = None
        if self._finnhub_key:
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
                finnhub_exc = exc
                log.warning("live_sentiment.finnhub_error", error=str(exc))

        # Fallback: SPY RSI(14) as technical sentiment proxy
        result = self._fetch_spy_rsi_fallback(scores, finnhub_exc)
        return result

    def _fetch_spy_rsi_fallback(
        self, scores: SentimentScores, primary_exc: Exception | None
    ) -> float | None:
        """RSI(14) of SPY as technical sentiment proxy when Finnhub is unavailable."""
        try:
            import yfinance as yf

            hist = yf.Ticker("SPY").history(period="3mo")["Close"]
            if len(hist) < 15:
                raise ValueError("insufficient SPY history for RSI(14)")
            delta = hist.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            last_loss = loss.iloc[-1]
            if last_loss == 0:
                raise ValueError("RSI denominator is zero (all gains, no losses)")
            rs = gain.iloc[-1] / last_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return self._normalize_0_100(float(rsi))
        except Exception as exc:
            log.warning("live_sentiment.spy_rsi_error", error=str(exc))
            # Report the original Finnhub error if present, else the RSI error
            scores.errors["Finnhub"] = str(primary_exc) if primary_exc else str(exc)
            return None

    def _fetch_aaii(self, scores: SentimentScores) -> float | None:
        """AAII Investor Survey — scrape HTML, extract bullish/bearish %, normalize to [-1,+1]."""
        try:
            from bs4 import BeautifulSoup

            req = urllib.request.Request(_AAII_URL, headers=_BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table", {"id": "sentiment-data"}) or soup.find("table")
            if table is None:
                raise ValueError("AAII sentiment table not found")
            rows = table.find_all("tr")
            last_row = rows[-1].find_all("td")
            # Columns: Date, Bullish, Neutral, Bearish, ...
            bullish = float(last_row[1].text.strip().replace("%", ""))
            bearish = float(last_row[3].text.strip().replace("%", ""))
            total = bullish + bearish
            if total == 0:
                raise ValueError("AAII zero total sentiment")
            score = (bullish - bearish) / total
            return float(max(-1.0, min(1.0, score)))
        except Exception as exc:
            log.warning("live_sentiment.aaii_error", error=str(exc))
            scores.errors["AAII"] = str(exc)
            return None

    def _fetch_cot(self, scores: SentimentScores) -> float | None:
        """COT E-mini S&P 500 — CFTC Socrata API, non-commercial net position / open interest."""
        try:
            url = f"{_CFTC_SOCRATA_URL}?$limit=5&$order=report_date_as_yyyy_mm_dd DESC"
            data = self._get_json(url)
            record = next(
                (r for r in data if _SP500_FUTURES_SUBSTR in r.get("market_and_exchange_names", "").upper()),
                None,
            )
            if record is None:
                raise ValueError("E-mini S&P 500 not found in CFTC response")
            long_nc = float(record.get("noncomm_positions_long_all", 0))
            short_nc = float(record.get("noncomm_positions_short_all", 0))
            oi = float(record.get("open_interest_all", 1))
            if oi == 0:
                raise ValueError("COT open interest is zero")
            net_pct = (long_nc - short_nc) / oi
            score = net_pct / _COT_OI_SPREAD  # ±25% OI → ±1
            return float(max(-1.0, min(1.0, score)))
        except Exception as exc:
            log.warning("live_sentiment.cot_error", error=str(exc))
            scores.errors["COT"] = str(exc)
            return None

    def _fetch_insider(self, scores: SentimentScores) -> float | None:
        """Insider Activity — OpenInsider screener, open-market buy vs sell count."""
        try:
            from bs4 import BeautifulSoup

            req = urllib.request.Request(_OPENINSIDER_URL, headers=_BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table", {"class": "tinytable"})
            if table is None:
                raise ValueError("OpenInsider tinytable not found")
            buys = sells = 0
            for row in table.find_all("tr")[1:]:  # skip header
                cells = row.find_all("td")
                if len(cells) < 5:
                    continue
                trade_type = cells[4].text.strip().upper()
                if trade_type == "P":
                    buys += 1
                elif trade_type == "S":
                    sells += 1
            total = buys + sells
            if total == 0:
                raise ValueError("OpenInsider: no trades found")
            score = (buys - sells) / total
            return float(max(-1.0, min(1.0, score)))
        except Exception as exc:
            log.warning("live_sentiment.insider_error", error=str(exc))
            scores.errors["Insider"] = str(exc)
            return None

    def _fetch_short_int(self, scores: SentimentScores) -> float | None:
        """Short Interest — SPY shortPercentOfFloat via yfinance, normalized to [-1,+1]."""
        try:
            import yfinance as yf

            info = yf.Ticker("SPY").info
            pct = info.get("shortPercentOfFloat")
            if pct is None:
                raise ValueError("shortPercentOfFloat not available for SPY")
            # Invert: high short interest → bearish (-1); low → bullish (+1)
            score = -(pct - _SHORT_INT_NEUTRAL) / _SHORT_INT_SPREAD
            return float(max(-1.0, min(1.0, score)))
        except Exception as exc:
            log.warning("live_sentiment.short_int_error", error=str(exc))
            scores.errors["Short Int"] = str(exc)
            return None

    # ── HTTP helpers ───────────────────────────────────────────────────────

    def _get_json(
        self, url: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            raw = resp.read()
        return dict(json.loads(raw))

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
