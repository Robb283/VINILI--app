"""Opt-in live smoke checks. Never bundled with sample market prices.

Run from project root: PYTHONPATH=. python tests/live_check.py
Token is entered without echo and never stored.
"""
import asyncio
import getpass
import json
import os

from app.main import Assessment, assess, search


async def run():
    for artist, title in [('Pink Floyd', 'Animals'), ('Nirvana', 'Nevermind'), ('The Beatles', 'Abbey Road')]:
        found = await search(artist=artist, title=title, country='Germany', catno='', pressing='any', page=1)
        if not found['results']:
            print(json.dumps({'artist': artist, 'title': title, 'results': 0}))
            continue
        # Selecting the first result exercises the pipeline; it does not identify a physical copy.
        release = found['results'][0]
        result = await assess(Assessment(release_id=release['id'], asking_price=25, condition='VG+', confirmed=True))
        print(json.dumps({'selected_test_edition': release, 'assessment': result}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    os.environ['DISCOGS_TOKEN'] = getpass.getpass('Discogs server token (not saved): ')
    # This opt-in check exercises data access locally; it does not enable public data redistribution.
    os.environ['ENABLE_MARKET_DATA'] = 'true'
    asyncio.run(run())
