"""Bounded, cached Italian translation of public catalogue notes only."""
import asyncio
import hashlib
import html
import re
import time
from collections import OrderedDict
from datetime import date

import httpx

_cache = OrderedDict()
_budget_day = date.today()
_budget_used = 0
_budget_lock = asyncio.Lock()


def protect_text(text, identifiers=()):
    protected = {}
    literals = [i.get('value', '') for i in identifiers if i.get('value')]
    # Street addresses and catalogue references must remain verbatim.
    literals += re.findall(r'\b\d+\s+(?:(?:West|East|North|South|W\.|E\.|N\.|S\.)\s+)?[A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+){0,4}', text)
    literals += re.findall(r'\[[rlam]\d+\]', text)
    for literal in sorted(set(literals), key=len, reverse=True):
        if literal not in text: continue
        key = f'ZXQ{len(protected):03}QXZ'
        protected[key] = literal
        text = text.replace(literal, key)
    return text, protected


def split_bytes(text, maximum=450):
    parts, current = [], ''
    for word in text.split():
        if len(word.encode('utf-8')) > maximum:
            raise ValueError('Un segmento non è traducibile senza alterare i codici.')
        candidate = f'{current} {word}'.strip()
        if len(candidate.encode('utf-8')) > maximum:
            parts.append(current); current = word
        else: current = candidate
    if current: parts.append(current)
    return parts


def italian_summary(notes):
    """Extract explicit catalogue statements; never infer missing characteristics."""
    points = []
    first = re.search(r'first pressing with (.+?) address', notes, re.I)
    later = re.search(r'(?:later|subsequent) (?:repress|reissue)[^\n]*?\b(?:has|with) (.+?) address', notes, re.I)
    if first: points.append(f'Prima stampa: indirizzo «{first[1]}» sul retrocopertina.')
    if later: points.append(f'Ristampa successiva: indirizzo «{later[1]}».')
    if re.search(r'this first pressing[^\n]*?\bhas a flower[^\n]*?runouts?', notes, re.I):
        points.append('La prima stampa presenta un fiore inciso nei solchi finali.')
    if re.search(r'repress[^\n]*?(?:does not|doesn.t|without)[^\n]*?flower', notes, re.I):
        points.append('La ristampa non presenta il fiore inciso nei solchi finali.')
    if re.search(r'\bgatefold\b', notes, re.I): points.append('Copertina apribile.')
    if re.search(r'\bglossy cover\b', notes, re.I): points.append('Copertina lucida.')
    if re.search(r'\bembossed[^\n]*?cover', notes, re.I): points.append('Copertina con elementi in rilievo.')
    if re.search(r'\bmisprint\b', notes, re.I): points.append('Le note segnalano un errore di stampa: confronta il testo originale per identificarlo.')
    if re.search(r'\binner sleeve', notes, re.I): points.append('Le note descrivono anche le buste interne; confrontale con la tua copia.')
    licensed = re.search(r'released under licen[cs]e from ([^\n]+)', notes, re.I)
    if licensed: points.append(f'Pubblicata su licenza di {licensed[1].rstrip(".")}.')
    return {'text': '\n'.join(points), 'status': 'summary' if points else 'unavailable', 'excerpt': True}


async def translate_notes(notes, identifiers=()):
    global _budget_day, _budget_used
    if not notes.strip(): return {'text': '', 'status': 'empty', 'excerpt': False}
    # Translate a concise excerpt; full source is always retained separately.
    excerpt = len(notes) > 1100
    text = notes[:1100]
    if excerpt and ' ' in text: text = text.rsplit(' ', 1)[0]
    italian = len(re.findall(r'\b(?:copertina|etichetta|stampato|inciso|ristampa|matrici|prima|italiana|busta)\b', text, re.I))
    if italian >= 3: return {'text': text, 'status': 'already_it', 'excerpt': excerpt}
    encoded, protected = protect_text(text, identifiers)
    key = hashlib.sha256(encoded.encode()).hexdigest()
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < 21600:
        translated = cached[1]
    else:
        async with _budget_lock:
            if date.today() != _budget_day: _budget_day, _budget_used = date.today(), 0
            if _budget_used + len(encoded) > 4500:
                return italian_summary(notes)
            _budget_used += len(encoded)
        try:
            chunks = split_bytes(encoded)
            output = []
            async with httpx.AsyncClient(timeout=10) as client:
                for chunk in chunks:
                    response = await client.get('https://api.mymemory.translated.net/get', params={'q': chunk, 'langpair': 'en|it'})
                    response.raise_for_status()
                    data = response.json()
                    translated_chunk = data.get('responseData', {}).get('translatedText', '')
                    if data.get('responseStatus') != 200 or data.get('quotaFinished') or not translated_chunk:
                        raise ValueError('Traduzione non disponibile')
                    output.append(html.unescape(translated_chunk))
            translated = ' '.join(output)
            if any(token not in translated for token in protected):
                raise ValueError('Il traduttore ha alterato un riferimento protetto.')
            _cache[key] = (time.monotonic(), translated)
            while len(_cache) > 128: _cache.popitem(last=False)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return italian_summary(notes)
    # Correct recurrent machine-translation errors in record terminology before
    # restoring protected labels, addresses and identifiers.
    corrections = [(r'\bpressatura\b', 'stampa'), (r'\bspremitura\b', 'stampa'),
                   (r'\bcamicia posteriore\b', 'retro della copertina'),
                   (r'\brunouts\b', 'solchi finali'), (r'\brunout\b', 'solco finale'),
                   (r'\brilasciato\b', 'pubblicato')]
    if re.search(r'\bpressing\b', text, re.I): corrections.append((r'\bpressione\b', 'stampa'))
    if re.search(r'\brepress\b', text, re.I): corrections.append((r'\brepressione\b', 'ristampa'))
    for pattern, target in corrections:
        translated = re.sub(pattern, lambda m: target.capitalize() if m[0][0].isupper() else target, translated, flags=re.I)
    for token, original in protected.items(): translated = translated.replace(token, original)
    return {'text': translated, 'status': 'translated', 'excerpt': excerpt}
