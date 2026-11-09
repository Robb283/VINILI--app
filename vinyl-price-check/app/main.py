import asyncio
import math
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

CONDITIONS = {
    'M': 'Mint (M)', 'NM': 'Near Mint (NM or M-)',
    'VG+': 'Very Good Plus (VG+)', 'VG': 'Very Good (VG)',
    'G+': 'Good Plus (G+)', 'G': 'Good (G)', 'F': 'Fair (F)', 'P': 'Poor (P)',
}
app = FastAPI(title='Vinyl Price Check', version='0.1.0')
static = Path(__file__).parent / 'static'
app.mount('/static', StaticFiles(directory=static), name='static')
cache = OrderedDict()
lock = asyncio.Lock()
last_call = 0.0
requests_window = []


@app.middleware('http')
async def headers(request: Request, call_next):
    if request.url.path.startswith('/api/') and request.url.path != '/api/health':
        now = time.monotonic()
        requests_window[:] = [t for t in requests_window if now - t < 60]
        if len(requests_window) >= 20:
            return JSONResponse({'detail': 'Servizio occupato. Riprova tra un minuto.'}, status_code=429, headers={'Retry-After': '60', 'Cache-Control': 'no-store'})
        requests_window.append(now)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


async def discogs(path: str, params=None, authenticated=True):
    global last_call
    token = os.getenv('DISCOGS_TOKEN', '').strip()
    if authenticated and not token:
        raise HTTPException(503, 'Ricerca non configurata: il gestore deve impostare la credenziale Discogs sul server.')
    key = (path, tuple(sorted((params or {}).items())), bool(token))
    now = time.monotonic()
    if key in cache and now - cache[key][0] < 300:
        return cache[key][1]
    headers = {'User-Agent': os.getenv('DISCOGS_USER_AGENT', 'VinylPriceCheck/0.1')}
    if token:
        headers['Authorization'] = 'Discogs token=' + token
    # One upstream request at a time, <= 24/minute. No rotating keys or retries.
    async with lock:
        await asyncio.sleep(max(0, 2.5 - (time.monotonic() - last_call)))
        last_call = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get('https://api.discogs.com' + path, params=params, headers=headers)
        except httpx.RequestError:
            raise HTTPException(502, 'Discogs non raggiungibile. Riprova più tardi.')
    if r.status_code == 429:
        raise HTTPException(429, 'Limite Discogs raggiunto. Attendi un minuto e riprova.', headers={'Retry-After': '60'})
    if r.status_code in (401, 403):
        raise HTTPException(503, 'Discogs non autorizza questo accesso. Il gestore deve verificare credenziale e impostazioni venditore.')
    if r.status_code == 404:
        raise HTTPException(404, 'Edizione non trovata su Discogs.')
    if r.status_code != 200:
        raise HTTPException(502, 'Discogs ha restituito un errore temporaneo.')
    try:
        data = r.json()
    except ValueError:
        raise HTTPException(502, 'Risposta Discogs non leggibile.')
    cache[key] = (time.monotonic(), data)
    cache.move_to_end(key)
    while len(cache) > 256:
        cache.popitem(last=False)
    return data


@app.get('/')
async def index():
    return FileResponse(static / 'index.html')


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'search_configured': bool(os.getenv('DISCOGS_TOKEN')),
            'market_data_enabled': os.getenv('ENABLE_MARKET_DATA') == 'true'}


@app.get('/api/search')
async def search(artist: str = Query(min_length=1, max_length=150),
                 title: str = Query(min_length=1, max_length=150),
                 country: str = Query('', max_length=80),
                 catno: str = Query('', max_length=80),
                 pressing: Literal['any', 'first', 'reissue'] = 'any',
                 page: int = Query(1, ge=1, le=50)):
    if not artist.strip() or not title.strip():
        raise HTTPException(422, 'Inserisci artista e titolo.')
    params = {'type': 'release', 'format': 'Vinyl', 'artist': artist.strip(),
              'release_title': title.strip(), 'per_page': 20, 'page': page}
    if country.strip(): params['country'] = country.strip()
    if catno.strip(): params['catno'] = catno.strip()
    data = await discogs('/database/search', params)
    results = []
    for r in data.get('results', []):
        if pressing == 'reissue' and 'Reissue' not in r.get('format', []):
            continue
        results.append({k: r.get(k) for k in ('id', 'title', 'year', 'country', 'catno', 'label', 'format')})
    return {'results': results, 'pagination': {k: data.get('pagination', {}).get(k) for k in ('page', 'pages', 'items')},
            'warning': 'Prima stampa non certificabile dalla sola ricerca: confronta anno, etichetta, catalogo e matrici.' if pressing == 'first' else 'Solo edizioni marcate Reissue nella pagina corrente. Le altre pagine possono contenere altre ristampe.' if pressing == 'reissue' else None}


class Assessment(BaseModel):
    release_id: int = Field(gt=0)
    asking_price: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    condition: Literal['M', 'NM', 'VG+', 'VG', 'G+', 'G', 'F', 'P'] | None = None
    confirmed: bool = False


def positive_eur(value):
    if not isinstance(value, dict) or value.get('currency') != 'EUR': return None
    v = value.get('value')
    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0:
        return round(v, 2)
    return None


def evaluate(body: Assessment, suggestions: dict, stats: dict):
    prices = {k: positive_eur(suggestions.get(v)) for k, v in CONDITIONS.items()}
    values = [v for v in prices.values() if v is not None]
    reference = prices.get(body.condition)
    verdict, confidence = 'Non valutabile', 'Insufficiente'
    reason = 'Non ci sono suggerimenti di prezzo in euro per la condizione indicata.'
    if body.condition is None:
        reason = 'Indica le condizioni del vinile per confrontare prezzi omogenei.'
    elif reference is not None:
        ratio = body.asking_price / reference
        verdict = 'Conveniente' if ratio < .8 else 'Troppo alto' if ratio > 1.2 else 'Corretto'
        confidence = 'Bassa'
        reason = 'Confronto indicativo con il suggerimento Discogs per questa condizione; non è una stima basata su vendite comparabili verificate.'
    if stats.get('blocked_from_sale'):
        verdict, confidence, reason = 'Non valutabile', 'Insufficiente', 'Edizione bloccata alla vendita su Discogs.'
    return {'verdict': verdict, 'confidence': confidence, 'reason': reason,
            'reference': reference, 'condition': body.condition,
            'suggestions_range': [min(values), max(values)] if len(values) >= 2 else None,
            'range_label': 'Estremi dei suggerimenti Discogs tra condizioni diverse, da P a M. Non è un intervallo di vendite né il valore della tua copia.',
            'market_value_range': None, 'suggestions': prices,
            'lowest_listing': positive_eur(stats.get('lowest_price')),
            'num_for_sale': stats.get('num_for_sale'),
            'method': 'Sotto l’80% del suggerimento: conveniente; sopra il 120%: troppo alto; altrimenti corretto. Soglie scelte dall’app, non da Discogs. Copertina, spedizione e autenticità non sono valutate.'}


@app.post('/api/assess')
async def assess(body: Assessment):
    if not body.confirmed:
        raise HTTPException(422, 'Conferma l’edizione confrontando i dati con la tua copia.')
    release = await discogs(f'/releases/{body.release_id}', authenticated=False)
    if not any(f.get('name') == 'Vinyl' for f in release.get('formats', [])):
        raise HTTPException(422, 'L’edizione selezionata non è in vinile.')
    result = {'release': {'id': body.release_id, 'title': release.get('title'),
                         'year': release.get('year'), 'country': release.get('country')},
              'source_url': f'https://www.discogs.com/release/{body.release_id}',
              'checked_at': datetime.now(timezone.utc).isoformat(), 'currency': 'EUR'}
    if os.getenv('ENABLE_MARKET_DATA') != 'true':
        return result | evaluate(body, {}, {}) | {'reason': 'Dati di mercato disattivati dal gestore. Nessuna stima viene inventata.'}
    warnings = []
    stats, suggestions = {}, {}
    for name, path, params in [('stats', f'/marketplace/stats/{body.release_id}', {'curr_abbr': 'EUR'}),
                               ('suggestions', f'/marketplace/price_suggestions/{body.release_id}', None)]:
        try:
            data = await discogs(path, params, authenticated=name == 'suggestions')
            if name == 'stats': stats = data
            else: suggestions = data
        except HTTPException as e:
            warnings.append(f'{name}: {e.detail}')
    return result | evaluate(body, suggestions, stats) | {'warnings': warnings}
