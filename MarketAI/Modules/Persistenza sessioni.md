
# Persistenza Sessioni

**Introdotto in:** v15 – UI Native (Sessione 3)  
**File sorgente:** `personal/user_preferences/`  
**Stato:** Salvataggio e ricaricamento di configurazioni e preferenze

## Panoramica

Il sistema di persistenza di MarketAI salva le configurazioni delle analisi (simbolo, modello, orizzonte, date, feature flags) e le preferenze UI dell'utente in un database SQLite dedicato (`db/user_sessions.db`). Questo permette di riprendere il lavoro esattamente da dove lo si era interrotto, senza dover riconfigurare manualmente ogni parametro.

## Database

**File:** `db/user_sessions.db` (SQLite separato dal database principale)

**Tabelle:**
- `analysis_sessions` – configurazioni di analisi salvate
- `user_preferences` – preferenze UI (tema, pagina default, simbolo default, etc.)
- `model_metrics` – metriche storiche per il drift detection (v15)

### Schema `analysis_sessions`

| Colonna | Tipo | Descrizione |
|---------|------|-------------|
| `session_id` | TEXT (PK) | UUID generato automaticamente |
| `name` | TEXT | Nome personalizzato dall'utente |
| `symbol` | TEXT | Simbolo analizzato (es. AAPL) |
| `start_date` | TEXT | Data inizio (YYYY-MM-DD) |
| `end_date` | TEXT | Data fine (YYYY-MM-DD) |
| `model_name` | TEXT | Modello utilizzato |
| `horizon_days` | INTEGER | Orizzonte di previsione (giorni) |
| `auto_features` | INTEGER | 0/1 (feature automatiche abilitate) |
| `created_at` | TEXT | ISO timestamp creazione |
| `last_used_at` | TEXT | ISO timestamp ultimo utilizzo |
| `notes` | TEXT | Note personali |

### Schema `user_preferences`

| Colonna | Tipo | Descrizione |
|---------|------|-------------|
| `key` | TEXT (PK) | Nome della preferenza |
| `value` | TEXT | Valore (sempre stringa) |
| `updated_at` | TEXT | ISO timestamp ultimo aggiornamento |

**Preferenze supportate:**
```yaml
theme: dark                    # "dark" | "light"
default_page: E1               # Pagina di apertura
default_symbol: SPY
default_horizon: 30
language: it                   # "it" | "en"
auto_refresh_seconds: 900
show_data_quality_badge: true