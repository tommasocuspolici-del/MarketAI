"""SanityChecker: regole deterministiche di plausibilita' (Rule 46).

Applicato dopo SilentFailureDetector e DataCleaner, prima di Pandera.
Differenza dal DataCleaner:
  - DataCleaner -> rileva anomalie statistiche (outlier zscore, gap, stale).
  - SanityChecker -> rileva impossibilita' semantiche (P/E < -500, prezzo <= 0).

Le soglie sono caricate da ``config/sanity_rules.yaml`` (con default in
codice nel caso il file manchi).

Bugfix v7.1.1:
  · Le regole "macro" definite in sanity_rules.yaml (unemployment_rate,
    inflation_rate, gdp_growth) erano IGNORATE dal _load_config perche'
    iterava solo su _DEFAULT_RULES che non includeva la chiave "macro".
    Ora i default macro sono presenti e check_macro_data() applica le regole.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

__version__ = "7.1.1"

__all__ = ["SanityChecker", "SanityViolation", "Severity"]

# Default thresholds — usati se config/sanity_rules.yaml non esiste o
# manca un campo. Tutti i numeri qui sono volutamente conservativi.
# v7.1.1: aggiunta sezione "macro" (era assente, causa "ghost rules" nel YAML).
_DEFAULT_RULES: dict[str, dict[str, Any]] = {
    "price": {
        "min_value": 0.0001,
        "max_value": 5_000_000.0,
        "max_daily_change_pct": 0.50,
    },
    "volume": {"min_value": 0.0},
    "pe_ratio": {
        "min_value": -500.0,
        "max_value": 5_000.0,
        "zero_as_unavailable": True,
    },
    "market_cap": {"min_value": 0.0, "min_plausible": 100_000.0},
    "dividend": {"max_yield": 1.0, "max_yield_warn": 0.30},
    "eps": {"max_abs_value": 10_000.0},
    # ─── Macro (v7.1.1) ──────────────────────────────────────────────────
    # Strutturato come dict-di-dict: ogni indicatore macro ha le proprie
    # soglie min/max. Questo riflette esattamente la struttura YAML.
    "macro": {
        "unemployment_rate": {"min_value": 0.0, "max_value": 100.0},
        "inflation_rate": {"min_value": -10.0, "max_value": 100.0},
        "gdp_growth": {"min_value": -50.0, "max_value": 50.0},
    },
}


class Severity(str, Enum):
    """Gravita' della violazione."""

    CRITICAL = "CRITICAL"
    WARN = "WARN"


@dataclass(frozen=True, slots=True)
class SanityViolation:
    """Singola violazione delle regole di plausibilita'."""

    field: str
    value: Any
    severity: Severity
    message: str


class SanityChecker:
    """Verifica plausibilita' semantica dei dati di mercato.

    Esempio::

        checker = SanityChecker()
        violations = checker.check_price_data(
            ticker="AAPL", price=187.42, prev_close=185.10
        )
        if checker.is_safe_to_store(violations):
            store(...)
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._rules = self._load_config(config_path)

    @staticmethod
    def _load_config(path: Path | None) -> dict[str, dict[str, Any]]:
        """Carica config sanity_rules.yaml oppure usa i default.

        v7.1.1: il merge ora gestisce correttamente strutture nested
        (es. macro.unemployment_rate.max_value), non solo flat dicts.
        """
        rules: dict[str, dict[str, Any]] = {
            k: _deep_copy_dict(v) for k, v in _DEFAULT_RULES.items()
        }
        if path is None or not path.exists():
            return rules
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            return rules
        # Merge ricorsivo dei valori dello YAML sui default
        for key, defaults in _DEFAULT_RULES.items():
            if key in raw and isinstance(raw[key], dict):
                rules[key] = _deep_merge(defaults, raw[key])
        return rules

    # ─────────────────────────────────────────────────────────── price
    def check_price_data(
        self,
        ticker: str,
        price: float | None,
        *,
        volume: float | None = None,
        prev_close: float | None = None,
    ) -> list[SanityViolation]:
        """Regole per dati di prezzo (intraday/daily)."""
        violations: list[SanityViolation] = []
        rules = self._rules["price"]

        if price is not None:
            min_v = float(rules.get("min_value", 0.0001))
            max_v = float(rules.get("max_value", 5_000_000.0))
            max_change = float(rules.get("max_daily_change_pct", 0.50))

            if price <= min_v:
                violations.append(
                    SanityViolation(
                        field="price",
                        value=price,
                        severity=Severity.CRITICAL,
                        message=(
                            f"{ticker}: prezzo {price} <= {min_v} è impossibile. "
                            f"Dato sicuramente errato."
                        ),
                    )
                )
            elif price > max_v:
                violations.append(
                    SanityViolation(
                        field="price",
                        value=price,
                        severity=Severity.WARN,
                        message=(
                            f"{ticker}: prezzo molto alto ({price}). "
                            f"Verifica che non ci sia stato uno split o un errore di unità."
                        ),
                    )
                )

            if prev_close and prev_close > 0:
                pct = abs(price - prev_close) / prev_close
                if pct > max_change:
                    violations.append(
                        SanityViolation(
                            field="price_change",
                            value=pct,
                            severity=Severity.WARN,
                            message=(
                                f"{ticker}: variazione giornaliera {pct:.0%} > "
                                f"{max_change:.0%}. "
                                f"Possibile errore dati o evento straordinario."
                            ),
                        )
                    )

        if volume is not None:
            min_vol = float(self._rules["volume"].get("min_value", 0.0))
            if volume < min_vol:
                violations.append(
                    SanityViolation(
                        field="volume",
                        value=volume,
                        severity=Severity.CRITICAL,
                        message=f"{ticker}: volume negativo ({volume}) impossibile.",
                    )
                )

        return violations

    # ────────────────────────────────────────────────────── fundamentals
    def check_fundamental_data(
        self,
        ticker: str,
        *,
        pe_ratio: float | None = None,
        market_cap: float | None = None,
        dividend: float | None = None,
        price: float | None = None,
        eps: float | None = None,
    ) -> list[SanityViolation]:
        """Regole per dati fondamentali (P/E, market cap, EPS, ...)."""
        violations: list[SanityViolation] = []

        if pe_ratio is not None:
            r = self._rules["pe_ratio"]
            if pe_ratio < float(r.get("min_value", -500.0)):
                violations.append(
                    SanityViolation(
                        field="pe_ratio",
                        value=pe_ratio,
                        severity=Severity.CRITICAL,
                        message=(
                            f"{ticker}: P/E = {pe_ratio:.0f} < {r['min_value']}. "
                            f"Probabile errore di dato (EPS = 0 o vicino a zero)."
                        ),
                    )
                )
            elif pe_ratio > float(r.get("max_value", 5_000.0)):
                violations.append(
                    SanityViolation(
                        field="pe_ratio",
                        value=pe_ratio,
                        severity=Severity.WARN,
                        message=(
                            f"{ticker}: P/E = {pe_ratio:.0f} > {r['max_value']}. "
                            f"Improbabile, verifica EPS."
                        ),
                    )
                )
            elif pe_ratio == 0 and bool(r.get("zero_as_unavailable", True)):
                violations.append(
                    SanityViolation(
                        field="pe_ratio",
                        value=pe_ratio,
                        severity=Severity.WARN,
                        message=(
                            f"{ticker}: P/E = 0. "
                            f"Spesso indica 'dato non disponibile' nelle API, non un P/E reale."
                        ),
                    )
                )

        if market_cap is not None:
            r = self._rules["market_cap"]
            if market_cap < float(r.get("min_value", 0.0)):
                violations.append(
                    SanityViolation(
                        field="market_cap",
                        value=market_cap,
                        severity=Severity.CRITICAL,
                        message=f"{ticker}: market cap negativo impossibile.",
                    )
                )
            elif 0 < market_cap < float(r.get("min_plausible", 100_000.0)):
                violations.append(
                    SanityViolation(
                        field="market_cap",
                        value=market_cap,
                        severity=Severity.WARN,
                        message=(
                            f"{ticker}: market cap molto piccolo ({market_cap:.0f}). "
                            f"Verifica unità di misura (USD vs migliaia)."
                        ),
                    )
                )

        if dividend is not None and price is not None and price > 0:
            yield_ratio = dividend / price
            if yield_ratio > float(self._rules["dividend"].get("max_yield", 1.0)):
                violations.append(
                    SanityViolation(
                        field="dividend",
                        value=dividend,
                        severity=Severity.CRITICAL,
                        message=(
                            f"{ticker}: dividendo annuo ({dividend}) > prezzo ({price}). "
                            f"Dividend yield > 100% impossibile."
                        ),
                    )
                )
            elif yield_ratio > float(
                self._rules["dividend"].get("max_yield_warn", 0.30)
            ):
                violations.append(
                    SanityViolation(
                        field="dividend",
                        value=dividend,
                        severity=Severity.WARN,
                        message=(
                            f"{ticker}: dividend yield {yield_ratio:.0%} insolitamente alto. "
                            f"Verifica frequenza distribuzione."
                        ),
                    )
                )

        if eps is not None:
            max_abs = float(self._rules["eps"].get("max_abs_value", 10_000.0))
            if abs(eps) > max_abs:
                violations.append(
                    SanityViolation(
                        field="eps",
                        value=eps,
                        severity=Severity.WARN,
                        message=(
                            f"{ticker}: EPS = {eps}. "
                            f"Valore estremo, verifica valuta e unità."
                        ),
                    )
                )

        return violations

    # ───────────────────────────────────────────────────────────── macro
    def check_macro_data(
        self,
        series_id: str,
        value: float | None,
        *,
        indicator_type: str | None = None,
    ) -> list[SanityViolation]:
        """Regole di plausibilita' per indicatori macroeconomici (v7.1.1).

        Args:
            series_id: identificativo della serie (es. "UNRATE", "CPIAUCSL").
            value: valore osservato.
            indicator_type: tipo esplicito ("unemployment_rate", "inflation_rate",
                "gdp_growth"). Se None, viene inferito dal series_id.

        Returns:
            Lista violazioni. Vuota se il dato e' plausibile.
        """
        violations: list[SanityViolation] = []
        if value is None:
            return violations

        macro_rules = self._rules.get("macro", {})
        if not macro_rules:
            return violations

        # Inferenza tipo da series_id se non specificato
        if indicator_type is None:
            indicator_type = _infer_macro_indicator_type(series_id)
            if indicator_type is None:
                # Tipo non riconosciuto: nessun controllo applicabile
                return violations

        rule = macro_rules.get(indicator_type)
        if not isinstance(rule, dict):
            return violations

        min_value = rule.get("min_value")
        max_value = rule.get("max_value")

        # Etichetta human-readable per messaggi
        labels = {
            "unemployment_rate": "tasso di disoccupazione",
            "inflation_rate": "inflazione",
            "gdp_growth": "crescita PIL",
        }
        label = labels.get(indicator_type, indicator_type)

        if min_value is not None and value < float(min_value):
            violations.append(
                SanityViolation(
                    field=indicator_type,
                    value=value,
                    severity=Severity.CRITICAL,
                    message=(
                        f"{series_id}: {label} {value:.2f} < {min_value} "
                        f"e' implausibile. Verifica unita' di misura "
                        f"(percentuale vs decimale)."
                    ),
                )
            )

        if max_value is not None and value > float(max_value):
            violations.append(
                SanityViolation(
                    field=indicator_type,
                    value=value,
                    severity=Severity.CRITICAL,
                    message=(
                        f"{series_id}: {label} {value:.2f} > {max_value} "
                        f"e' implausibile. Verifica unita' di misura."
                    ),
                )
            )

        return violations

    # ──────────────────────────────────────────────────────── helpers
    @staticmethod
    def is_safe_to_store(violations: list[SanityViolation]) -> bool:
        """True se non ci sono violazioni CRITICAL."""
        return not any(v.severity == Severity.CRITICAL for v in violations)

    @staticmethod
    def severity_emoji(severity: Severity) -> str:
        """Emoji standard per badge UI."""
        return "❌" if severity == Severity.CRITICAL else "⚠️"


# ─────────────────────────────────────────────────────── module-level helpers
def _deep_copy_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Deep copy di un dict potenzialmente nested (uso interno _load_config)."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _deep_copy_dict(v)
        else:
            out[k] = v
    return out


def _deep_merge(
    defaults: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    """Merge ricorsivo: override sovrascrive defaults; nested dicts mergiati."""
    result = _deep_copy_dict(defaults)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# Mappa nota: series_id FRED -> tipo indicator
_FRED_SERIES_TO_TYPE: dict[str, str] = {
    # Disoccupazione
    "UNRATE": "unemployment_rate",
    "U-3": "unemployment_rate",
    # Inflazione
    "CPIAUCSL": "inflation_rate",
    "CPILFESL": "inflation_rate",
    "PCEPI": "inflation_rate",
    "T10YIE": "inflation_rate",
    # Crescita
    "GDPC1": "gdp_growth",
    "GDP": "gdp_growth",
}


def _infer_macro_indicator_type(series_id: str) -> str | None:
    """Inferisce il tipo di indicatore dal series_id FRED."""
    if not series_id:
        return None
    return _FRED_SERIES_TO_TYPE.get(series_id.strip().upper())
