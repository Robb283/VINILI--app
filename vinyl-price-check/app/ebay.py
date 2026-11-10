"""Read-only eBay Browse integration. Credentials and OAuth tokens never leave the server."""
import asyncio
import math
import os
import re
import time
import unicodedata
from collections import OrderedDict
from datetime import datetime, timezone
from statistics import median
from urllib.parse import quote, urlparse

import httpx

BASE = 'https://api.ebay.com'
SCOPE = 'https://api.ebay.com/oauth/api_scope'
_token = ''
_token_until = 0.0
_token_lock = asyncio.Lock()
_slots = asyncio.Semaphore(3)
_results = OrderedDict()


class EbayError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def configured():
    return bool(os.getenv('EBAY_CLIENT_ID', '').strip() and os.getenv('EBAY_CLIENT_SECRET', '').strip())


def money(value, allow_zero=False):
    try:
        raw = value.get('value')
        if isinstance(raw, bool): return None
        amount = float(raw)
        if math.isfinite(amount) and (amount >= 0 if allow_zero else amount > 0):
            return {'value': round(amount, 2), 'currency': value['currency']}
    except (TypeError, ValueError, KeyError, AttributeError):
        pass
    return None


async def access_token():
    global _token, _token_until
    if not configured():
        raise EbayError('not_configured', 'Collegamento eBay non ancora configurato.')
    async with _token_lock:
        if _token and time.monotonic() < _token_until: return _token
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(BASE + '/identity/v1/oauth2/token',
                    auth=httpx.BasicAuth(os.environ['EBAY_CLIENT_ID'].strip(), os.environ['EBAY_CLIENT_SECRET'].strip()),
                    data={'grant_type': 'client_credentials', 'scope': SCOPE})
        except httpx.RequestError:
            raise EbayError('unreachable', 'eBay non raggiungibile. Riprova più tardi.')
        if response.status_code == 429:
            raise EbayError('rate_limited', 'Limite eBay raggiunto. Riprova più tardi.')
        if response.status_code in (400, 401, 403):
            raise EbayError('credentials_rejected', 'eBay non accetta le credenziali Production configurate dal gestore.')
        if response.status_code != 200:
            raise EbayError('upstream_error', 'Autenticazione eBay temporaneamente non disponibile.')
        try:
            data = response.json()
            token = data['access_token']
            ttl = float(data['expires_in'])
            if not isinstance(token, str) or not token or not math.isfinite(ttl) or ttl <= 0: raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise EbayError('invalid_response', 'Risposta di autenticazione eBay non utilizzabile.')
        _token, _token_until = token, time.monotonic() + max(0, ttl - 60)
        return _token


async def browse(path, params=None):
    global _token_until
    token = await access_token()
    async with _slots:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(BASE + '/buy/browse/v1' + path, params=params,
                    headers={'Authorization': 'Bearer ' + token, 'X-EBAY-C-MARKETPLACE-ID': 'EBAY_IT',
                             'Accept-Language': 'en-US', 'X-EBAY-C-ENDUSERCTX': 'contextualLocation=country%3DIT'})
        except httpx.RequestError:
            raise EbayError('unreachable', 'eBay non raggiungibile. Riprova più tardi.')
    if response.status_code == 401:
        _token_until = 0
        raise EbayError('access_denied', 'eBay non autorizza l’accesso Browse. Il gestore deve verificare chiavi e autorizzazioni Production.')
    if response.status_code == 403:
        raise EbayError('access_denied', 'L’account eBay non è autorizzato a usare Browse in Production.')
    if response.status_code == 429:
        raise EbayError('rate_limited', 'Limite eBay raggiunto. Riprova più tardi.')
    if response.status_code != 200:
        raise EbayError('upstream_error', 'Ricerca eBay temporaneamente non disponibile.')
    try: return response.json()
    except ValueError: raise EbayError('invalid_response', 'Risposta eBay non leggibile.')


def norm(value):
    value = re.sub(r'\s*\(\d+\)', '', str(value or ''))
    value = ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', value))


def contains(text, value):
    value = norm(value)
    return bool(value) and (' ' + value + ' ') in (' ' + norm(text) + ' ')


def compact(value): return re.sub(r'[^a-z0-9]', '', norm(value))


def catalogue_matches(text, catalogue):
    value = compact(catalogue)
    if not value: return False
    pattern = r'(?<![a-z0-9])' + r'[\W_]*'.join(re.escape(c) for c in value) + r'(?![a-z0-9])'
    return bool(re.search(pattern, norm(text)))


def aspects(item):
    return {norm(a.get('name')): str(a.get('value', '')) for a in item.get('localizedAspects', [])}


def aspect_value(data, names):
    return ' '.join(data[norm(name)] for name in names if norm(name) in data)


def country_aliases(country):
    aliases = {'US': ['US', 'USA', 'United States', 'U.S.', 'U.S.A.'],
               'UK': ['UK', 'United Kingdom', 'Great Britain', 'U.K.'],
               'Germany': ['Germany', 'Deutschland'], 'Italy': ['Italy', 'Italia'],
               'France': ['France', 'Francia'], 'Japan': ['Japan', 'Japanese'],
               'Netherlands': ['Netherlands', 'Holland'], 'Europe': ['Europe', 'European']}
    return aliases.get(country, [country])


def safe_url(value, image=False):
    p = urlparse(str(value or ''))
    allowed = {'i.ebayimg.com'} if image else {'www.ebay.it', 'www.ebay.com', 'www.ebay.co.uk', 'www.ebay.de', 'www.ebay.fr', 'www.ebay.es', 'www.ebay.ca', 'www.ebay.com.au'}
    return value if p.scheme == 'https' and p.hostname in allowed and not p.username and not p.password else None


def assess(item, edition):
    """Return only album candidates; price comparisons require explicit edition evidence."""
    if 'FIXED_PRICE' not in item.get('buyingOptions', []) or 'AUCTION' in item.get('buyingOptions', []): return None
    title = item.get('title') or ''
    data = aspects(item)
    format_value = aspect_value(data, ['Format'])
    if re.search(r'\b(?:cd|cassette|dvd|sacd|blu ray|lot|bundle|lotto|poster)\b', norm(title + ' ' + format_value)): return None
    if re.search(r'\b(?:cover only|sleeve only|no record|senza disco|record lot|records lot|box set)\b', norm(title)): return None
    artist_text = title + ' ' + aspect_value(data, ['Artist', 'Artista', 'Performer'])
    album_text = title + ' ' + aspect_value(data, ['Release Title', 'Album', 'Titolo'])
    if not contains(artist_text, edition.get('artist')) or not contains(album_text, edition.get('title')): return None
    formats = ' '.join(f.get('name', '') + ' ' + ' '.join(f.get('descriptions', [])) for f in edition.get('formats', []))
    vinyl = any(contains(format_value + ' ' + title, word) for word in ['vinyl', 'LP', '33 rpm', '33 giri'])
    if not vinyl: return None
    # Explicit contradictory metadata excludes the item, even if the title happens to match.
    years = aspect_value(data, ['Release Year', 'Year of Release', 'Anno di pubblicazione'])
    year = str(edition.get('year') or '')
    if years and year and year not in re.findall(r'\b\d{4}\b', years): return None
    countries = aspect_value(data, ['Country/Region of Manufacture', 'Country of Origin', 'Country', 'Paese di fabbricazione'])
    aliases = country_aliases(edition.get('country', ''))
    if countries and not any(contains(countries, c) for c in aliases): return None
    catalogues = [x.get('catno', '') for x in edition.get('labels', []) if compact(x.get('catno')) not in ('', 'none', 'unknown')]
    cat_aspect = aspect_value(data, ['Catalog Number', 'Catalogue Number', 'Numero di catalogo'])
    if cat_aspect and catalogues and not any(catalogue_matches(cat_aspect, c) for c in catalogues): return None
    if not any('Reissue' in f.get('descriptions', []) or 'Repress' in f.get('descriptions', []) for f in edition.get('formats', [])):
        if re.search(r'\b(?:reissue|repress|remastered|ristampa)\b', norm(title + ' ' + aspect_value(data, ['Edition']))): return None
    evidence = {
        'catalogue': any(catalogue_matches(title + ' ' + cat_aspect, c) for c in catalogues),
        'year': bool(year and year in re.findall(r'\b\d{4}\b', title + ' ' + years)),
        'country': any(contains(title + ' ' + countries, c) for c in aliases) if aliases[0] else False,
        'format': True,
    }
    audio = norm(title + ' ' + aspect_value(data, ['Edition', 'Audio Channels', 'Features']))
    if 'Mono' in formats and contains(audio, 'stereo'): return None
    if 'Stereo' in formats and contains(audio, 'mono'): return None
    audio_known = (contains(audio, 'mono') if 'Mono' in formats else contains(audio, 'stereo') if 'Stereo' in formats else True)
    price = money(item.get('price'))
    url = safe_url(item.get('itemWebUrl'))
    if not price or not url: return None
    # Neither seller country nor listing creation date is pressing evidence.
    compatible = all(evidence.values()) and audio_known
    shipping = None
    for option in item.get('shippingOptions', []):
        value = money(option.get('shippingCost'), allow_zero=True)
        if value:
            shipping = value
            break
    grading = aspect_value(data, ['Record Grading', 'Vinyl Grading', 'Condizione del disco'])
    sleeve = aspect_value(data, ['Sleeve Grading', 'Condizione della copertina'])
    missing = [label for key, label in [('catalogue', 'catalogo'), ('year', 'anno'), ('country', 'paese')] if not evidence[key]]
    if not audio_known: missing.append('mono/stereo')
    item_id = str(item.get('legacyItemId') or item.get('itemId') or '')
    if '|' in item_id: item_id = item_id.split('|')[1]
    return {'id': item_id,
            'title': title, 'url': url, 'image': safe_url(item.get('image', {}).get('imageUrl'), image=True),
            'price': price, 'shipping': shipping, 'condition': item.get('condition') or 'Non dichiarata',
            'record_grading': grading or None, 'sleeve_grading': sleeve or None,
            'compatibility': 'compatible' if compatible else 'unverified',
            'note': 'Catalogo, anno, paese e formato coerenti con l’annuncio; tiratura da verificare nelle foto.' if compatible else 'Da verificare: ' + ', '.join(missing) + '.',
            'evidence': evidence}


def price_summary(items):
    candidates = [i for i in items if i['compatibility'] == 'compatible' and i['price']['currency'] == 'EUR']
    values = sorted(i['price']['value'] for i in candidates)
    if len(values) < 3:
        return {'available': False, 'count': len(values), 'currency': 'EUR',
                'reason': 'Dati insufficienti: servono almeno 3 annunci compatibili con prezzi in euro.'}
    def percentile(p):
        index = (len(values) - 1) * p
        lo = int(index)
        return round(values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (index - lo), 2)
    return {'available': True, 'count': len(values), 'currency': 'EUR',
            'low': percentile(.25), 'high': percentile(.75), 'median': round(median(values), 2),
            'condition': 'Condizioni miste: controlla i gradi dichiarati nei singoli annunci.',
            'confidence': 'Bassa' if len(values) < 5 else 'Indicativa',
            'reason': 'Fascia centrale (25°–75° percentile) dei prezzi richiesti, non vendite concluse. Spedizione esclusa; nessuna correzione per le condizioni.'}


async def search_offers(edition):
    now = time.monotonic()
    key = edition['id']
    if key in _results and now - _results[key][0] < 300: return _results[key][1]
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        if not configured(): raise EbayError('not_configured', 'Collegamento eBay non ancora configurato.')
        artist = re.sub(r'\s*\(\d+\)', '', edition.get('artist', ''))
        title = edition.get('title', '')
        catalogue = next((x['catno'] for x in edition.get('labels', []) if compact(x.get('catno')) not in ('', 'none', 'unknown')), '')
        clean = lambda value: ' '.join(re.findall(r'[\w]+', value, re.UNICODE))
        queries = list(dict.fromkeys([clean(f'{artist} {title} {catalogue}')[:100], clean(f'{artist} {title} vinyl')[:100]]))
        summaries = OrderedDict()
        for query in queries:
            response = await browse('/item_summary/search', {'q': query, 'limit': '24', 'filter': 'buyingOptions:{FIXED_PRICE},deliveryCountry:IT', 'fieldgroups': 'EXTENDED'})
            for item in response.get('itemSummaries', []):
                if item.get('itemId'): summaries.setdefault(item['itemId'], item)
            if len(summaries) >= 8: break
        # Bounded detail lookups provide the seller's declared pressing and condition aspects.
        selected = list(summaries.values())[:8]
        async def detail(item):
            try:
                data = await browse('/item/' + quote(item['itemId'], safe=''))
                return item | data, False
            except EbayError as error:
                if error.code in ('credentials_rejected', 'access_denied', 'rate_limited'): raise
                return item, True
        details = await asyncio.gather(*(detail(item) for item in selected))
        offers = OrderedDict()
        for (item, failed) in details:
            offer = assess(item, edition)
            if offer and offer['id']: offers.setdefault(offer['id'], offer)
        items = list(offers.values())
        result = {'status': 'ok', 'source': 'eBay', 'marketplace': 'EBAY_IT', 'checked_at': checked_at,
                  'items': items, 'price': price_summary(items), 'examined': len(selected),
                  'partial': any(failed for _, failed in details) or len(summaries) > len(selected),
                  'message': 'Annunci attivi su eBay; disponibilità e importi possono cambiare.' if items else 'Nessun annuncio compatibile trovato nel campione esaminato.'}
    except EbayError as error:
        result = {'status': error.code, 'source': 'eBay', 'items': [], 'checked_at': checked_at,
                  'price': {'available': False, 'count': 0}, 'message': error.message}
    if result['status'] == 'ok':
        _results[key] = (now, result)
        _results.move_to_end(key)
        while len(_results) > 128: _results.popitem(last=False)
    return result
