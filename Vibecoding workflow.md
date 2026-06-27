# Contratti API tra Engine e Personal

Il Bridge definisce i contratti di comunicazione (dataclass / modelli Pydantic) utilizzati per lo scambio di dati tra il layer Engine (previsioni, dati) e il layer Personal (utenti, strategie, UI). Questi contratti garantiscono l'integrità dei dati e facilitano lo sviluppo separato dei due layer.

## Modelli Principali

### `PredictionRequest`
Richiesta di previsione inoltrata dal Personal all'Engine.
python
class PredictionRequest(BaseModel):
    symbol: str          # Ticker dell'asset (es. "AAPL")
    horizon: int = 30    # Numero di giorni di previsione
    model_type: str = "ensemble"  # "nbeats", "tft", "quantile", "ensemble"
    quantiles: List[float] = [0.1, 0.5, 0.9]  # quantili richiesti
    include_history: bool = True  # se includere i dati storici nella risposta
### `PredictionResponse`

Risposta dall'Engine al Personal.

python
class PredictionResponse(BaseModel):
    symbol: str
    horizon: int
    predictions: Dict[str, Any]   # chiavi: "mean", "quantiles", "std"
    history: Optional[pd.DataFrame] = None  # dati storici (se richiesti)
    model_version: str            # versione del modello utilizzato
    timestamp: datetime
### `UserProfile`

Profilo utente gestito dal Personal e utilizzato per personalizzare le strategie.
python
class UserProfile(BaseModel):
    user_id: str
    risk_tolerance: float  # 0-1
    preferred_assets: List[str]
    strategy_code: Optional[str] = None  # script personalizzato

### `BacktestRequest`
Richiesta di backtesting di una strategia.
python
class BacktestRequest(BaseModel):
    symbol: str
    start_date: date
    end_date: date
    initial_capital: float = 10000.0
    strategy: str  # nome della strategia o codice serializzato
### `BacktestResult`
Risultato del backtest.
python
class BacktestResult(BaseModel):
    final_value: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    trades: List[Dict[str, Any]]

###Utilizzo

- I modelli sono definiti in `bridge/api_contracts.py` e importati sia da Engine che da Personal.
    
- La serializzazione avviene tramite JSON (FastAPI) o pickle (per scambi interni).
    
- Eventuali modifiche a questi contratti richiedono un aggiornamento di versione e il coordinamento tra i team (documentato in `Versioning and Dependencies.md`).
    
## Collegamenti

- [Architecture/Bridge Layer.md](https://../Architecture/Bridge%2520Layer.md)
    
- [Versioning and Dependencies.md](https://../Versioning%2520and%2520Dependencies.md)