# UI Components - Libreria di Componenti v8.2.0

Tutti i componenti UI estendono `BaseComponent` (ABC). Il metodo `to_html()` è puro e testabile senza Streamlit; il metodo `render()` è `# pragma: no cover` e chiama gli internals di Streamlit[reference:33].

## Componenti Disponibili

### KpiCard
Visualizza una metrica con delta opzionale e indicatore di qualità.
```python
from presentation.ui.components.kpi_card import KpiCard

card = KpiCard(
    title="Sharpe Ratio",
    value=1.42,
    unit="",
    delta=0.15,
    delta_label="vs 1y",
    quality_flag="ok",  # "ok" | "low_ic" | "insufficient_data"
    icon="",
    tooltip="Risk-adjusted return",
)
card.render()  # Streamlit
html = card.to_html()  # HTML puro per test