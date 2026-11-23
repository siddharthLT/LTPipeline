"""Finds coordinates for mapped companies that came without them, using OpenStreetMap's Nominatim.

Tries the full street address first, then falls back to city, state and country (marked 'city' so the map can say the pin is
approximate). Respects Nominatim's one request a second and only sends the address text. Safe to re-run: companies that already
have coordinates are skipped."""
import json
import time
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand

from pipeline.models import MappedCompany, world_region

URL = 'https://nominatim.openstreetmap.org/search?'
UA = 'LunartreePipeline/1.0 (internal company map)'


def search(query):
    qs = urllib.parse.urlencode({'q': query, 'format': 'json', 'limit': 1, 'addressdetails': 1, 'accept-language': 'en'})
    req = urllib.request.Request(URL + qs, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    time.sleep(1.1)
    return data[0] if data else None


class Command(BaseCommand):
    help = 'Geocode mapped companies that have an address or city but no coordinates'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        todo = [m for m in MappedCompany.objects.filter(latitude__isnull=True).order_by('name') if m.address or m.city]
        if opts['limit']:
            todo = todo[:opts['limit']]
        self.stdout.write('%d companies to geocode' % len(todo))
        done = failed = 0
        for m in todo:
            place = ', '.join(x for x in (m.city, m.state_name or m.state, m.country) if x)
            tries = []
            if m.address:
                tries.append((m.address, 'address'))
            if place and place != m.address:
                tries.append((place, 'city'))
            hit = None
            for query, kind in tries:
                try:
                    hit = search(query)
                except Exception as e:  # network hiccup: move on, a re-run picks it up
                    self.stderr.write('%s: %s' % (m.name, e))
                    hit = None
                if hit:
                    hit['kind'] = kind
                    break
            if not hit:
                failed += 1
                self.stdout.write('  no match: %s (%s)' % (m.name, m.address or place))
                continue
            country = (hit.get('address') or {}).get('country', '')
            if m.country and country and country != m.country and not (m.country in country or country in m.country):
                failed += 1
                self.stdout.write('  skipped, country mismatch: %s expected %s got %s' % (m.name, m.country, country))
                continue
            if not opts['dry_run']:
                m.latitude, m.longitude, m.geo_source = float(hit['lat']), float(hit['lon']), hit['kind']
                if not m.country and country:
                    m.country = country
                    m.world_region = world_region(country)
                m.save(update_fields=['latitude', 'longitude', 'geo_source', 'country', 'world_region'])
            done += 1
            if done % 25 == 0:
                self.stdout.write('  %d done' % done)
        self.stdout.write(self.style.SUCCESS('Located %d, no result for %d' % (done, failed)))
