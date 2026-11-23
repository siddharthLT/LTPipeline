"""Fills the mapped universe from the Company Map database (read only) and copies its logo URLs onto pipeline accounts.

Keeps CDMO, CRO, CDMO/CRO, reagent, packaging, instrument and equipment suppliers, drops medical-device makers filed
under Equipment and software or lab-service firms filed under CRO, and leaves out anything already in the pipeline.
Safe to re-run: rows are matched on the Company Map id, and logos already set are not overwritten."""
import os
import re
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from pipeline.models import Account, MappedCompany, world_region

KEEP = {'CDMO', 'CRO', 'CDMO/CRO', 'Reagents', 'Packaging', 'Instruments', 'Equipment/Reagent', 'Equipment'}
NOT_CRO = {'information technology & services', 'hospital & health care', 'medical practice', 'management consulting',
           'design', 'financial services'}
# Same company under a different website in the map: map domain -> pipeline domain
ALIASES = {'shilpabio.com': 'shilpa.com'}
STOP = (r'\b(inc|llc|ltd|limited|corp|corporation|co|company|gmbh|sa|ag|plc|group|holdings|the|pharma|pharmaceuticals?|'
        r'biologics?|sciences?|biosciences?|laboratories|labs?|solutions|services)\b')

QUERY = """SELECT id, name, coalesce(nullif(domain, ''), url), url, logo_url, segment, industry, sub_type, product_category,
           city, state_code, country, employee_count, linkedin_url, account_list_source, address, postal_code, state_name,
           latitude, longitude, region FROM companymap_company"""


def host(value):
    value = re.sub(r'^https?://', '', (value or '').strip().lower())
    return re.sub(r'^www\.', '', value).split('/')[0].split('?')[0]


def root(domain):
    parts = domain.split('.')
    return '.'.join(parts[-3:]) if len(parts) >= 3 and parts[-2] in ('co', 'com', 'org') else '.'.join(parts[-2:])


def name_key(value):
    return re.sub(r'\s+', ' ', re.sub(STOP, ' ', re.sub(r'[^a-z0-9 ]', ' ', (value or '').lower()))).strip()


def keep(row):
    segment, industry = row['segment'], row['industry'] or ''
    if segment not in KEEP:
        return False
    if segment == 'Equipment' and industry == 'medical devices':
        return False
    if segment in ('CRO', 'CDMO/CRO') and industry in NOT_CRO:
        return False
    return True


class Command(BaseCommand):
    help = 'Import the mapped universe from the Company Map database'

    def add_arguments(self, parser):
        parser.add_argument('--env', default=str(Path.home() / 'emailcounter' / '.env'), help='.env holding the Company Map DATABASE_URL')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        import psycopg
        env = {}
        for line in Path(opts['env']).read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"\'')
        if not env.get('DATABASE_URL'):
            raise CommandError('No DATABASE_URL in %s' % opts['env'])
        keys = ['id', 'name', 'dom', 'url', 'logo', 'segment', 'industry', 'sub_type', 'pc', 'city', 'state', 'country', 'emp', 'li', 'src', 'addr', 'zip', 'state_name', 'lat', 'lng', 'region']
        with psycopg.connect(env['DATABASE_URL'], connect_timeout=20) as conn:
            conn.read_only = True
            rows = [dict(zip(keys, r)) for r in conn.execute(QUERY).fetchall()]
        for r in rows:
            r['dom'] = root(host(r['dom']))
            r['dom'] = ALIASES.get(r['dom'], r['dom'])

        accounts = list(Account.objects.all())
        pipe_dom = {root(host(a.domain)): a for a in accounts}
        pipe_name = {name_key(a.name): a for a in accounts}
        in_pipeline, logos = set(), {}
        for r in rows:
            a = pipe_dom.get(r['dom']) if r['dom'] else None
            a = a or pipe_name.get(name_key(r['name']))
            if a:
                in_pipeline.add(r['id'])
                if r['logo'] and a.pk not in logos:
                    logos[a.pk] = r['logo']

        seen, fresh = set(), []
        for r in rows:
            if r['id'] in in_pipeline or not keep(r):
                continue
            key = r['dom'] or 'n:' + name_key(r['name'])
            if key in seen:
                continue
            seen.add(key)
            fresh.append(r)
        by_seg = defaultdict(int)
        for r in fresh:
            by_seg[r['segment']] += 1
        self.stdout.write('%d companies for the mapped universe %s' % (len(fresh), dict(by_seg)))
        self.stdout.write('%d of %d pipeline accounts found in the map; %d have a logo there' % (len(in_pipeline & {r['id'] for r in rows}), len(accounts), len(logos)))
        if opts['dry_run']:
            return

        existing = {m.map_id: m for m in MappedCompany.objects.all()}
        new, changed = [], []
        for r in fresh:
            vals = dict(name=r['name'][:200], domain=r['dom'][:253], url=(r['url'] or '')[:500], segment=r['segment'],
                        sub_type=(r['sub_type'] or '')[:200], product_category=r['pc'] or '', city=(r['city'] or '')[:120],
                        state=(r['state'] or '')[:60], country=(r['country'] or '')[:80], employee_count=r['emp'],
                        linkedin_url=(r['li'] or '')[:500], source=(r['src'] or '')[:200], address=(r['addr'] or '')[:300],
                        postal_code=(r['zip'] or '')[:20], state_name=(r['state_name'] or '')[:80],
                        world_region=world_region(r['country'] or '', r['region'] or ''))
            if r['lat'] is not None and r['lng'] is not None:  # coordinates that came with the map; geocoded ones are kept otherwise
                vals.update(latitude=float(r['lat']), longitude=float(r['lng']), geo_source='source')
            m = existing.get(r['id'])
            if m is None:
                new.append(MappedCompany(map_id=r['id'], logo_url=(r['logo'] or '')[:500], **vals))
                continue
            for k, v in vals.items():
                setattr(m, k, v)
            if not m.logo_url and r['logo']:
                m.logo_url = r['logo'][:500]
            changed.append(m)
        MappedCompany.objects.bulk_create(new, batch_size=500)
        if changed:
            MappedCompany.objects.bulk_update(changed, [f.name for f in MappedCompany._meta.fields if f.name not in ('id', 'map_id')], batch_size=500)
        # companies that have since joined the pipeline leave the universe
        MappedCompany.objects.filter(map_id__in=in_pipeline).delete()
        have = {a.pk: a for a in accounts if a.logo_url}
        todo = [a for a in accounts if a.pk not in have and a.pk in logos]
        for a in todo:
            a.logo_url = logos[a.pk][:500]
        Account.objects.bulk_update(todo, ['logo_url'])
        self.stdout.write(self.style.SUCCESS('Created %d, updated %d; logos copied to %d pipeline accounts' % (len(new), len(changed), len(todo))))
