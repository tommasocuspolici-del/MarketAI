"""Centralised .env loader (v7.1.2 hotfix).

Risolve il root cause #1 dei bug ULTERIORI_ERRORI: ``app_unified.py`` non
chiamava mai ``load_dotenv()`` e quindi tutte le API key (FRED, Alpha
Vantage, Finnhub, eToro) risultavano "no API key" anche se presenti
nel file ``.env``.

Pattern d'uso (da chiamare UNA volta sola, all'avvio dell'applicazione)::

    from shared.env_loader import load_environment

    report = load_environment()
    if report.dotenv_path is None:
        log.warning("Nessun file .env trovato; le API esterne saranno disabilitate")

Comportamento:
  1. Cerca il file ``.env`` partendo dalla PROJECT_ROOT (canonico) e poi
     dalla CWD (fallback per chi lancia Streamlit da subdirectory).
  2. Carica le variabili in ``os.environ`` SENZA sovrascrivere quelle
     gia' definite (priorita' all'environment di sistema, in linea con la
     prassi 12-factor).
  3. Ritorna un :class:`EnvLoadReport` che descrive in modo strutturato:
     - quale file e' stato caricato (o None);
     - quali API key sono presenti / mancanti / placeholder.
  4. NON stampa segreti (Regola 15): logga solo nomi e booleani.

Convenzioni v6.0 rispettate: type hints completi, structlog (Regola 6),
nessun magic number, import assoluti.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from shared.constants import PROJECT_ROOT
from shared.logger import get_logger

__version__ = "7.1.2"

__all__ = [
    "EnvLoadReport",
    "ApiKeyStatus",
    "load_environment",
    "get_api_key_statuses",
]

log = get_logger(__name__)


# Valori usati come placeholder nel .env.example: se l'utente non li sostituisce
# li trattiamo come "non configurati" anche se la variabile e' settata.
_PLACEHOLDER_PREFIXES: tuple[str, ...] = (
    "your_",
    "YOUR_",
    "<YOUR_",
)
_PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {"", "changeme", "CHANGEME", "todo", "TODO", "xxx", "XXX"}
)

# Mappa nome_friendly -> ENV var name(s) (la prima e' canonica, le altre alias).
# Usata da ``get_api_key_statuses`` per riassumere lo stato in UI/log.
_TRACKED_KEYS: dict[str, tuple[str, ...]] = {
    "FRED": ("FRED_API_KEY",),
    "Alpha Vantage": ("ALPHA_VANTAGE_KEY", "ALPHA_VANTAGE_API_KEY"),
    "Finnhub": ("FINNHUB_API_KEY",),
    "eToro API": ("ETORO_API_KEY",),
    "eToro User": ("ETORO_USER_KEY",),
    "BLS (opt.)": ("BLS_API_KEY",),
    "SEC EDGAR UA": ("SEC_EDGAR_USER_AGENT",),
}


@dataclass(frozen=True, slots=True)
class ApiKeyStatus:
    """Stato di una singola API key in environment."""

    name: str
    env_var: str
    is_set: bool
    is_placeholder: bool

    @property
    def is_usable(self) -> bool:
        """True se la chiave e' presente E non e' un placeholder."""
        return self.is_set and not self.is_placeholder


@dataclass(frozen=True, slots=True)
class EnvLoadReport:
    """Report strutturato del caricamento .env."""

    dotenv_path: Path | None
    loaded_count: int
    candidates_tried: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def loaded_successfully(self) -> bool:
        """True se almeno un file .env e' stato trovato e caricato."""
        return self.dotenv_path is not None


# ─────────────────────────────────────────────────────── private helpers
def _is_placeholder(value: str) -> bool:
    """Verifica se un valore e' un placeholder dal .env.example."""
    stripped = value.strip()
    if stripped in _PLACEHOLDER_VALUES:
        return True
    return any(stripped.startswith(p) for p in _PLACEHOLDER_PREFIXES)


def _candidate_paths(explicit: Path | None) -> list[Path]:
    """Lista ordinata di percorsi candidati per il file .env.

    Ordine di preferenza:
      1. Percorso esplicito passato dall'utente.
      2. PROJECT_ROOT/.env (canonico — lo usano docker-compose, .gitignore).
      3. CWD/.env (fallback se l'utente lancia Streamlit da subdir).
    """
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.append(PROJECT_ROOT / ".env")
    cwd_env = Path.cwd() / ".env"
    if cwd_env not in candidates:
        candidates.append(cwd_env)
    return candidates


def _load_dotenv_file(path: Path) -> int:
    """Parser .env minimale stdlib-only.

    Usato come fallback se ``python-dotenv`` non e' installato. Supporta
    le sintassi base ``KEY=VALUE``, commenti ``#``, valori tra virgolette
    semplici/doppie. NON espande ``${VAR}`` ne' fa command substitution.

    Returns:
        Numero di variabili caricate (escluse quelle gia' presenti in env).
    """
    n_loaded = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("env_file_read_failed", path=str(path), error=str(exc))
        return 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip leading 'export ' a la bash
        if key.startswith("export "):
            key = key[len("export "):].strip()
        # Rimuovi virgolette esterne se presenti
        if len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        ):
            value = value[1:-1]
        # Strip inline comment dopo lo spazio se non e' tra virgolette
        # (gia' gestito sopra: se il valore era quotato non veniamo qui)
        if "#" in value and " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        # Non sovrascrivere variabili gia' presenti in environment (12-factor).
        if key and key not in os.environ:
            os.environ[key] = value
            n_loaded += 1
    return n_loaded


# ─────────────────────────────────────────────────────── public api
def load_environment(
    explicit_path: Path | None = None,
    *,
    override: bool = False,
) -> EnvLoadReport:
    """Carica il file .env nell'environment del processo.

    Idempotente: chiamare piu' volte non causa effetti collaterali se le
    variabili sono gia' presenti. Usa python-dotenv se disponibile,
    altrimenti un parser minimale stdlib-only.

    Args:
        explicit_path: Percorso esplicito del .env (default: cerca in
            PROJECT_ROOT/.env e CWD/.env).
        override: Se True, le variabili nel .env sovrascrivono quelle
            gia' presenti in environment. Default False (12-factor).

    Returns:
        :class:`EnvLoadReport` con il risultato dell'operazione.
    """
    candidates = _candidate_paths(explicit_path)
    chosen: Path | None = None
    for candidate in candidates:
        if candidate.is_file():
            chosen = candidate
            break

    if chosen is None:
        log.info(
            "env_file_not_found",
            tried=[str(c) for c in candidates],
            hint=(
                "Crea un file .env nella radice del progetto. "
                "Esempio: cp .env.example .env"
            ),
        )
        return EnvLoadReport(
            dotenv_path=None,
            loaded_count=0,
            candidates_tried=tuple(candidates),
        )

    n_loaded = 0
    try:
        # Path preferito: python-dotenv (gia' nelle dipendenze pyproject.toml)
        from dotenv import dotenv_values

        kv = dotenv_values(chosen)
        for k, v in kv.items():
            if not k:
                continue
            if v is None:
                continue
            if k in os.environ and not override:
                continue
            os.environ[k] = v
            n_loaded += 1
    except ImportError:
        # Fallback: parser stdlib-only
        log.warning(
            "python_dotenv_not_installed",
            hint="Installa con: poetry add python-dotenv",
        )
        n_loaded = _load_dotenv_file(chosen)

    log.info(
        "env_file_loaded",
        path=str(chosen),
        n_vars=n_loaded,
    )
    return EnvLoadReport(
        dotenv_path=chosen,
        loaded_count=n_loaded,
        candidates_tried=tuple(candidates),
    )


def get_api_key_statuses() -> list[ApiKeyStatus]:
    """Riassume lo stato di tutte le API key tracciate.

    Pensata per l'UI di diagnostica (E0_API_Health) e per i log di startup.
    NON ritorna mai i valori delle chiavi (Regola 15).

    Returns:
        Lista di :class:`ApiKeyStatus`, una per chiave tracciata.
    """
    out: list[ApiKeyStatus] = []
    for friendly_name, env_vars in _TRACKED_KEYS.items():
        # Prendiamo la prima env var configurata (le altre sono alias storici).
        chosen_var = env_vars[0]
        chosen_value = ""
        for ev in env_vars:
            v = os.environ.get(ev, "").strip()
            if v:
                chosen_var = ev
                chosen_value = v
                break
        is_set = bool(chosen_value)
        is_placeholder = is_set and _is_placeholder(chosen_value)
        out.append(
            ApiKeyStatus(
                name=friendly_name,
                env_var=chosen_var,
                is_set=is_set,
                is_placeholder=is_placeholder,
            )
        )
    return out
