# zulunation.it — nuovo sito

Sito statico di **Universal Zulu Nation Italia** che importa in automatico tutti i contenuti dal blog Blogger
[zulunationitalia.blogspot.com](https://zulunationitalia.blogspot.com).

## Come funziona

1. **Importazione** (`scripts/sync.py`): legge dal feed di Blogger l'elenco di articoli e pagine, scarica il testo
   completo di ognuno e tutte le immagini. Le immagini vengono salvate in `assets/img/` (WebP, max 1600 px) e nel testo
   gli indirizzi vengono sostituiti con le copie locali. I link interni al vecchio blog diventano link del nuovo sito.
2. **Generazione** (`scripts/build.py`): crea il sito in `_site/` — home, articoli, sezioni per etichetta, archivio per
   anno e mese, ricerca, feed RSS (`/feed.xml`), sitemap.
3. **Automatismo** (`.github/workflows/sync-deploy.yml`): ogni 3 ore GitHub Actions ripete l'importazione, salva le
   novità nel repository e ripubblica il sito su GitHub Pages. Si scrive su Blogger come sempre: il sito si aggiorna da solo.

Gli indirizzi degli articoli sono identici a quelli di Blogger (`/2026/10/titolo.html`, `/p/contatti.html`),
quindi i vecchi link condivisi continuano a funzionare dopo il cambio di dominio. Anche `/search/label/Nome` reindirizza
alla nuova sezione.

## Configurazione

Tutto in `site.json`: titolo, menu (`nav`), sezioni della home (`home_sections`), riquadro "Diventa membro" (`cta`),
social, dimensione e qualità delle immagini.

## Forzare un aggiornamento

GitHub → **Actions** → *Importa dal blog e pubblica* → **Run workflow**. Spunta "Rileggi tutti gli articoli" per
reimportare anche gli articoli già presenti (utile dopo aver modificato le regole di pulizia del testo).

## Passare a www.zulunation.it

1. In `site.json` imposta `"custom_domain": "www.zulunation.it"` e fai commit.
2. GitHub → **Settings → Pages → Custom domain**: scrivi `www.zulunation.it` e salva.
3. Su Aruba, nella gestione DNS del dominio, al posto del forward:
   - record **CNAME** `www` → `mastafive.github.io`
   - per il dominio senza www, record **A** `@` verso `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`
4. Quando GitHub ha verificato il dominio, attiva **Enforce HTTPS** nella stessa pagina.

## In locale

```bash
pip install -r requirements.txt
python scripts/sync.py        # importa (incrementale)
python scripts/build.py       # genera _site/
python -m http.server -d _site 8000
```
