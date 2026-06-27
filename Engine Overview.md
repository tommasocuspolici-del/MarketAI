# FastAPI Backend - Endpoint di Previsione

Il backend FastAPI espone un'API REST per interagire con il motore di previsione. È il punto di ingresso principale per le richieste esterne (UI, client, integrazioni).

## Endpoint Principali

### `POST /predict`
Richiede una previsione per un asset.

**Request Body** (JSON):
json
{
  "symbol": "AAPL",
  "horizon": 30,
  "model_type": "ensemble",
  "quantiles": [0.1, 0.5, 0.9],
  "include_history": true
}

Tutti i campi sono opzionali eccetto `symbol`. I valori di default sono definiti nel contratto.
**Response** (200 OK):
json
{
  "symbol": "AAPL",
  "horizon": 30,
  "predictions": {
    "mean": [153.4, 154.5, ...],
    "quantiles": {
      "0.1": [150.2, 151.3, ...],
      "0.5": [153.4, 154.5, ...],
      "0.9": [156.7, 158.0, ...]
    },
    "std": [2.1, 2.3, ...]
  },
  "history": [{"date": "2025-01-01", "close": 150.0}, ...],
  "model_version": "v1.2.3",
  "timestamp": "2025-03-01T10:00:00Z"
}

**Errori**:

- `400 Bad Request`: simbolo non valido o orizzonte fuori range.
    
- `404 Not Found`: se il simbolo non è supportato.
    
- `503 Service Unavailable`: se tutti i provider di dati sono offline.
    

### `GET /health`

Check di salute del servizio. Restituisce `{"status": "ok"}`.

### `GET /metrics` (solo per admin)

Restituisce metriche di performance (numero di richieste, tempi di risposta, etc.) in formato Prometheus.

## Autenticazione

Per le versioni future, l'endpoint `/predict` sarà protetto da un token JWT. Attualmente, in modalità sviluppo, l'autenticazione è disabilitata (configurabile tramite `app_config.yaml`).

## Implementazione

- Il controller chiama il servizio `PredictionService` che interagisce con l'Engine.
    
- La logica di caching e throttling è gestita a livello di middleware.
    
- La documentazione interattiva è disponibile su `/docs` (Swagger UI).
    

## Esempio di Chiamata con `curl`

bash

curl -X POST "http://localhost:8000/predict" \
     -H "Content-Type: application/json" \
     -d '{"symbol":"AAPL","horizon":10}'

