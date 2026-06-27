# Bridge – Contratti API e Comunicazione tra Layer

**Introdotto in:** v10 (Architettura base)  
**File principale:** `bridge/api_contracts.py`  
**Stato:** Nucleo dell'architettura (deve rimanere stabile)

## Panoramica

Il **Bridge** è il livello che definisce e gestisce la comunicazione tra l'**Engine Layer** (analisi quantitativa di mercato) e il **Personal Layer** (finanze personali). Non esegue logica di business, ma espone esclusivamente **contratti API** (dataclass / Pydantic models) che garantiscono che i due layer parlino lo stesso linguaggio.

Il Bridge è posizionato al centro dell'architettura:

```mermaid
graph LR
    E[Engine Layer] -->|calcola| B[Bridge<br/>api_contracts.py]
    P[Personal Layer] -->|consume| B
    B -->|fornisce dati aggregati| P
    B -->|fornisce profilo/obiettivi| E