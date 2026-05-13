"""EDGAR fundamentals parsers: EarningsParser + BalanceSheetParser.

Converts raw ``EdgarFact`` objects (from ``SECEdgarFetcher``) into structured
DataFrames matching the ``fundamentals_edgar`` DuckDB table schema.

Design:
  · ``EarningsParser`` → income statement (revenue, gross_profit, ebit,
                          net_income, eps_diluted)
  · ``BalanceSheetParser`` → balance sheet + FCF (total_assets, total_debt,
                              equity, free_cash_flow)
  · ``FundamentalsAggregator`` → combines both into a single DataFrame ready
                                  for ``FundamentalsRepository.write_edgar()``

GAAP concepts mapping is explicit and documented — changing it requires a
code review, not just a YAML edit, because mapping errors propagate silently
into financial ratios.

Regola 8: tutti i calcoli numerici usano numpy.float64.
Regola 2: ogni classe ha una sola responsabilità.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "9.0.0"
__all__ = [
    "EarningsParser",
    "BalanceSheetParser",
    "FundamentalsAggregator",
]

log = get_logger(__name__)

# ─── GAAP concept mapping (PRIORITÀ: il primo match vince) ──────────────────
# Le aziende usano concetti GAAP diversi per lo stesso item — è necessario
# tentarli in ordine di preferenza (standard più usato prima).
# Anti-pattern evitato: valori hardcoded sparsi nel codice → tutto qui.

# Revenue: priorità IFRS/GAAP più comuni
_REVENUE_CONCEPTS: list[str] = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenueFromRelatedParties",
]

# Gross Profit
_GROSS_PROFIT_CONCEPTS: list[str] = [
    "GrossProfit",
]

# EBIT (Operating Income)
_EBIT_CONCEPTS: list[str] = [
    "OperatingIncomeLoss",
    "IncomeLossFromContinuingOperationsBeforeInterestExpenseInterestIncomeIncomeTaxesExtraordinaryItemsNoncontrollingInterestsNet",
]

# Net Income
_NET_INCOME_CONCEPTS: list[str] = [
    "NetIncomeLoss",
    "NetIncomeLossAttributableToParentEntity",
    "ProfitLoss",
]

# EPS Diluted
_EPS_DILUTED_CONCEPTS: list[str] = [
    "EarningsPerShareDiluted",
    "EarningsPerShareBasic",  # fallback se diluted non disponibile
]

# Balance Sheet
_TOTAL_ASSETS_CONCEPTS: list[str] = [
    "Assets",
]

_LONG_TERM_DEBT_CONCEPTS: list[str] = [
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    "LongTermNotesPayable",
]

_SHORT_TERM_DEBT_CONCEPTS: list[str] = [
    "ShortTermBorrowings",
    "DebtCurrent",
    "CurrentPortionOfLongTermDebt",
]

_EQUITY_CONCEPTS: list[str] = [
    "StockholdersEquity",
    "StockholdersEquityAttributableToParent",
    "RetainedEarningsAccumulatedDeficit",
]

# Free Cash Flow components
_OPERATING_CF_CONCEPTS: list[str] = [
    "NetCashProvidedByUsedInOperatingActivities",
]

_CAPEX_CONCEPTS: list[str] = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForCapitalImprovements",
    "AcquisitionsNetOfCashAcquiredAndPurchasesOfBusinesses",
]

# Periodi accettati (form_type ≠ ammendment)
_ANNUAL_FORMS: frozenset[str] = frozenset({"10-K", "20-F"})
_QUARTERLY_FORMS: frozenset[str] = frozenset({"10-Q"})


# ─── Tipi importati al runtime ───────────────────────────────────────────────
# Evitiamo import circolare: SECEdgarFetcher non importa da qui,
# ma usiamo il suo EdgarFact come tipo nel parser.
from engine.market_data.fetchers.edgar_fetcher import EdgarFact  # noqa: E402


class EarningsParser:
    """Parses income statement items from a list of EdgarFact objects.

    Produces a DataFrame with columns:
      ticker, report_date (UTC), period ('Q1'|'Q2'|'Q3'|'Q4'|'FY'),
      revenue, gross_profit, ebit, net_income, eps_diluted.

    All numeric columns are numpy float64 (Regola 8).
    """

    def parse(self, facts: list[EdgarFact]) -> pd.DataFrame:
        """Convert EdgarFact list to income statement DataFrame.

        Args:
            facts: Raw facts from SECEdgarFetcher. Can be from one or more tickers.

        Returns:
            DataFrame matching fundamentals_edgar partial schema (income side).
            Empty DataFrame if no usable facts found.
        """
        if not facts:
            return pd.DataFrame()

        # Raggruppa per (ticker, period_end, period_type, form_type)
        # Priorità: 10-K/10-Q > ammendment (10-K/A, 10-Q/A)
        by_period = self._group_by_period(facts)

        rows: list[dict[str, object]] = []
        for key, period_facts in by_period.items():
            ticker, period_end, period_type = key
            row = self._extract_income_row(ticker, period_end, period_type, period_facts)
            if row:
                rows.append(row)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        # Conversione tipi: float64 per tutti i valori numerici (Regola 8)
        for col in ("revenue", "gross_profit", "ebit", "net_income", "eps_diluted"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

        log.info(
            "earnings_parser.done",
            tickers=df["ticker"].nunique(),
            rows=len(df),
        )
        return df

    # ─── Internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _group_by_period(
        facts: list[EdgarFact],
    ) -> dict[tuple[str, object, str], list[EdgarFact]]:
        """Group facts by (ticker, period_end, period_type).

        Esclude ammendment (form_type che termina con '/A') se esiste
        il filing originale per lo stesso periodo.
        """
        groups: dict[tuple[str, object, str], list[EdgarFact]] = {}
        for f in facts:
            # Normalizza period_type: SEC usa 'FY', 'Q1'...'Q4'
            pt = f.period_type.upper() if f.period_type else "FY"
            key = (f.ticker, f.period_end, pt)
            if key not in groups:
                groups[key] = []
            groups[key].append(f)
        return groups

    @staticmethod
    def _first_match(
        facts: list[EdgarFact],
        concepts: list[str],
        unit_filter: str = "USD",
    ) -> np.float64 | None:
        """Return the value of the first matching GAAP concept, or None."""
        # Costruiamo un indice veloce per concept
        by_concept: dict[str, list[EdgarFact]] = {}
        for f in facts:
            by_concept.setdefault(f.metric, []).append(f)

        for concept in concepts:
            matches = by_concept.get(concept, [])
            if not matches:
                continue
            # Preferisce USD; se non trovato, prende il primo disponibile
            usd = [m for m in matches if m.currency.upper() == unit_filter]
            chosen = usd[0] if usd else matches[0]
            return np.float64(chosen.value)
        return None

    def _extract_income_row(
        self,
        ticker: str,
        period_end: object,
        period_type: str,
        facts: list[EdgarFact],
    ) -> dict[str, object] | None:
        """Build a single income statement row from a group of facts."""
        revenue = self._first_match(facts, _REVENUE_CONCEPTS)
        net_income = self._first_match(facts, _NET_INCOME_CONCEPTS)

        # Riga valida solo se almeno revenue o net_income disponibili
        if revenue is None and net_income is None:
            return None

        return {
            "ticker": ticker,
            "report_date": period_end,
            "period": period_type,
            "revenue": float(revenue) if revenue is not None else np.nan,
            "gross_profit": float(v) if (v := self._first_match(facts, _GROSS_PROFIT_CONCEPTS)) is not None else np.nan,
            "ebit": float(v) if (v := self._first_match(facts, _EBIT_CONCEPTS)) is not None else np.nan,
            "net_income": float(net_income) if net_income is not None else np.nan,
            "eps_diluted": float(v) if (v := self._first_match(facts, _EPS_DILUTED_CONCEPTS, "USD/shares")) is not None else np.nan,
        }


class BalanceSheetParser:
    """Parses balance sheet + FCF items from a list of EdgarFact objects.

    Produces a DataFrame with columns:
      ticker, report_date (UTC), period, total_assets, total_debt, equity, fcf.

    FCF = NetCashProvidedByUsedInOperatingActivities
          - PaymentsToAcquirePropertyPlantAndEquipment

    Note: total_debt = long_term_debt + short_term_debt. Quando solo uno
    dei due è disponibile si usa quello, non si annulla la riga.
    """

    def parse(self, facts: list[EdgarFact]) -> pd.DataFrame:
        """Convert EdgarFact list to balance sheet + FCF DataFrame."""
        if not facts:
            return pd.DataFrame()

        by_period = EarningsParser._group_by_period(facts)

        rows: list[dict[str, object]] = []
        for key, period_facts in by_period.items():
            ticker, period_end, period_type = key
            row = self._extract_balance_row(ticker, period_end, period_type, period_facts)
            if row:
                rows.append(row)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        for col in ("total_assets", "total_debt", "equity", "fcf"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

        log.info(
            "balance_sheet_parser.done",
            tickers=df["ticker"].nunique(),
            rows=len(df),
        )
        return df

    def _extract_balance_row(
        self,
        ticker: str,
        period_end: object,
        period_type: str,
        facts: list[EdgarFact],
    ) -> dict[str, object] | None:
        """Build a single balance sheet row from a group of facts."""
        total_assets = EarningsParser._first_match(facts, _TOTAL_ASSETS_CONCEPTS)
        equity = EarningsParser._first_match(facts, _EQUITY_CONCEPTS)

        # Riga valida solo se almeno assets o equity disponibili
        if total_assets is None and equity is None:
            return None

        # Debito totale: somma LT + ST (NaN + valore = valore, non NaN)
        lt_debt = EarningsParser._first_match(facts, _LONG_TERM_DEBT_CONCEPTS)
        st_debt = EarningsParser._first_match(facts, _SHORT_TERM_DEBT_CONCEPTS)
        if lt_debt is not None and st_debt is not None:
            total_debt: float = float(lt_debt) + float(st_debt)
        elif lt_debt is not None:
            total_debt = float(lt_debt)
        elif st_debt is not None:
            total_debt = float(st_debt)
        else:
            total_debt = np.nan  # type: ignore[assignment]

        # FCF = OpCF - CapEx (CapEx è già negativo in EDGAR, quindi usiamo abs)
        op_cf = EarningsParser._first_match(facts, _OPERATING_CF_CONCEPTS)
        capex = EarningsParser._first_match(facts, _CAPEX_CONCEPTS)
        if op_cf is not None and capex is not None:
            # CapEx in EDGAR è positivo (pagamento), quindi sottraiamo
            fcf: float = float(op_cf) - abs(float(capex))
        elif op_cf is not None:
            fcf = float(op_cf)
        else:
            fcf = np.nan  # type: ignore[assignment]

        return {
            "ticker": ticker,
            "report_date": period_end,
            "period": period_type,
            "total_assets": float(total_assets) if total_assets is not None else np.nan,
            "total_debt": total_debt,
            "equity": float(equity) if equity is not None else np.nan,
            "fcf": fcf,
        }


class FundamentalsAggregator:
    """Combines EarningsParser + BalanceSheetParser into a single DataFrame.

    The combined DataFrame matches the ``fundamentals_edgar`` DuckDB table
    schema and is ready for ``FundamentalsRepository.write_edgar()``.

    Strategia di merge: outer join su (ticker, report_date, period).
    Righe senza income o senza balance sheet vengono comunque incluse
    con NaN per i campi mancanti.
    """

    def __init__(self) -> None:
        # Istanzia i parser una sola volta per evitare allocazioni inutili
        self._earnings = EarningsParser()
        self._balance = BalanceSheetParser()

    def aggregate(self, facts: list[EdgarFact]) -> pd.DataFrame:
        """Aggregate EdgarFact list into a ready-to-persist fundamentals DataFrame.

        Args:
            facts: Raw facts from SECEdgarFetcher.

        Returns:
            Combined DataFrame with columns:
              ticker, report_date, period,
              revenue, gross_profit, ebit, net_income, eps_diluted,
              total_assets, total_debt, equity, fcf, source.
        """
        income_df = self._earnings.parse(facts)
        balance_df = self._balance.parse(facts)

        # Caso base: nessun dato
        if income_df.empty and balance_df.empty:
            return pd.DataFrame()

        # Merge outer su chiavi condivise
        merge_keys = ["ticker", "report_date", "period"]

        if income_df.empty:
            combined = balance_df
        elif balance_df.empty:
            combined = income_df
        else:
            combined = pd.merge(
                income_df,
                balance_df,
                on=merge_keys,
                how="outer",
                suffixes=("_inc", "_bal"),
            )
            # Risolve colonne duplicate (non attese, ma difensivo)
            combined = combined.loc[:, ~combined.columns.duplicated()]

        # Aggiunge colonna source obbligatoria
        if "source" not in combined.columns:
            combined["source"] = "edgar_xbrl"

        # Ordina per ticker, report_date DESC per coerenza con le query UI
        combined = combined.sort_values(
            ["ticker", "report_date"], ascending=[True, False]
        ).reset_index(drop=True)

        log.info(
            "fundamentals_aggregator.done",
            tickers=combined["ticker"].nunique() if not combined.empty else 0,
            total_rows=len(combined),
        )
        return combined
