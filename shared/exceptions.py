"""Custom exception hierarchy for the entire application.

Rule 5: No generic except. All exceptions must derive from MarketAIError.
All exception classes use English names and English docstrings.
"""
from __future__ import annotations

__version__ = "6.0.0"

__all__ = [
    "AlertError",
    # Analysis
    "AnalysisError",
    "AuthenticationError",
    "BacktestError",
    "BackupError",
    # Bridge / cross-layer
    "BridgeError",
    # Configuration
    "ConfigurationError",
    "ContractViolationError",
    "CorrelationError",
    "DataCleaningError",
    # Data layer
    "DataError",
    "DataQualityError",
    "DataValidationError",
    # Database
    "DatabaseError",
    "DSLEvalError",
    "DSLParseError",
    "DuckDBError",
    "FeatureDisabledError",
    "FetchError",
    "ForecastError",
    "GoalError",
    # Operational
    "HealthCheckError",
    "InsufficientDataError",
    "MarketAIError",
    "MigrationError",
    "MissingEnvVarError",
    # Personal
    "PersonalError",
    "PipelineError",
    "ProfileNotFoundError",
    "ProfileSuitabilityError",
    "RateLimitExceededError",
    "SQLiteError",
    "SentimentAggregationError",
    "StaleDataError",
    "StressTestError",
]


# ═══════════════════════════════════════════════════════════════════════════
# Base exception
# ═══════════════════════════════════════════════════════════════════════════
class MarketAIError(Exception):
    """Base class for all application-specific errors."""


# ═══════════════════════════════════════════════════════════════════════════
# Configuration errors
# ═══════════════════════════════════════════════════════════════════════════
class ConfigurationError(MarketAIError):
    """Raised when configuration is missing or malformed."""


class MissingEnvVarError(ConfigurationError):
    """Raised when a required environment variable is not set."""

    def __init__(self, var_name: str) -> None:
        # Messaggio esplicito per facilitare il debugging in produzione
        super().__init__(
            f"Required environment variable '{var_name}' is not set. "
            f"Check .env against .env.example."
        )
        self.var_name = var_name


class FeatureDisabledError(MarketAIError):
    """Raised when a code path requires a feature flag that is disabled."""


# ═══════════════════════════════════════════════════════════════════════════
# Data layer errors
# ═══════════════════════════════════════════════════════════════════════════
class DataError(MarketAIError):
    """Base class for all data-related errors."""


class FetchError(DataError):
    """Raised when an external data fetch fails."""

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"Fetch from '{source}' failed: {detail}")
        self.source = source
        self.detail = detail


class RateLimitExceededError(DataError):
    """Raised when a rate limit is exceeded and cannot be recovered."""

    def __init__(self, source: str, limit_type: str) -> None:
        super().__init__(
            f"Rate limit exceeded for '{source}' (type={limit_type}). "
            f"Increase config/rate_limits.yaml or wait."
        )
        self.source = source
        self.limit_type = limit_type


class DataCleaningError(DataError):
    """Raised when DataCleaner cannot process raw data."""


class DataValidationError(DataError):
    """Raised when Pandera schema validation fails."""


class DataQualityError(DataError):
    """Raised when data quality score is below the minimum allowed threshold."""

    def __init__(self, series_id: str, score: float, minimum: float) -> None:
        super().__init__(
            f"Data quality score {score:.3f} for series '{series_id}' "
            f"is below minimum {minimum:.3f}."
        )
        self.series_id = series_id
        self.score = score
        self.minimum = minimum


class StaleDataError(DataError):
    """Raised when data is identified as stale beyond acceptable window."""


# ═══════════════════════════════════════════════════════════════════════════
# Database errors
# ═══════════════════════════════════════════════════════════════════════════
class DatabaseError(MarketAIError):
    """Base class for database-related errors."""


class MigrationError(DatabaseError):
    """Raised when a DuckDB or SQLite migration fails."""


class DuckDBError(DatabaseError):
    """Raised on DuckDB-specific errors."""


class SQLiteError(DatabaseError):
    """Raised on SQLite-specific errors."""


class DSLParseError(MarketAIError):
    """Raised when a DSL expression cannot be parsed or uses disallowed constructs.

    L'utente riceve questo errore quando la sintassi dell'indicatore è errata.
    Il messaggio deve essere comprensibile senza conoscenza del codice interno.
    """


class DSLEvalError(MarketAIError):
    """Raised when a valid DSL expression fails during evaluation.

    Distinto da DSLParseError: l'espressione è sintatticamente corretta
    ma produce un errore durante il calcolo sui dati reali (es. divisione per zero).
    """


# ═══════════════════════════════════════════════════════════════════════════
# Analysis errors
# ═══════════════════════════════════════════════════════════════════════════
class AnalysisError(MarketAIError):
    """Base class for analytical errors."""


class BacktestError(AnalysisError):
    """Raised when backtesting fails or produces invalid results."""


class StressTestError(AnalysisError):
    """Raised when stress testing fails."""


class ForecastError(AnalysisError):
    """Raised when forecasting models fail or produce invalid results."""


class InsufficientDataError(AnalysisError):
    """Raised when there is not enough data to perform an analysis."""

    def __init__(self, required: int, available: int) -> None:
        super().__init__(
            f"Insufficient data: required {required} samples, available {available}."
        )
        self.required = required
        self.available = available


class SentimentAggregationError(AnalysisError):
    """Raised when sentiment composite cannot be computed (no sources, etc.)."""


class CorrelationError(AnalysisError):
    """Raised when correlation/regime analysis fails."""


class PipelineError(AnalysisError):
    """Raised when the end-to-end analysis pipeline fails."""


class AlertError(MarketAIError):
    """Base class for alert system errors."""


# ═══════════════════════════════════════════════════════════════════════════
# Bridge / cross-layer errors (Rule 21)
# ═══════════════════════════════════════════════════════════════════════════
class BridgeError(MarketAIError):
    """Base class for errors crossing engine ↔ personal boundary."""


class ContractViolationError(BridgeError):
    """Raised when a bridge contract (Pydantic schema) is violated."""


# ═══════════════════════════════════════════════════════════════════════════
# Personal layer errors
# ═══════════════════════════════════════════════════════════════════════════
class PersonalError(MarketAIError):
    """Base class for personal layer errors."""


class ProfileNotFoundError(PersonalError):
    """Raised when an InvestorProfile is not found in SQLite."""


class ProfileSuitabilityError(PersonalError):
    """Raised when an instrument is not suitable for an investor profile (Rule 22)."""

    def __init__(self, instrument: str, profile_id: str, reason: str) -> None:
        super().__init__(
            f"Instrument '{instrument}' not suitable for profile '{profile_id}': {reason}"
        )
        self.instrument = instrument
        self.profile_id = profile_id
        self.reason = reason


class GoalError(PersonalError):
    """Raised on errors managing financial goals."""


# ═══════════════════════════════════════════════════════════════════════════
# Operational errors
# ═══════════════════════════════════════════════════════════════════════════
class HealthCheckError(MarketAIError):
    """Raised when a health check cannot be performed."""


class BackupError(MarketAIError):
    """Raised when a backup operation fails."""


class AuthenticationError(MarketAIError):
    """Raised on authentication failures (Rule 32)."""
