import asyncio
import math
import re
import unicodedata
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from app.translate import translate_notes

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title='First Press — guida alle prime stampe', version='0.5.0')
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
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://i.discogs.com https://img.discogs.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
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
    headers = {'User-Agent': os.getenv('DISCOGS_USER_AGENT', 'FirstPress/0.5')}
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
    eligible = [v for v in rows if v['year'] and not v['special']]
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
        verdict = 'Indicata come ristampa nel catalogo'
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
            'formats': formats, 'identifiers': identifiers, 'notes': data.get('notes') or '', 'images': release_images(data),
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



def country_matches(country, region):
    return region in re.findall(r'[A-Z]{2,}', str(country or ''))


def release_images(data):
    images = sorted((data.get('images') or []), key=lambda image: image.get('type') != 'primary')
    result = []
    for image in images:
        uri = image.get('uri') or image.get('resource_url') or ''
        parsed = urlparse(uri)
        if parsed.scheme == 'https' and parsed.hostname in {'i.discogs.com', 'img.discogs.com'}:
            result.append({'url': uri, 'type': image.get('type'), 'width': image.get('width'), 'height': image.get('height')})
    return result[:6]


async def scan_versions(master_id, country=''):
    versions, pages, total = [], 1, 0
    for page in range(1, 3):
        params = {'format': 'Vinyl', 'sort': 'released', 'sort_order': 'asc', 'per_page': 100, 'page': page}
        if country: params['country'] = country
        data = await discogs(f'/masters/{master_id}/versions', params, authenticated=False)
        versions.extend(data.get('versions', []))
        pages = data.get('pagination', {}).get('pages', 1)
        total = data.get('pagination', {}).get('items', len(versions))
        if page >= pages: break
    rows, chosen, earliest = rank_versions(versions)
    return {'rows': rows, 'chosen': chosen, 'earliest': earliest, 'partial': pages > 2, 'total': total}


def select_country_companions(primary, rows):
    """Primary first; UK/US each appear once, including compound territories."""
    selected = [(primary, 'world')]
    covered = {code for code in ('UK', 'US') if country_matches(primary.get('country'), code)}
    for code in ('UK', 'US'):
        if code in covered: continue
        _, chosen, _ = rank_versions([r for r in rows if country_matches(r.get('country'), code)])
        if chosen and chosen['id'] not in {item['id'] for item, _ in selected}:
            selected.append((chosen, code))
    return selected


async def enrich_edition(row, role, earliest, partial):
    data = await discogs(f"/releases/{row['id']}", authenticated=False)
    details = release_details(data, earliest, partial)
    details['role'] = role
    details['partial'] = partial
    proper_names = [x['name'] for x in details['labels'] + details['companies'] if x.get('name')]
    proper_names += [name + ' Records' for name in proper_names if not name.endswith('Records')]
    protected = details['identifiers'] + [{'value': name} for name in proper_names]
    details['translation'] = await translate_notes(details['notes'], protected)
    details['price'] = await optional_price(row['id'])
    return details


@app.get('/api/guide')
async def guide(q: str = Query(min_length=2, max_length=220), master_id: int | None = Query(None, gt=0)):
    if len(q.strip()) < 2: raise HTTPException(422, 'Scrivi artista e titolo.')
    matches = []
    if master_id is None:
        search = await discogs('/database/search', {'q': q.strip(), 'type': 'master', 'per_page': 10})
        matches = [{k: r.get(k) for k in ('id', 'title', 'year')} for r in search.get('results', [])]
        if not matches: return {'found': False, 'reason': 'Nessun album trovato. Prova artista e titolo senza altri dettagli.'}
        matches.sort(key=lambda r: master_match_score(q, r.get('title') or ''), reverse=True)
        if master_match_score(q, matches[0].get('title') or '') < .55:
            return {'found': False, 'reason': 'Il titolo non corrisponde abbastanza. Prova “Artista - Titolo”.'}
        master_id = matches[0]['id']
    master = await discogs(f'/masters/{master_id}', authenticated=False)
    worldwide = await scan_versions(master_id)
    primary = worldwide['chosen']
    if not primary:
        return {'found': False, 'reason': 'Non sono state trovate versioni in vinile per questo album.'}
    contexts = {'world': worldwide}
    rows = worldwide['rows']
    missing, warnings = [], []
    for region in ('UK', 'US'):
        if country_matches(primary.get('country'), region): continue
        if worldwide['partial']:
            try:
                regional = await scan_versions(master_id, region)
                contexts[region] = regional
                # Replace the sampled regional rows with the dedicated scan.
                rows = [r for r in rows if not country_matches(r.get('country'), region)] + regional['rows']
            except HTTPException:
                warnings.append(f'Impossibile completare il controllo {region}.')
        else:
            regional_rows = [r for r in rows if country_matches(r.get('country'), region)]
            regional_rows, chosen, earliest = rank_versions(regional_rows)
            contexts[region] = {'rows': regional_rows, 'chosen': chosen, 'earliest': earliest, 'partial': False}
        if region in contexts and not contexts[region]['chosen']: missing.append(region)
    selected = select_country_companions(primary, rows)
    editions = []
    tasks = [enrich_edition(row, role, contexts.get(role, worldwide)['earliest'], contexts.get(role, worldwide)['partial']) for row, role in selected]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for (row, role), result in zip(selected, results):
        if isinstance(result, Exception):
            warnings.append(f"Dettagli dell’edizione {row['id']} non raggiungibili.")
        else: editions.append(result)
    return {'found': True, 'master': {'id': master_id, 'title': master.get('title'),
            'artist': ', '.join(x.get('name', '') for x in master.get('artists', [])),
            'year': master.get('year'), 'source_url': f'https://www.discogs.com/master/{master_id}'},
            'matches': matches, 'editions': editions, 'missing_regions': missing, 'warnings': warnings,
            'partial': worldwide['partial'], 'checked_at': datetime.now(timezone.utc).isoformat(),
            'limitation': 'Edizioni commerciali datate più vecchie trovate su Discogs; il catalogo può essere incompleto. Più tirature possono condividere lo stesso anno.'}
