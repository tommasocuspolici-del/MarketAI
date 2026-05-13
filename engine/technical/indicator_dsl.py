"""DSL Evaluator per indicatori tecnici personalizzati.

Permette all'utente di definire indicatori come:
  "EMA(close, 20)"                    → EMA 20 periodi
  "RSI(close, 14) > 70"               → segnale overbought (boolean Series)
  "close / EMA(close, 200) - 1"       → distanza % da EMA200
  "MACD(close, 12, 26, 9)"            → MACD histogram

SICUREZZA: usa ast.parse() + whitelist di nodi AST permessi.
Mai eval() né exec(). Qualsiasi costrutto non whitelistato solleva DSLParseError.

Regola 8: tutti i calcoli numerici usano pandas/numpy (mai float nativo).
Regola 2 (SRP): questo modulo valuta le espressioni — non le persiste.
               La persistenza è in IndicatorRegistry.
"""
from __future__ import annotations

import ast
from typing import Any, Union

import numpy as np
import pandas as pd

from shared.exceptions import DSLEvalError, DSLParseError
from shared.logger import get_logger

__version__ = "9.0.0"
__all__ = ["DSLEvaluator", "validate_expression", "list_supported_functions"]

log = get_logger(__name__)

# Colonne OHLCV accessibili nel DSL (Regola 7: nessuna stringa magic inline)
_ALLOWED_COLUMNS: frozenset[str] = frozenset(
    {"close", "open", "high", "low", "volume"}
)

# Nodi AST permessi (whitelist esplicita — tutto il resto è vietato)
_ALLOWED_NODE_TYPES: frozenset[type] = frozenset({
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.Call, ast.Name, ast.Constant, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd,
    ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq,
    ast.And, ast.Or, ast.BoolOp,
})

# Tipo restituito dai nodi: Series o scalare
_NodeResult = Union[pd.Series, float, int]


# ─── Funzioni di indicatore tecnico (pandas vettorizzate, Regola 8) ──────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average. pandas ewm() è completamente vettorizzato."""
    return series.ewm(span=int(period), adjust=False, min_periods=int(period)).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=int(period), min_periods=int(period)).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    """RSI (Relative Strength Index). Usa Wilder smoothing (EWM alpha=1/period)."""
    delta = series.diff()
    gain  = delta.clip(lower=0.0)
    loss  = (-delta).clip(lower=0.0)
    avg_g = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    # Divide sicuro: avg_l=0 → RS=inf → RSI=100
    rs = avg_g / avg_l.replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).astype(np.float64)


def _macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.Series:
    """MACD Histogram = MACD line − Signal line."""
    ema_fast   = series.ewm(span=fast, adjust=False).mean()
    ema_slow   = series.ewm(span=slow, adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return (macd_line - signal_line).astype(np.float64)


def _std(series: pd.Series, period: int) -> pd.Series:
    """Rolling standard deviation."""
    return series.rolling(window=int(period), min_periods=int(period)).std()


def _rolling_max(series: pd.Series, period: int) -> pd.Series:
    """Rolling maximum."""
    return series.rolling(window=int(period), min_periods=1).max()


def _rolling_min(series: pd.Series, period: int) -> pd.Series:
    """Rolling minimum."""
    return series.rolling(window=int(period), min_periods=1).min()


def _abs_fn(series: pd.Series) -> pd.Series:
    """Valore assoluto di una serie."""
    return series.abs()


def _log_fn(series: pd.Series) -> pd.Series:
    """Logaritmo naturale (utile per ritorni continui)."""
    return np.log(series.clip(lower=1e-10)).astype(np.float64)


def _pct_change(series: pd.Series, period: int = 1) -> pd.Series:
    """Variazione percentuale rispetto a N barre precedenti."""
    return series.pct_change(periods=int(period)).astype(np.float64)


# Mapping nome → (funzione, n_args_min, n_args_max)
_FUNCTIONS: dict[str, tuple[Any, int, int]] = {
    "EMA":        (_ema,        2, 2),
    "SMA":        (_sma,        2, 2),
    "RSI":        (_rsi,        2, 2),
    "MACD":       (_macd,       1, 4),   # MACD(close) o MACD(close, 12, 26, 9)
    "STD":        (_std,        2, 2),
    "MAX":        (_rolling_max, 2, 2),
    "MIN":        (_rolling_min, 2, 2),
    "ABS":        (_abs_fn,     1, 1),
    "LOG":        (_log_fn,     1, 1),
    "PCT_CHANGE": (_pct_change, 1, 2),
}


def list_supported_functions() -> list[str]:
    """Ritorna la lista dei nomi di funzione supportati nel DSL."""
    return sorted(_FUNCTIONS.keys())


# ─── DSL Evaluator ───────────────────────────────────────────────────────────

class DSLEvaluator:
    """Valuta espressioni DSL su un DataFrame OHLCV.

    ANTI-REGRESSIONE: non usare mai eval() né exec(). La sicurezza del DSL
    si basa ESCLUSIVAMENTE sul walking dell'AST con whitelist esplicita.
    Qualsiasi modifica che introduce eval/exec è un bug di sicurezza.

    Uso::
        ev = DSLEvaluator()
        series = ev.evaluate("RSI(close, 14)", df)   # pd.Series float64
    """

    def evaluate(self, expression: str, df: pd.DataFrame) -> pd.Series:
        """Valuta un'espressione DSL su un DataFrame OHLCV.

        Args:
            expression: Stringa DSL (es. "EMA(close, 20)").
            df: DataFrame con colonne ts, open, high, low, close, volume.

        Returns:
            pd.Series float64 allineata all'indice di df.

        Raises:
            DSLParseError: Sintassi non valida o funzione/colonna non supportata.
            DSLEvalError: Errore durante il calcolo (divisione per zero, ecc.).
        """
        expression = expression.strip()
        if not expression:
            raise DSLParseError("L'espressione DSL non può essere vuota.")
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise DSLParseError(
                f"Sintassi non valida: {exc.msg} (riga {exc.lineno})"
            ) from exc

        # Verifica preventiva: ogni nodo dell'AST deve essere whitelistato
        self._check_ast(tree)

        try:
            result = self._eval_node(tree.body, df)
        except DSLParseError:
            raise
        except DSLEvalError:
            raise
        except Exception as exc:
            raise DSLEvalError(
                f"Errore durante il calcolo di '{expression}': {exc}"
            ) from exc

        # Normalizza il risultato a pd.Series float64
        if isinstance(result, pd.Series):
            return result.astype(np.float64)
        # Scalare → broadcast su tutta la serie
        return pd.Series(float(result), index=df.index, dtype=np.float64)

    # ─── AST safety check ───────────────────────────────────────────────────

    def _check_ast(self, tree: ast.AST) -> None:
        """Verifica che ogni nodo dell'AST sia nel whitelist.

        ANTI-REGRESSIONE: questo metodo deve essere chiamato PRIMA di _eval_node.
        Non rimuovere né bypassare questo check.
        """
        for node in ast.walk(tree):
            if type(node) not in _ALLOWED_NODE_TYPES:
                raise DSLParseError(
                    f"Costrutto non permesso nel DSL: '{type(node).__name__}'. "
                    f"Usa solo: EMA, SMA, RSI, MACD, STD, MAX, MIN, ABS, LOG, "
                    f"PCT_CHANGE e operatori aritmetici/di confronto."
                )

    # ─── Node evaluator (ricorsivo) ──────────────────────────────────────────

    def _eval_node(self, node: ast.expr, df: pd.DataFrame) -> _NodeResult:
        """Valuta ricorsivamente un nodo AST."""
        if isinstance(node, ast.Constant):
            return float(node.value)

        if isinstance(node, ast.Name):
            name = node.id.lower()
            if name not in _ALLOWED_COLUMNS:
                raise DSLParseError(
                    f"Colonna '{node.id}' non riconosciuta. "
                    f"Usa: {', '.join(sorted(_ALLOWED_COLUMNS))}"
                )
            # Supporta sia 'close' che 'Close' nel DataFrame
            col = name if name in df.columns else name.capitalize()
            if col not in df.columns:
                raise DSLParseError(f"Colonna '{name}' non presente nel DataFrame.")
            return df[col].astype(np.float64)

        if isinstance(node, ast.BinOp):
            lv = self._eval_node(node.left, df)
            rv = self._eval_node(node.right, df)
            return self._apply_binop(node.op, lv, rv)

        if isinstance(node, ast.UnaryOp):
            v = self._eval_node(node.operand, df)
            if isinstance(node.op, ast.USub):
                return -v  # type: ignore[operator]
            return v

        if isinstance(node, ast.Compare):
            lv = self._eval_node(node.left, df)
            for op, comp in zip(node.ops, node.comparators):
                rv = self._eval_node(comp, df)
                lv = self._apply_compare(op, lv, rv)  # type: ignore[assignment]
            return lv  # type: ignore[return-value]

        if isinstance(node, ast.BoolOp):
            results = [self._eval_node(v, df) for v in node.values]
            if isinstance(node.op, ast.And):
                out = results[0]
                for r in results[1:]:
                    out = out & r  # type: ignore[operator]
                return out  # type: ignore[return-value]
            out = results[0]
            for r in results[1:]:
                out = out | r  # type: ignore[operator]
            return out  # type: ignore[return-value]

        if isinstance(node, ast.Call):
            return self._eval_call(node, df)

        # Nodo non gestito (non dovrebbe accadere dopo _check_ast)
        raise DSLParseError(f"Nodo AST non valutabile: {type(node).__name__}")

    def _eval_call(self, node: ast.Call, df: pd.DataFrame) -> pd.Series:
        """Valuta una chiamata a funzione DSL (es. EMA(close, 20))."""
        if not isinstance(node.func, ast.Name):
            raise DSLParseError("Solo funzioni semplici sono permesse (no metodi).")
        fname = node.func.id.upper()
        if fname not in _FUNCTIONS:
            raise DSLParseError(
                f"Funzione '{fname}' non supportata. "
                f"Disponibili: {', '.join(list_supported_functions())}"
            )
        fn, min_args, max_args = _FUNCTIONS[fname]
        if not (min_args <= len(node.args) <= max_args):
            raise DSLParseError(
                f"{fname} richiede {min_args}–{max_args} argomenti, "
                f"ricevuti {len(node.args)}."
            )
        # Valuta ogni argomento (possono essere Series o scalari)
        evaluated: list[Any] = []
        for arg in node.args:
            v = self._eval_node(arg, df)
            # Argomenti numerici come period devono essere interi
            if isinstance(v, float):
                evaluated.append(int(v))
            else:
                evaluated.append(v)
        result = fn(*evaluated)
        if not isinstance(result, pd.Series):
            return pd.Series(result, index=df.index, dtype=np.float64)
        return result

    # ─── Operatori ──────────────────────────────────────────────────────────

    @staticmethod
    def _apply_binop(op: ast.operator, lv: _NodeResult, rv: _NodeResult) -> _NodeResult:
        """Applica operatore aritmetico binario."""
        if isinstance(op, ast.Add):
            return lv + rv  # type: ignore[operator]
        if isinstance(op, ast.Sub):
            return lv - rv  # type: ignore[operator]
        if isinstance(op, ast.Mult):
            return lv * rv  # type: ignore[operator]
        if isinstance(op, ast.Div):
            # Divisione sicura: evita ZeroDivisionError su Series
            if isinstance(rv, pd.Series):
                rv = rv.replace(0.0, np.nan)
            elif rv == 0:
                raise DSLEvalError("Divisione per zero nell'espressione DSL.")
            return lv / rv  # type: ignore[operator]
        raise DSLParseError(f"Operatore '{type(op).__name__}' non supportato.")

    @staticmethod
    def _apply_compare(op: ast.cmpop, lv: _NodeResult, rv: _NodeResult) -> pd.Series:
        """Applica operatore di confronto, ritorna pd.Series[bool]."""
        ops_map = {
            ast.Gt:  lambda a, b: a > b,
            ast.Lt:  lambda a, b: a < b,
            ast.GtE: lambda a, b: a >= b,
            ast.LtE: lambda a, b: a <= b,
            ast.Eq:  lambda a, b: a == b,
            ast.NotEq: lambda a, b: a != b,
        }
        fn = ops_map.get(type(op))
        if fn is None:
            raise DSLParseError(f"Operatore '{type(op).__name__}' non supportato.")
        return fn(lv, rv)  # type: ignore[return-value]


# ─── Utility pubblica ─────────────────────────────────────────────────────────

def validate_expression(expression: str, sample_df: pd.DataFrame) -> str | None:
    """Valida un'espressione DSL su un DataFrame campione.

    Returns:
        None se valida; stringa con messaggio di errore se non valida.
    """
    try:
        ev = DSLEvaluator()
        result = ev.evaluate(expression, sample_df)
        if result.dropna().empty:
            return "L'espressione produce solo valori NaN (period troppo lungo?)."
        return None
    except (DSLParseError, DSLEvalError) as exc:
        return str(exc)
    except Exception as exc:
        return f"Errore inatteso: {exc}"
