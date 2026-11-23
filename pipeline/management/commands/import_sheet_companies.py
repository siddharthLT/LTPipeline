"""Adds companies from the master sheet's CDMO, CRO, Equipment and packaging, and Reagents and instruments tabs to the mapped
universe when they are in neither the pipeline nor the mapped universe.

Takes the tabs as CSV exports (company in column D, segment E, sub-type F, HQ country G, website I). Segment comes from the
sheet. Where the Company Map knows the company (matched on website, then name) its address and coordinates come along; the rest
are left for the geocoder once an address or city is known. Re-runnable: sheet rows are keyed on a map_id derived from
the domain, starting at SHEET_ID_BASE so they never collide with Company Map ids, so they update rather than duplicate."""
import csv
import zlib
from collections import defaultdict

import psycopg
from django.core.management.base import BaseCommand

from pipeline.models import Account, MappedCompany, world_region

from .import_mapped_universe import ALIASES, host, name_key, root

SHEET_ID_BASE = 10000000


class Command(BaseCommand):
    help = 'Add master-sheet companies that are not in the pipeline or the mapped universe'

    def add_arguments(self, parser):
        parser.add_argument('csv', nargs='+', help='CSV exports of the four tabs')
        parser.add_argument('--env', default='~/emailcounter/.env')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        import os
        rows = []
        for path in opts['csv']:
            for r in list(csv.reader(open(path)))[1:]:
                if len(r) >= 9 and r[3].strip():
                    rows.append(dict(name=r[3].strip(), seg=r[4].strip(), sub=r[5].strip(), country=r[6].strip(), site=r[8].strip(),
                                     tab=os.path.basename(path)))
        known_dom, known_name = set(), set()
        for m in MappedCompany.objects.all():
            known_dom.add(root(m.domain or host(m.url)))
            known_name.add(name_key(m.name))
        for a in Account.objects.all():
            known_dom.add(root(a.domain))
            known_name.add(name_key(a.name))
        known_dom.discard('')
        cm = self.company_map(opts['env'])
        created = updated = 0
        seen = set()
        for r in rows:
            d = ALIASES.get(root(host(r['site'])), root(host(r['site'])))
            if d in known_dom or name_key(r['name']) in known_name or (d or name_key(r['name'])) in seen:
                continue
            seen.add(d or name_key(r['name']))
            m = (cm['dom'].get(d) or cm['name'].get(name_key(r['name'])) or [None])[0] if cm else None
            country = r['country'] or (m or {}).get('country') or ''
            vals = dict(name=r['name'][:200], domain=d[:120], url=r['site'][:300], segment=r['seg'][:40], sub_type=r['sub'][:120],
                        country=country[:80], world_region=world_region(country, (m or {}).get('region') or ''),
                        source='Master sheet: ' + r['tab'][:60])
            if m:
                vals.update(address=(m['address'] or '')[:300], city=(m['city'] or '')[:120], state=(m['state'] or '')[:60],
                            state_name=(m['state_name'] or '')[:80], postal_code=(m['zip'] or '')[:20])
                if m['lat'] is not None and m['lng'] is not None:
                    vals.update(latitude=float(m['lat']), longitude=float(m['lng']), geo_source='source')
            if opts['dry_run']:
                created += 1
                continue
            map_id = SHEET_ID_BASE + zlib.crc32((d or name_key(r['name'])).encode()) % 2000000000
            _, was_new = MappedCompany.objects.update_or_create(map_id=map_id, defaults=vals)
            created += was_new
            updated += not was_new
        self.stdout.write(self.style.SUCCESS('%d rows read; %d added, %d updated' % (len(rows), created, updated)))

    def company_map(self, env_path):
        import os
        try:
            env = dict(l.rstrip('\n').split('=', 1) for l in open(os.path.expanduser(env_path)) if '=' in l and not l.startswith('#'))
            con = psycopg.connect(env['DATABASE_URL'].strip().strip('"\''), connect_timeout=20)
            con.read_only = True
        except Exception as e:
            self.stderr.write('Company Map not reachable, continuing without it: %s' % e)
            return None
        cur = con.cursor()
        cur.execute('SELECT name, url, domain, city, state_code, state_name, country, address, postal_code, latitude, longitude, region '
                    'FROM companymap_company')
        keys = ['name', 'url', 'domain', 'city', 'state', 'state_name', 'country', 'address', 'zip', 'lat', 'lng', 'region']
        out = {'dom': defaultdict(list), 'name': defaultdict(list)}
        for row in cur.fetchall():
            r = dict(zip(keys, row))
            out['dom'][root(r['domain'] or host(r['url']))].append(r)
            out['name'][name_key(r['name'])].append(r)
        out['dom'].pop('', None)
        return out
