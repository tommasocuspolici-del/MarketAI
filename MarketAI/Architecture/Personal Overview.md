# Personal Layer – Gestione Finanze Personali

**Introdotto in:** v10 (Architettura base)  
**File principali:** `personal/` (intera cartella)  
**Stato:** Modulo di pianificazione finanziaria integrato

## Panoramica

Il **Personal Layer** è il modulo che si occupa della gestione delle finanze personali dell'utente. Fornisce strumenti per:

- **Profilo investitore** – definizione di tolleranza al rischio, orizzonte temporale, obiettivi.
- **Cash flow** – proiezioni di entrate/uscite a 12 mesi.
- **Patrimonio netto** – tracciamento di attività e passività nel tempo.
- **Obiettivi SMART** – definizione e verifica di fattibilità.
- **Tassazione** – regime italiano (26% capital gains, 12.5% titoli di stato).
- **Simulazioni Monte Carlo** – valutazione della probabilità di successo di un piano.
- **FIRE calculator** – stima dell'età di pensionamento.

Il Personal Layer comunica con l'**Engine Layer** esclusivamente tramite il [[Bridge Overview|Bridge]], che definisce i contratti API per lo scambio di dati.

```mermaid
graph TB
    subgraph Personal[Personal Layer]
        IP[Investor Profile<br/>Regola 22 - filtro suggerimenti]
        CF[Cash Flow<br/>proiezioni 12 mesi]
        NW[Net Worth<br/>attività/passività]
        G[Goals<br/>SMART + feasibility]
        T[Tax<br/>regime italiano]
        WS[Wealth Scenarios<br/>Monte Carlo 10k]
        FIRE[FIRE Calculator<br/>età pensionamento]
    end
    
    Bridge[Bridge<br/>api_contracts.py] -.-> Personal
    Personal -.-> UI[Dashboard Personal<br/>P1, P2, P3, M3]