
# Config Files – File di Configurazione MarketAI

**Introdotto in:** v10 (Architettura base)  
**Cartella:** `config/`  
**Stato:** Centralizzazione di tutti i parametri di sistema

## Panoramica

MarketAI utilizza file YAML per la configurazione di tutti i parametri di sistema, separando la logica di business dalla configurazione operativa. Questo permette di modificare il comportamento del sistema senza toccare il codice sorgente.

## Struttura
config/  
├── data_sources.yaml # Provider e sorgenti dati  
├── rate_limits.yaml # Limiti per API esterne  
├── cache.yaml # TTL e parametri cache  
├── backtesting.yaml # Configurazione costi e slippage  
├── feature_flags.yaml # Abilitazione/disabilitazione moduli  
├── logging.yaml # Livelli e rotazione log  
└── ui_config.json # Preferenze UI (generato a runtime, in %LOCALAPPDATA%)

text

## File principali
### `data_sources.yaml`
providers:
  yfinance:
    enabled: true
    priority: 1
    cache_ttl_seconds: 900
  alpha_vantage:
    enabled: true
    priority: 2
    cache_ttl_seconds: 900
    rate_limit_rpm: 5
  finnhub:
    enabled: true
    priority: 3
    cache_ttl_seconds: 1800
    requires_api_key: true

### `rate_limits.yaml`

yaml

alpha_vantage:
  requests_per_minute: 5
  requests_per_day: 500
finnhub:
  requests_per_minute: 30
  requests_per_day: 1000
yahoo_finance:
  requests_per_minute: 60
  requests_per_day: 10000

### `cache.yaml`

yaml

cache:
  ttl_seconds: 900           # 15 minuti
  max_size_mb: 512           # Max dimensione cache
  enable_fallback: true      # Usa cache anche se scaduta
  fallback_ttl_seconds: 3600 # 1 ora per fallback

### `backtesting.yaml`

yaml

costs:
  commission_type: "percentage"   # "fixed" | "percentage"
  commission_value: 0.001         # 0.1% (minimo Regola 23)
  slippage_type: "volatility"     # "fixed" | "volatility"
  slippage_vol_multiplier: 0.5
  min_commission: 1.0
  max_volume_fraction: 0.05       # Max 5% volume giornaliero

### `feature_flags.yaml`

yaml

# Modelli sperimentali (default: false)
nbeats_model: false              # v14 – RAM heavy
lstm: false                      # Legacy
gpu_acceleration: false          # ROCm non stabile su Windows
# Modelli stabili (default: true)
realistic_backtester: true       # v14
auto_feature_engineering: true   # v13
ensemble_predictor: true         # v13
# API e UI
fastapi_backend: false           # Avvio manuale (v14)
pywebview_enabled: true          # v15

### `logging.yaml`

yaml

logging:
  level: "INFO"
  format: "json"                 # "json" | "text"
  rotation:
    max_size_mb: 20
    backups: 5
  separate_errors: true
  error_logs:
    api: "logs/api_errors.log"
    db: "logs/db_errors.log"

### `ui_config.json` (generato a runtime in `%LOCALAPPDATA%\MarketAI\`)

json

{
  "project_path": "C:\\Users\\...\\AppData\\Roaming\\MarketAI",
  "backup_path": "C:\\Users\\...\\AppData\\Local\\MarketAI\\backups",
  "github_remote": "origin",
  "github_branch": "main",
  "test_preset": "Fast",
  "theme": "dark",
  "default_symbol": "SPY",
  "default_horizon": "30"
}

## Caricamento delle configurazioni

- **YAML:** `shared/config_loader.py` – carica e valida i file YAML con Pydantic.
    
- **JSON:** `management_ui.py` – gestisce `ui_config.json` per preferenze UI.
    
- **Environment (.env):** `os.getenv()` per API key e path di sistema.
    

**Regola:** Non hardcodare mai valori di configurazione nel codice sorgente.

Collegamenti
- [[Architecture Overview]]
    
- [[Shared Overview]]
    
