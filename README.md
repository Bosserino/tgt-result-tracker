# TGT Result Tracker

Landing con i risultati VGC (Masters) del team ai Regional, International e Worlds
da Danzica 2027 in poi, con i 6 sprite del menù di Pokémon Champions scaricabili.

- `config.json` — giocatori e data di partenza (`since`). Aggiungi/togli nomi qui.
- `update.py` — legge Pokedata (lista eventi, standings JSON, roster JSON), calcola
  record / piazzamento / top, scarica gli sprite Champions da PokeAPI in `site/sprites/`
  e scrive `site/data.json`. Solo libreria standard Python.
- `site/` — la landing statica (`index.html` + `data.json` + `sprites/`). La pagina
  rilegge `data.json` ogni 5 minuti.
- `cache/` — forme Pokémon risolte ed eventi conclusi (non vengono riscaricati).

## Aggiornamento automatico

`.github/workflows/update.yml` esegue `update.py` ogni 30 minuti, committa le novità
e pubblica `site/` su GitHub Pages. Per attivarlo: crea un repo GitHub, fai push,
e in *Settings → Pages* scegli **Source: GitHub Actions**.

## In locale

```bash
python3 update.py
python3 -m http.server 8765 --directory site
```

Poi apri http://localhost:8765.
