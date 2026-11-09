# First Press — edizioni più vecchie a confronto

Versione 0.5. App FastAPI in italiano, disponibile su https://vinyl-price-check.onrender.com . Il repository e l’URL storico restano invariati per conservare gli aggiornamenti.

## Flusso

Solo artista e titolo, in un campo. Nessuna ricerca con foto e nessun caricamento di immagini. La risposta compatta mostra le copertine delle specifiche edizioni:

- più vecchia UK → aggiunge la più vecchia US, se presente;
- più vecchia US → aggiunge la più vecchia UK, se presente;
- più vecchia di altro paese → aggiunge UK e US, quando presenti;
- un’edizione che copre entrambi i territori compare una sola volta.

Per ogni scheda: paese e data, etichetta/catalogo, formato, copertina con eventuali immagini aggiuntive, note italiane, link alla fonte. Matrici e note originali sono chiuse inizialmente e apribili con un clic. L’eventuale fascia prezzo compare solo se realmente disponibile e autorizzata; il flag Marketplace resta disattivato, senza modifiche alle precedenti restrizioni.

## Selezione e limiti

La ricerca trova l’album (master) senza filtrare il formato rappresentativo: un master CD può avere prime versioni in vinile. Il filtro Vinyl viene applicato alle versioni. Sono considerate le versioni datate commerciali più vecchie trovate; promo, test pressing, acetati e edizioni non ufficiali non vengono preferiti alle versioni commerciali. La presenza del flag Reissue/Repress viene mostrata, senza scegliere una versione più recente solo perché priva di quel flag.

Il catalogo mondiale viene letto in ordine cronologico, fino a 2 pagine da 100. Se è completo, US e UK vengono selezionate da quel catalogo; se è parziale, vengono richiesti anche cataloghi regionali dedicati (fino a 200 versioni per territorio). Ricerca parziale e territori non trovati sono segnalati. Date assenti non vengono inventate. Nello stesso anno possono esistere tirature non ordinabili con certezza: non si certifica una prima stampa solo dalla data.

Le immagini sono quelle della release specifica, fornite dall’API Discogs. Si usano soltanto URL HTTPS dei domini i.discogs.com e img.discogs.com; nessuna immagine generata o copertina generica è sostituita a una mancante. Il browser le carica da Discogs; il provider può vedere le richieste tecniche. Se non sono accessibili viene mostrato un messaggio con link alla fonte. Le foto secondarie non sono etichettate automaticamente come retro/etichetta perché l’API non ne certifica il contenuto.

## Italiano

Interfaccia, paesi, formati comuni e descrizioni delle matrici sono localizzati. Titoli, nomi propri e codici rimangono originali. Le note pubbliche Discogs vengono inviate dal server al servizio gratuito MyMemory, solo mediante endpoint GET documentato; non vengono inviati token Discogs, ricerche dell’utente o dati personali.

Si traduce un estratto fino a 1100 caratteri per edizione (se più lungo è indicato). L’originale completo resta sempre consultabile. Indirizzi, riferimenti Discogs e codici presenti nelle note vengono sostituiti con segnaposto e ripristinati: se il traduttore altera un segnaposto, la traduzione non viene mostrata. Le note già riconoscibili come italiane non richiedono traduzione. La traduzione automatica assume inglese come lingua sorgente e può essere imprecisa: verificare l’originale.

MyMemory: massimo 500 byte per richiesta, quota gratuita anonima dichiarata di 5000 caratteri/giorno. L’app suddivide in segmenti entro 450 byte, applica un tetto locale di 4500 caratteri al giorno per processo, memorizza le traduzioni per massimo 6 ore e 128 voci. La quota effettiva può essere condivisa sull’IP del provider. Quota esaurita o errore: messaggio esplicito e note originali disponibili, senza traduzioni inventate. Non vengono usati servizi a pagamento né inviate contribuzioni SET.

Documentazione: https://mymemory.translated.net/doc/spec.php e https://mymemory.translated.net/doc/usagelimits.php . Dati Discogs: https://www.discogs.com/developers e https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use . Attribuzione nella pagina e accanto ai risultati.

## Avvio e test

Python 3.12. Dalla cartella del progetto:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DISCOGS_TOKEN='solo-nell-ambiente-server'
uvicorn app.main:app --reload
```

Su PowerShell usare `.venv\Scripts\Activate.ps1` e `$env:DISCOGS_TOKEN`. `.env.example` è documentazione e non viene caricato automaticamente. Nessuna credenziale è inclusa nei file.

```sh
pip install -r requirements-dev.txt
python -m pytest tests -q
node --check app/static/app.js
```

24 test verificano regole UK/US/altro paese, territori composti senza doppioni, ricerca regionale quando il catalogo mondiale è parziale, assenza paesi non inventata, date mancanti, precedenza cronologica, URL copertine, preservazione codici/indirizzi, errore traduzione, rimozione ricerca fotografica, errori e assenza di chiamate Marketplace quando disattivate. Le fixture sintetiche sono solo nei test, mai nel prodotto.

## Conservazione e pubblicazione

Repository: https://github.com/Robb283/VINILI--app/tree/vinyl-price-check/vinyl-price-check . Il ramo principale resta indipendente; le versioni precedenti rimangono nella cronologia Git.

Render: servizio `srv-dbotboe7bikc73a7lr4g`, workspace `tea-dbot87ec6qcc738memt0`, Frankfurt, piano gratuito. Build `pip install -r vinyl-price-check/requirements.txt`; start `cd vinyl-price-check && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`. Repository pubblico collegato via URL: le nuove versioni richiedono deploy manuale. Il render.yaml è un esempio per eventuale repository autonomo, non la fonte delle variabili correnti.

Cache Discogs volatile fino a 5 minuti / 256 risposte; 20 richieste applicative/minuto per istanza; upstream serializzato ogni 2,5 secondi. Usare un solo worker. Nessun database e nessun archivio di ricerche. Il piano gratuito può sospendersi dopo inattività, con un primo caricamento più lento. Le credenziali restano nell’ambiente server.

Quando il traduttore non è disponibile, un estrattore locale può fornire una sintesi esplicitamente etichettata: riconosce soltanto affermazioni presenti nelle note (indirizzi di prima stampa/repress, fiore nei runout, copertina apribile/lucida, buste interne, errori di stampa, licenza). Non è una traduzione completa e non inventa caratteristiche assenti. L’originale rimane consultabile. Questa sintesi non invia dati a servizi esterni e non dipende dalla quota del traduttore.

## Versione 0.6 — immagini ingrandibili

Clic sulla copertina o su una miniatura: visualizzatore a schermo intero con zoom da adattamento a 4×, scorrimento sui dettagli, frecce per le immagini della stessa edizione, doppio clic per passare da adattamento a 2×, pulsante Chiudi ed Esc. Il dialogo nativo mantiene la navigazione da tastiera e ripristina il focus alla chiusura. La foto viene usata con l’URL originale fornito dall’API: nessuna ricostruzione o aumento artificiale della risoluzione.
