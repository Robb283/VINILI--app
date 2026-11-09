# First Press — guide aux premières éditions / guida alle prime stampe

Versione 0.4. La web app precedentemente chiamata Vinyl Price Check ora si concentra sull’individuazione delle prime stampe. Inserisci artista e titolo in un campo, o leggi il testo di una foto, e ottieni una guida con etichetta, catalogo, anno, paese, matrici e note distintive. Il paese è facoltativo. Il prezzo è secondario e compare solo se disponibile e attivato dal gestore.

## Utilizzo

App: https://vinyl-price-check.onrender.com

1. Scrivi artista e album, oppure scegli una foto JPG/PNG/WebP con testo leggibile.
2. Facoltativamente scegli il paese: prima uscita mondiale e prima edizione italiana/americana sono ambiti diversi.
3. La ricerca propone un album Discogs e carica direttamente una guida alle candidate più precoci. Si può cambiare album se il risultato proposto è sbagliato.
4. Confronta etichette, indirizzi, catalogo, note e matrici con il disco del commerciante. Puoi aprire altre edizioni per controllare le differenze.

Il solo anno, lo stesso numero di catalogo o l’assenza del flag Reissue non certificano una prima tiratura. Varianti dello stesso anno possono avere copertine o incisioni diverse. L’app non certifica autenticità e non deduce lo stato del vinile dalla copertina.

## Dati e limiti

- Fonti: API documentate Discogs `/database/search` (master), `/masters/{id}`, `/masters/{id}/versions`, `/releases/{id}`.
- Versioni filtrate per Vinyl e paese facoltativo, richieste in ordine di data crescente. Massimo 3 pagine da 50. Una ricerca troncata è indicata come parziale; mostriamo fino a 30 alternative oltre alla candidata proposta.
- Le date sconosciute non vengono inventate. Tra le versioni datate vengono proposte quelle più precoci non marcate Reissue/Repress/Promo/Test Pressing/Unofficial/Acetate. Questi criteri selezionano candidate, non provano la prima tiratura.
- Il main_release del master non è assunto come prima stampa. L’anno del master può riferirsi a formati diversi dal vinile.
- Notes e identificativi sono riprodotti con attribuzione e link alla release. Le note sono contributi degli utenti Discogs; è necessaria la verifica sulla copia.
- L’OCR Tesseract.js 7 legge scritte nel browser. Non è un riconoscitore visivo di copertine senza testo. Foto e canvas non vengono inviati al server. Il motore, worker e modello inglese sono scaricati da jsDelivr; al CDN sono visibili i download tecnici, non la foto. HEIC non incluso. La proposta di testo è correggibile.

## Prezzo facoltativo

`ENABLE_MARKET_DATA` resta `false` sul servizio attuale. Non è un requisito per utilizzare la guida. Non viene richiesto alcun prezzo di acquisto e non c’è più un verdetto economico. Le vecchie route di valutazione `/api/assess` e ricerca release `/api/search` sono rimosse.

Se e quando l’uso pubblico viene autorizzato e la funzione attivata, il dettaglio può leggere suggerimenti Discogs in EUR per VG, VG+ e NM. Gli estremi sono dichiarati come suggerimenti per condizioni diverse, non come minimo/mediana/massimo delle vendite concluse. Dati mancanti, valute diverse o API non accessibili producono fascia non disponibile senza interrompere la guida. Non sono presenti prezzi simulati.

La revisione automatica aveva rifiutato l’esposizione pubblica dei dati di mercato in attesa di autorizzazione specifica. Questo nuovo flusso non aggira quel blocco.

Termini e documentazione consultati: https://www.discogs.com/developers e https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use . Il catalogo testuale e gli identificativi sono distinti dai dati Marketplace soggetti a restrizioni. La pagina mantiene le attribuzioni richieste.

## Avvio e test

Python 3.12. Da questa cartella:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DISCOGS_TOKEN='solo-nell-ambiente-server'
uvicorn app.main:app --reload
```

Su PowerShell: `.venv\Scripts\Activate.ps1` e `$env:DISCOGS_TOKEN`. Il file `.env.example` documenta le variabili; non viene caricato automaticamente. Nessuna credenziale è salvata nei file.

```sh
pip install -r requirements-dev.txt
python -m pytest tests -q
```

I test verificano date mancanti, selezione di candidate, repress coeve, preservazione di note/matrici, ricerca parziale, filtro paese, errori e assenza di chiamate Marketplace quando disattivate. Le fixture sintetiche restano nei test e non sono servite nell’app.

## Continuità e pubblicazione

Repository: https://github.com/Robb283/VINILI--app/tree/vinyl-price-check/vinyl-price-check . Il ramo principale resta indipendente. Le versioni precedenti sono conservate nella cronologia Git.

Render: servizio `srv-dbotboe7bikc73a7lr4g`, workspace `tea-dbot87ec6qcc738memt0`, regione Frankfurt, piano gratuito. Build `pip install -r vinyl-price-check/requirements.txt`; start `cd vinyl-price-check && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`. Questo servizio usa il repository pubblico tramite URL; le nuove versioni richiedono deploy manuale anche se è presente l’impostazione autoDeploy. Il `render.yaml` nella cartella è un esempio per eventuale repository autonomo, non la fonte delle variabili correnti.

Il piano gratuito può sospendersi dopo inattività e richiedere un primo caricamento più lungo. Cache volatile massima 5 minuti e 256 risposte; 20 richieste applicative/minuto per istanza, chiamate Discogs serializzate a distanza di 2,5 secondi. Non vengono salvati record di ricerca. Credenziali esclusivamente nell’ambiente server. Nessun database richiesto.
