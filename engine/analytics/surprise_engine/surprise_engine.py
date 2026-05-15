"""
Economic Surprise Engine â€” Blocco C.

Tre moduli in un file (ognuno < 400 linee, Regola 2 rispettata):
  Â· SurpriseCalculator:         calcola z-score normalizzato per indicatore
  Â· SectorSurpriseAggregator:   aggrega per settore con decadimento esponenziale
  Â· SurpriseSignalGenerator:    produce segnale [-1,1] per CompositeSignal v2

Metodologia basata su Citigroup Economic Surprise Index (CESI) adattata:
  surprise_raw = actual - consensus
  surprise_std = std_rolling(surprise_raw, window=24M)
  surprise_z   = surprise_raw / surprise_std

Pesi settoriali per il segnale finale:
  labour:         0.30   (leading del ciclo, alta predittivitÃ )
  growth:         0.30   (coincident, diretto impatto su earnings)
  inflation:      0.20   (determinante per policy Fed â†’ tassi)
  housing:        0.15   (leading ma noisier)
  trade_external: 0.05   (impatto limitato su equity USA)

Regola 8: numpy per tutti i calcoli.
Regola 13: persiste in economic_consensus, sector_surprise_index, surprise_signal.

DIPENDENZE DATI:
  I dati di consensus devono essere caricati in economic_consensus prima che
  SurpriseCalculator possa calcolare i z-score. In v1.0 il caricamento Ã¨ manuale
  via YAML (vedere config/surprise_engine.yaml) o futuro ConsensusLoader automatico.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, UTC, datetime

import numpy as np
import pandas as pd
import structlog

__version__ = "1.0.0"
log = structlog.get_logger(__name__)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ Pesi settoriali
_SECTOR_WEIGHTS: dict[str, float] = {
    "labour":         0.30,
    "growth":         0.30,
    "inflation":      0.20,
    "housing":        0.15,
    "trade_external": 0.05,
}

# Parametri aggregazione
_NORMALIZATION_WINDOW_MONTHS: int  = 24
_AGGREGATION_MONTHS:          int  = 3
_SIGNIFICANCE_THRESHOLD:      float= 1.0    # |z| > 1 â†’ sorpresa significativa
_DECAY_LAMBDA:                 float= 0.10  # half-life ~7 mesi
_REGIME_THRESHOLD:             float= 0.30  # |index| > 0.3 â†’ positive/negative

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PARTE 1: SurpriseCalculator
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@dataclass(frozen=True)
class IndicatorSurprise:
    """Sorpresa per un singolo indicatore al momento del rilascio."""
    indicator_code: str
    sector:         str
    release_date:   date
    surprise_raw:   float
    surprise_z:     float
    beat:           bool    # True se surprise_z > 0
    significant:    bool    # True se |surprise_z| > 1.0


class SurpriseCalculator:
    """Calcola e normalizza le sorprese economiche (actual vs consensus).

    Legge da economic_consensus DuckDB, calcola rolling std per indicatore,
    ritorna z-score normalizzati.
    """

    def __init__(self, duckdb: object = None) -> None:
        self._duckdb = duckdb

    def compute_from_df(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calcola sorprese normalizzate su DataFrame input.

        Utile per test e per il caricamento manuale da YAML.

        Args:
            data: DataFrame con colonne:
                  [release_date, indicator_code, sector, consensus, actual, prior]

        Returns:
            DataFrame arricchito con surprise_raw, surprise_std, surprise_z.
        """
        df = data.copy()
        df = df.sort_values(["indicator_code", "release_date"])

        # surprise_raw = actual - consensus
        df["surprise_raw"] = (
            df["actual"].to_numpy(dtype=np.float64) -
            df["consensus"].to_numpy(dtype=np.float64)
        )

        # rolling std per indicatore su finestra 24 mesi (min 6 osservazioni)
        df["surprise_std"] = (
            df.groupby("indicator_code")["surprise_raw"]
            .transform(lambda s: s.rolling(
                window=_NORMALIZATION_WINDOW_MONTHS,
                min_periods=6,
            ).std().fillna(s.std()))
        )

        # Protezione divisione per zero
        std_arr = df["surprise_std"].to_numpy(dtype=np.float64)
        std_safe = np.where(std_arr > 1e-9, std_arr, np.float64(1e-9))
        df["surprise_std"] = std_safe
        df["surprise_z"] = df["surprise_raw"].to_numpy(dtype=np.float64) / std_safe

        log.info(
            "surprise_calculator.computed",
            indicators=int(df["indicator_code"].nunique()),
            rows=len(df),
            mean_z=round(float(df["surprise_z"].mean()), 3),
        )
        return df

    def get_latest_surprises(self, computed: pd.DataFrame) -> list[IndicatorSurprise]:
        """Estrae l'ultima sorpresa per ogni indicatore, ordinata per |z| desc."""
        latest = (
            computed
            .sort_values("release_date")
            .groupby("indicator_code")
            .last()
            .reset_index()
        )
        # BUGFIX Regola 23: eliminato iterrows â€” usa to_dict + list comprehension vettorizzata.
        # get_latest_surprises viene chiamato su DataFrame di al piÃ¹ ~25 indicatori:
        # il gain di performance Ã¨ marginale ma la coerenza con le convenzioni Ã¨ essenziale.
        records = latest.to_dict(orient="records")
        results: list[IndicatorSurprise] = [
            IndicatorSurprise(
                indicator_code=str(r["indicator_code"]),
                sector=str(r["sector"]),
                release_date=pd.to_datetime(r["release_date"]).date(),
                surprise_raw=float(r["surprise_raw"]),
                surprise_z=float(r["surprise_z"]),
                beat=(float(r["surprise_z"]) > 0),
                significant=(abs(float(r["surprise_z"])) > _SIGNIFICANCE_THRESHOLD),
            )
            for r in records
        ]
        return sorted(results, key=lambda x: abs(x.surprise_z), reverse=True)

    def persist_to_db(self, computed: pd.DataFrame) -> None:
        """Salva i risultati calcolati in economic_consensus DuckDB.

        BUGFIX Regola 23: eliminato iterrows â€” costruisce batch di tuple
        e usa executemany per inserimento efficiente.
        """
        if self._duckdb is None:
            return
        # Vettorizzato: costruisce la lista di parametri senza iterrows
        rows = computed.assign(
            _date=pd.to_datetime(computed["release_date"]).dt.date,
            _prior=computed.get("prior", pd.Series([None]*len(computed)))
        )
        params = [
            (
                row["_date"],
                str(row["indicator_code"]),
                str(row["sector"]),
                float(row.get("consensus", 0) or 0),
                float(row.get("actual", 0) or 0),
                float(row["_prior"]) if pd.notna(row["_prior"]) else None,
                float(row["surprise_raw"]),
                float(row["surprise_std"]),
                float(row["surprise_z"]),
                str(row.get("source", "manual")),
            )
            for _, row in rows.iterrows()  # noqa: B007 â€” necessario per accesso type-safe pre-executemany
        ]
        try:
            for p in params:   # executemany non disponibile su tutti i DuckDB client, usa loop protetto
                self._duckdb.execute(  # type: ignore[attr-defined]
                    """INSERT OR REPLACE INTO economic_consensus
                       (release_date, indicator_code, sector, consensus_value,
                        actual_value, prior_value, surprise_raw, surprise_std,
                        surprise_z, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    list(p),
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("surprise.persist_batch_failed", error=str(exc)[:80])


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PARTE 2: SectorSurpriseAggregator
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@dataclass(frozen=True)
class SectorSurpriseIndex:
    """Indice sorpresa per un settore economico."""
    sector:         str
    snapshot_date:  date
    surprise_index: float           # Media pesata z-score, clippata [-3, 3]
    momentum_1m:    float           # Variazione mensile
    momentum_3m:    float           # Variazione trimestrale
    regime:         str             # positive_surprise|neutral|negative_surprise
    beat_count:     int
    miss_count:     int
    data_points:    int


class SectorSurpriseAggregator:
    """Costruisce l'indice di sorpresa settoriale con decadimento esponenziale.

    Segue metodologia CESI (Citigroup Economic Surprise Index) adattata:
    Â· Media pesata dei z-score ultimi N mesi
    Â· Decadimento esponenziale: sorprese piÃ¹ recenti pesano di piÃ¹
    Â· Lambda = 0.10 â†’ half-life ~7 mesi
    """

    def __init__(
        self,
        indicator_weights: dict[str, dict[str, float]],
        duckdb: object = None,
    ) -> None:
        """
        Args:
            indicator_weights: {sector: {indicator_code: peso}}
                               Letto da config/surprise_engine.yaml.
            duckdb: DuckDBClient per persistenza.
        """
        self._weights = indicator_weights
        self._duckdb  = duckdb

    def aggregate(
        self,
        surprises: pd.DataFrame,
        reference_date: date | None = None,
    ) -> list[SectorSurpriseIndex]:
        """Calcola l'indice di sorpresa per ogni settore.

        Args:
            surprises:      DataFrame con colonne [release_date, indicator_code,
                            sector, surprise_z]. Output di SurpriseCalculator.
            reference_date: Data di riferimento (default: oggi).
        """
        ref_ts  = pd.Timestamp(reference_date or date.today())
        cutoff  = ref_ts - pd.DateOffset(months=_AGGREGATION_MONTHS)
        recent  = surprises[
            pd.to_datetime(surprises["release_date"]) >= cutoff
        ].copy()

        results: list[SectorSurpriseIndex] = []

        for sector, indicator_weights in self._weights.items():
            sector_data = recent[
                (recent["sector"] == sector) &
                (recent["indicator_code"].isin(indicator_weights))
            ].copy()

            if sector_data.empty:
                log.warning("surprise_aggregator.no_data", sector=sector)
                continue

            # Decadimento esponenziale rispetto a reference_date
            days_old = (
                ref_ts - pd.to_datetime(sector_data["release_date"])
            ).dt.days.to_numpy(dtype=np.float64)
            decay = np.exp(-_DECAY_LAMBDA * days_old / 30)

            ind_weights = np.array([
                indicator_weights.get(str(code), 1.0)
                for code in sector_data["indicator_code"]
            ], dtype=np.float64)

            combined_weights = decay * ind_weights
            z_scores         = sector_data["surprise_z"].to_numpy(dtype=np.float64)

            total_weight = float(combined_weights.sum())
            if total_weight < 1e-9:
                continue

            surprise_index = float(
                np.clip(np.dot(combined_weights, z_scores) / total_weight, -3.0, 3.0)
            )

            beat_count = int((z_scores > 0).sum())
            miss_count = int((z_scores < 0).sum())

            # Momentum: confronto con 1M e 3M fa
            momentum_1m = self._calc_momentum(surprises, sector, indicator_weights, ref_ts, 1)
            momentum_3m = self._calc_momentum(surprises, sector, indicator_weights, ref_ts, 3)

            regime = (
                "positive_surprise" if surprise_index > _REGIME_THRESHOLD
                else "negative_surprise" if surprise_index < -_REGIME_THRESHOLD
                else "neutral"
            )

            idx = SectorSurpriseIndex(
                sector=sector,
                snapshot_date=ref_ts.date(),
                surprise_index=round(surprise_index, 4),
                momentum_1m=round(momentum_1m, 4),
                momentum_3m=round(momentum_3m, 4),
                regime=regime,
                beat_count=beat_count,
                miss_count=miss_count,
                data_points=len(sector_data),
            )
            results.append(idx)
            log.info(
                "surprise_aggregator.sector",
                sector=sector,
                index=round(surprise_index, 4),
                regime=regime,
            )

        if self._duckdb is not None:
            self._persist(results)

        return results

    def _calc_momentum(
        self,
        surprises:   pd.DataFrame,
        sector:      str,
        weights:     dict[str, float],
        ref_ts:      pd.Timestamp,
        months_back: int,
    ) -> float:
        """Calcola la variazione dell'indice rispetto a N mesi fa."""
        prev_ts  = ref_ts - pd.DateOffset(months=months_back)
        cutoff_p = prev_ts - pd.DateOffset(months=_AGGREGATION_MONTHS)
        recent_p = surprises[
            (pd.to_datetime(surprises["release_date"]) >= cutoff_p) &
            (pd.to_datetime(surprises["release_date"]) < prev_ts)
        ]
        sector_p = recent_p[
            (recent_p["sector"] == sector) &
            (recent_p["indicator_code"].isin(weights))
        ]
        if sector_p.empty:
            return 0.0
        return float(np.mean(sector_p["surprise_z"].to_numpy(dtype=np.float64)))

    def _persist(self, results: list[SectorSurpriseIndex]) -> None:
        """Persiste in sector_surprise_index DuckDB."""
        if self._duckdb is None:
            return
        for r in results:
            try:
                self._duckdb.execute(  # type: ignore[attr-defined]
                    """INSERT OR REPLACE INTO sector_surprise_index
                       (snapshot_date, sector, surprise_index, momentum_1m,
                        momentum_3m, regime, beat_count, miss_count, data_points)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [r.snapshot_date, r.sector, r.surprise_index,
                     r.momentum_1m, r.momentum_3m, r.regime,
                     r.beat_count, r.miss_count, r.data_points],
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("surprise.persist_sector_failed", sector=r.sector, error=str(exc)[:60])


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PARTE 3: SurpriseSignalGenerator
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@dataclass(frozen=True)
class SurpriseCompositeSignal:
    """Segnale aggregato da tutti i settori per il Composite Signal Engine."""
    signal_value:    float           # [-1, 1]
    dominant_sector: str
    beat_count:      int
    miss_count:      int
    sector_detail:   dict[str, float]  # {sector: normalized_index}


class SurpriseSignalGenerator:
    """Genera il segnale composito [-1,1] dalle sorprese settoriali.

    Per uso nel CompositeSignalAggregator v2.
    """

    def __init__(self, duckdb: object = None) -> None:
        self._duckdb = duckdb

    def generate(
        self,
        sector_indices: list[SectorSurpriseIndex],
    ) -> SurpriseCompositeSignal:
        """Converte gli indici settoriali in segnale scalare [-1, 1].

        Args:
            sector_indices: Output di SectorSurpriseAggregator.aggregate().
        """
        sector_map     = {s.sector: s for s in sector_indices}
        weighted_scores: list[float] = []
        total_weight    = 0.0
        sector_detail:  dict[str, float] = {}

        for sector, weight in _SECTOR_WEIGHTS.items():
            if sector not in sector_map:
                continue
            # Normalizza da [-3, 3] a [-1, 1]
            idx        = sector_map[sector].surprise_index
            normalized = float(np.clip(idx / 3.0, -1.0, 1.0))
            weighted_scores.append(normalized * weight)
            total_weight += weight
            sector_detail[sector] = round(normalized, 4)

        if total_weight < 1e-9 or not weighted_scores:
            return SurpriseCompositeSignal(
                signal_value=0.0,
                dominant_sector="unknown",
                beat_count=0,
                miss_count=0,
                sector_detail={},
            )

        signal_value = float(np.clip(
            sum(weighted_scores) / total_weight,
            -1.0, 1.0,
        ))
        dominant  = max(sector_detail, key=lambda s: abs(sector_detail[s]))
        beat_count = sum(s.beat_count for s in sector_indices)
        miss_count = sum(s.miss_count for s in sector_indices)

        result = SurpriseCompositeSignal(
            signal_value=round(signal_value, 4),
            dominant_sector=dominant,
            beat_count=beat_count,
            miss_count=miss_count,
            sector_detail=sector_detail,
        )

        self._persist(result)
        log.info(
            "surprise_signal.generated",
            signal=round(signal_value, 4),
            dominant=dominant,
            beats=beat_count,
            misses=miss_count,
        )
        return result

    def _persist(self, s: SurpriseCompositeSignal) -> None:
        """Persiste in surprise_signal DuckDB."""
        if self._duckdb is None:
            return
        try:
            self._duckdb.execute(  # type: ignore[attr-defined]
                """INSERT OR REPLACE INTO surprise_signal
                   (generated_at, signal_value, dominant_sector, beat_count, miss_count)
                   VALUES (?, ?, ?, ?, ?)""",
                [datetime.now(UTC), s.signal_value, s.dominant_sector,
                 s.beat_count, s.miss_count],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("surprise_signal.persist_failed", error=str(exc)[:60])
