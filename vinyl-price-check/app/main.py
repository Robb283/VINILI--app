import asyncio
import math
import re
import unicodedata
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title='First Press — guida alle prime stampe', version='0.4.0')
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
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; worker-src 'self' blob:; style-src 'self'; img-src 'self' blob: data:; connect-src 'self' https://cdn.jsdelivr.net; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
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
    headers = {'User-Agent': os.getenv('DISCOGS_USER_AGENT', 'FirstPress/0.4')}
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
        raise HTTPException(503, 'Discogs non autorizza questo accesso. Il gestore deve verificare credenziale Discogs.')
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
    return {'status': 'ok', 'search_configured': bool(os.getenv('DISCOGS_TOKEN')), 'mode': 'first_press_guide'}


def release_year(value):
    match = re.match(r'^(\d{4})(?:$|[-/])', str(value or ''))
    year = int(match.group(1)) if match else None
    return year if year and 1900 <= year <= datetime.now().year + 1 else None


def version_info(item):
    text = item.get('format') or ''
    if isinstance(text, list): text = ', '.join(text)
    reissue = bool(re.search(r'\b(?:Reissue|Repress)\b', text, re.I))
    special = bool(re.search(r'\b(?:Unofficial|Promo|Test Pressing|Acetate)\b', text, re.I))
    return {key: item.get(key) for key in ('id', 'title', 'country', 'catno', 'label', 'released')} | {
        'year': release_year(item.get('released')), 'format': text,
        'reissue': reissue, 'special': special,
        'source_url': f"https://www.discogs.com/release/{item['id']}"}


def rank_versions(versions):
    rows = [version_info(v) for v in versions if not v.get('major_formats') or 'Vinyl' in v['major_formats']]
    rows.sort(key=lambda v: (v['year'] or 9999, v['reissue'], v['special'], str(v.get('released') or ''), v['id']))
    eligible = [v for v in rows if v['year'] and not v['reissue'] and not v['special']]
    chosen = eligible[0] if eligible else (rows[0] if rows else None)
    earliest = eligible[0]['year'] if eligible else None
    return rows, chosen, earliest


def release_details(data, earliest=None, partial=False):
    formats = data.get('formats', [])
    if not any(f.get('name') == 'Vinyl' for f in formats):
        raise HTTPException(422, 'Questa edizione non è in vinile.')
    descriptions = [s for f in formats for s in f.get('descriptions', [])]
    row = version_info({'id': data['id'], 'format': descriptions, 'released': data.get('released') or data.get('year')})
    if row['reissue']:
        verdict = 'Classificata come ristampa / repress'
        explanation = 'Discogs riporta Reissue o Repress. Non usarla come riferimento automatico per una prima tiratura.'
    elif row['special']:
        verdict = 'Edizione speciale da verificare'
        explanation = 'Promo, test pressing o edizione non ufficiale: non equivale automaticamente alla prima edizione commerciale.'
    elif earliest and row['year'] and row['year'] > earliest:
        verdict = 'Più recente delle candidate trovate'
        explanation = f'Nel gruppo esaminato sono presenti candidate datate {earliest}. Questa edizione è datata {row["year"]}.'
    elif earliest and row['year'] == earliest:
        verdict = 'Candidata più precoce trovata'
        explanation = 'Anno e classificazione sono compatibili con le candidate più precoci esaminate. Per distinguere le tirature dello stesso anno servono etichette, matrici e note.'
    else:
        verdict = 'Prima stampa non determinabile'
        explanation = 'Le informazioni disponibili non permettono di proporre una prima tiratura con sufficiente fondamento.'
    if partial: explanation += ' La ricerca delle versioni è parziale.'
    identifiers = [{k: x.get(k, '') for k in ('type', 'value', 'description')} for x in data.get('identifiers', [])]
    return {'id': data['id'], 'title': data.get('title'), 'country': data.get('country'),
            'year': data.get('year'), 'released': data.get('released'),
            'labels': [{'name': x.get('name'), 'catno': x.get('catno')} for x in data.get('labels', [])],
            'formats': formats, 'identifiers': identifiers, 'notes': data.get('notes') or '',
            'companies': [{'name': x.get('name'), 'role': x.get('entity_type_name')} for x in data.get('companies', [])],
            'verdict': verdict, 'explanation': explanation, 'confidence': 'Da verificare sulla copia',
            'source_url': f"https://www.discogs.com/release/{data['id']}"}


async def optional_price(release_id):
    # Independent optional feature. It cannot block the catalogue guide.
    if os.getenv('ENABLE_MARKET_DATA') != 'true':
        return {'available': False, 'reason': 'Fascia prezzo non disponibile. La guida alla stampa resta utilizzabile.'}
    try:
        data = await discogs(f'/marketplace/price_suggestions/{release_id}')
    except HTTPException:
        return {'available': False, 'reason': 'Discogs non restituisce prezzi utilizzabili per questa edizione.'}
    values = {}
    for code, name in [('VG', 'Very Good (VG)'), ('VG+', 'Very Good Plus (VG+)'), ('NM', 'Near Mint (NM or M-)')]:
        item = data.get(name, {})
        if not isinstance(item, dict): continue
        value = item.get('value')
        if item.get('currency') == 'EUR' and isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
            values[code] = round(value, 2)
    return {'available': bool(values), 'by_condition': values,
            'range': [min(values.values()), max(values.values())] if len(values) >= 2 else None,
            'reason': 'Suggerimenti Discogs in EUR per condizioni diverse (VG–NM), non intervallo delle vendite storiche. Copertina e spedizione escluse.'}


def master_match_score(query, title):
    def tokens(value):
        value = unicodedata.normalize('NFKD', value.casefold())
        words = set(re.findall(r'[a-z0-9]+', value))
        return words - {'the', 'a', 'an', 'and', 'of', 'on', 'in', 'del', 'della', 'di', 'il', 'lo', 'la', 'le', 'i', 'gli'}
    requested = tokens(query)
    return len(requested & tokens(title)) / len(requested) if requested else 0


@app.get('/api/guide')
async def guide(q: str = Query(min_length=2, max_length=220), country: str = Query('', max_length=80),
                master_id: int | None = Query(None, gt=0)):
    if len(q.strip()) < 2: raise HTTPException(422, 'Scrivi almeno artista e titolo, oppure usa una foto leggibile.')
    matches = []
    if master_id is None:
        # A master can list CD as its representative format while having original
        # vinyl versions. Filter Vinyl only on /versions, never on the album search.
        search = await discogs('/database/search', {'q': q.strip(), 'type': 'master', 'per_page': 10})
        matches = [{k: r.get(k) for k in ('id', 'title', 'year')} for r in search.get('results', [])]
        if not matches:
            return {'found': False, 'reason': 'Nessun album trovato. Prova artista e titolo senza parole come “prima stampa”, oppure correggi il testo della foto.'}
        matches.sort(key=lambda r: master_match_score(q, r.get('title') or ''), reverse=True)
        if master_match_score(q, matches[0].get('title') or '') < .55:
            return {'found': False, 'reason': 'I risultati citano il disco ma il titolo non corrisponde abbastanza. Prova “Artista - Titolo”, senza dettagli della stampa.'}
        master_id = matches[0]['id']
    master = await discogs(f'/masters/{master_id}', authenticated=False)
    versions, pages, total = [], 1, 0
    for page in range(1, 4):
        params = {'format': 'Vinyl', 'sort': 'released', 'sort_order': 'asc', 'per_page': 50, 'page': page}
        if country.strip(): params['country'] = country.strip()
        result = await discogs(f'/masters/{master_id}/versions', params, authenticated=False)
        versions.extend(result.get('versions', []))
        pages = result.get('pagination', {}).get('pages', 1)
        total = result.get('pagination', {}).get('items', len(versions))
        if page >= pages: break
    partial = pages > 3
    rows, chosen, earliest = rank_versions(versions)
    # Keep the proposed edition visible even when very many undated/special variants exist.
    shown = rows[:30]
    if chosen and chosen not in shown: shown.insert(0, chosen)
    details = None
    if chosen:
        data = await discogs(f"/releases/{chosen['id']}", authenticated=False)
        details = release_details(data, earliest, partial)
        details['price'] = await optional_price(chosen['id'])
    return {'found': True, 'master': {'id': master_id, 'title': master.get('title'),
            'artist': ', '.join(x.get('name', '') for x in master.get('artists', [])),
            'year': master.get('year'), 'source_url': f'https://www.discogs.com/master/{master_id}'},
            'matches': matches, 'scope': country.strip() or 'Tutti i paesi', 'earliest_candidate_year': earliest,
            'candidates': shown, 'scanned': len(rows), 'total': total, 'partial': partial,
            'guide': details, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'limitation': 'Il catalogo è collaborativo e può essere incompleto. Anno più antico, numero di catalogo e assenza del flag Reissue non certificano una prima stampa. Il paese cambia il significato di “prima”.'}


@app.get('/api/releases/{release_id}')
async def release(release_id: int, master_id: int = Query(gt=0), country: str = Query('', max_length=80)):
    if release_id <= 0: raise HTTPException(422, 'Edizione non valida.')
    context = await guide(q='edizione', country=country, master_id=master_id)
    data = await discogs(f'/releases/{release_id}', authenticated=False)
    if data.get('master_id') != master_id:
        raise HTTPException(422, 'Questa edizione non appartiene all’album selezionato.')
    details = release_details(data, context['earliest_candidate_year'], context['partial'])
    details['price'] = await optional_price(release_id)
    return details
