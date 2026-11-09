# Vinyl Price Check — 0.1

Web app mobile in italiano, FastAPI + HTML/CSS/JavaScript. La lettura foto utilizza Tesseract.js 7 caricato su richiesta. Nessuna registrazione o credenziale chiesta ai visitatori. Nessun prezzo dimostrativo nel prodotto.

## Avvio

Python 3.12 consigliato:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DISCOGS_TOKEN='inserisci-solo-nel-tuo-ambiente-server'
uvicorn app.main:app --reload
```

Aprire http://127.0.0.1:8000. Su Windows PowerShell attivare `.venv\Scripts\Activate.ps1` e impostare `$env:DISCOGS_TOKEN` invece di `export`. Il file `.env.example` documenta le variabili: `.env` NON viene caricato automaticamente. Nessuna credenziale è inclusa nel progetto.

## Pubblicazione Render gratuita

Il progetto è nella sottocartella `vinyl-price-check` del ramo dedicato `vinyl-price-check` in `Robb283/VINILI--app`. Il ramo principale è indipendente.

- Runtime: Python; region: Frankfurt; plan: Free.
- Branch: `vinyl-price-check`.
- Build: `pip install -r vinyl-price-check/requirements.txt`.
- Start: `cd vinyl-price-check && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`.
- Health check: `/api/health`.
- Secret server: `DISCOGS_TOKEN`.
- `ENABLE_MARKET_DATA=false` per il rilascio iniziale; vedere condizioni sotto.

Il `render.yaml` è previsto per usare la cartella del progetto come root quando viene spostato in un repository autonomo. Non richiede database o servizi a pagamento. Il piano gratuito si sospende dopo 15 minuti di inattività; al primo accesso può servire circa un minuto. Limiti e disponibilità del piano dipendono da Render.

## Fonti e limiti verificati il 9 novembre 2026

Documentazione ufficiale: https://www.discogs.com/developers

Condizioni: https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use

Hosting: https://render.com/docs/deploy-fastapi e https://render.com/docs/free

- `/database/search`: catalogo delle edizioni, ricerca autenticata con token del gestore. Solo vinile, paginazione, paese/catalogo facoltativi. Il filtro Reissue seleziona il flag presente nella pagina corrente. “Prima stampa” è un avviso di verifica, non una certificazione automatica.
- `/releases/{id}`: verifica il formato prima di valutare.
- `/marketplace/stats/{id}?curr_abbr=EUR`: minimo delle offerte attive e numero di copie in vendita. Non sono prezzi di transazioni concluse. Test HTTP reale senza autenticazione: risposta 200 su release 249504 il 9 novembre 2026; valori dinamici non salvati nel prodotto.
- `/marketplace/price_suggestions/{id}`: suggerimenti per condizione; richiede autenticazione e impostazioni venditore completate. La valuta è quella di vendita dell’account: l’app usa solo EUR, senza conversioni implicite. Test senza credenziali: 401, correttamente gestito.
- L’API documentata consultata non fornisce un endpoint generale dello storico transazioni con minimo/mediana/massimo delle vendite. Non ricaviamo questi dati con scraping o endpoint non documentati.

I dati del Marketplace (prezzi, suggerimenti, storico) sono Restricted Data nei termini Discogs. I termini consentono applicazioni con limitazioni, vietano usi commerciali dei Restricted Data e la loro cessione a terzi, impongono attribuzione e una freschezza massima di sei ore. Questo NON equivale a un’autorizzazione certa per un servizio pubblico di valutazione: prima di attivare `ENABLE_MARKET_DATA=true` sul servizio pubblico va chiarita con Discogs la liceità dello specifico uso e ottenuta l’eventuale autorizzazione. Nessuna richiesta a Discogs viene inviata automaticamente.

Il gate è esplicito e disattivato per impostazione predefinita. Il catalogo resta utilizzabile con token valido. La pubblicazione iniziale può quindi identificare le edizioni ma mostrare “Non valutabile” per i prezzi: non va descritta come valutatore già completo.

## Metodo

L’utente conferma esplicitamente l’edizione. Con condizione nota e suggerimento EUR disponibile: prezzo richiesto inferiore all’80% → Conveniente; superiore al 120% → Troppo alto; altrimenti Corretto. Soglie applicative dichiarate; affidabilità sempre bassa, perché mancano vendite comparabili, copertina, autenticità e spese. L’app non attribuisce una probabilità statistica inventata.

Un suggerimento è un singolo riferimento: `market_value_range` resta null. Gli estremi tra suggerimenti per condizioni diverse sono eventualmente mostrati separatamente come tali. Nessun ±20% viene spacciato per intervallo di mercato. Per una forchetta attendibile della singola copia servono dati comparabili autorizzati aggiuntivi.

## Sicurezza e operatività

Credenziali solo nell’ambiente server, mai nel client o nel repository. Richieste solo a percorsi API Discogs fissi; nessun URL arbitrario dal visitatore. Validazione Pydantic, prezzi finiti positivi, output UI tramite textContent, CSP, no-store. Cache volatile fino a 5 minuti e 256 elementi; al massimo una richiesta upstream ogni 2,5 secondi. Limite globale 20 richieste API/minuto per istanza. Usare un solo worker. Il limite globale protegge il budget, ma per un lancio più ampio serviranno limiti per visitatore e protezione dagli abusi all’ingresso. Non vengono salvati record di ricerca. Il provider può conservare log tecnici e indirizzi IP secondo le sue policy.

## Verifica

```sh
pip install -r requirements-dev.txt
python -m pytest tests -q
```

I test usano fixture sintetiche esplicite solo nel codice di test, mai servite al pubblico. Coprono soglie, assenza prezzi, condizioni mancanti, valute, valori non validi, release bloccate, gate mercato, fallback errori e filtro ristampe. I test non dimostrano che un token specifico funzioni o che Discogs autorizzi la pubblicazione dei dati.

## Prossimi passi

1. Verificare ricerca autenticata e accessibilità dei suggerimenti con account gestore configurato in EUR.
2. Chiarire con Discogs i diritti del servizio pubblico per Restricted Data.
3. Provare edizioni reali confrontando etichetta, catalogo e matrici.
4. Integrare solo dati comparabili autorizzati prima di aggiungere un vero intervallo di valore e affidabilità superiore.

## Stato della pubblicazione

- App: https://vinyl-price-check.onrender.com
- Render service: `srv-dbotboe7bikc73a7lr4g`, workspace `tea-dbot87ec6qcc738memt0`.
- Repository: https://github.com/Robb283/VINILI--app/tree/vinyl-price-check/vinyl-price-check
- Ricerca: attiva con credenziale custodita nell’ambiente Render.
- Mercato pubblico: disattivato. La revisione automatica ha rifiutato l’attivazione persistente dei dati di mercato pubblici finché i diritti d’uso non sono chiariti. Nessuna modifica alternativa aggira il blocco.
- Test automatici: 19 passati anche in ambiente pulito con le versioni di requirements.txt.
- Prove reali locali autenticate del 9 novembre 2026: Animals (release 768254) e Abbey Road (7950925) restituiscono suggerimenti EUR; Nevermind test pressing (22528703) non ha suggerimenti e produce Non valutabile. Le selezioni automatiche in questi smoke test verificano il flusso tecnico e non certificano un’edizione fisica.
- Per ripetere il controllo live, da root progetto: `PYTHONPATH=. python tests/live_check.py`. Il token viene richiesto senza eco e non salvato. I dati di prezzo dinamici non sono inclusi nel repository.

## Versione 0.2 — ricerca rapida e foto

Due soli campi principali: nome del disco (artista e album insieme) e prezzo. Condizioni, paese, tipo di stampa e catalogo restano facoltativi e chiusi inizialmente. L’API accetta anche `q`, preservando la compatibilità con i vecchi parametri artist/title.

Foto: acquisizione da fotocamera o galleria, JPG/PNG/WebP entro 15 MB, lettura OCR locale con Tesseract.js 7.0.0. Il motore, il worker e il modello inglese vengono scaricati da jsDelivr solo quando si sceglie una foto. Il CDN può osservare i download tecnici, ma il codice non trasmette la foto: immagine e canvas rimangono nel browser. Alla ricerca vengono inviati solo il testo confermato e i filtri del modulo. Supporto HEIC non incluso. L’OCR legge le scritte, non riconosce l’immagine della copertina: i risultati sono candidati da confermare e non certificano la stampa. Il testo letto si può correggere o ricomporre scegliendo le righe con artista e titolo. Per copertine astratte o scritte difficili resta disponibile il campo manuale.

Il riconoscimento visivo generale, distinto dall’OCR, richiederebbe un modello multimodale o un catalogo di immagini: non è implementato né dichiarato funzionante in questa versione. Le condizioni del disco non sono dedotte dalla foto della copertina.

Il gate dei dati di mercato pubblici resta disattivato come nel rilascio precedente. Questa modifica non lo aggira.

Verifica 0.2: 20 test backend passati. Prova browser sul servizio Render: una foto di prova con scritte Terry Allen / Lubbock viene letta realmente dall’OCR; selezionando artista e titolo la ricerca restituisce sei edizioni su Discogs. Le prime due righe lette sono proposte automaticamente, le altre sono selezionabili. La prova verifica la lettura del testo e la ricerca, non un riconoscimento visivo generale o la correttezza di una stampa fisica. I test non attivano il gate dei dati di mercato pubblici.

## Versione 0.3 — confronto per condizioni

Il risultato comprende tre riferimenti indipendenti: Usurato (G), Buono (VG+), Ottimo (NM). Per ciascuno il prezzo suggerito da Discogs viene confrontato con quello richiesto, anche senza compilare le condizioni prima della ricerca. Le tre cifre non sono derivate dal minimo delle offerte o da percentuali inventate. Un suggerimento mancante resta Non valutabile. Affidabilità bassa e soglie applicative esplicite.

L’attivazione pubblica è stata nuovamente rifiutata dalla revisione automatica: richiede un’autorizzazione esplicita alla pubblicazione dei dati di mercato dopo l’indicazione delle restrizioni d’uso. Il flag ENABLE_MARKET_DATA resta false. Il codice di confronto è pronto e verificabile, senza aggirare quel blocco.
