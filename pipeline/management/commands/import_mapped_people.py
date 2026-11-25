"""Copies the people the Company Map holds (read only) onto the mapped companies they work at.

Only people the Company Map links to a company are copied; people matched just by email domain or name are left out.
A person is kept when their company is a mapped company, or an account in the pipeline (found by domain).
Safe to re-run: people are matched on their Company Map id, new ones are added and empty fields on existing ones are filled in."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from pipeline.management.commands.import_mapped_universe import ALIASES, host, root
from pipeline.models import MappedCompany, MappedPerson

PEOPLE = """SELECT p.id, p.name, p.title, p.email, p.phone, p.linkedin_url, p.stakeholder_role, p.company_id, p.prior_connections::text,
            coalesce(nullif(c.domain, ''), c.url) FROM contactdb_person p JOIN companymap_company c ON c.id = p.company_id
            ORDER BY p.id"""


def clean_url(value):
    value = (value or '').strip()
    if value and not value.lower().startswith(('http://', 'https://')):
        value = 'https://' + value
    return value[:500]


def warm_names(raw):
    """'["Vedant", "PK"]' -> 'Vedant, PK'"""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return ''
    data = data if isinstance(data, list) else [data]
    return ', '.join(dict.fromkeys(str(x).strip() for x in data if isinstance(x, str) and x.strip()))[:200]


def fetch(env_path):
    """Rows from the Company Map database, as dicts."""
    import psycopg
    env = {}
    for line in Path(env_path).read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"\'')
    if not env.get('DATABASE_URL'):
        raise CommandError('No DATABASE_URL in %s' % env_path)
    keys = ['id', 'name', 'title', 'email', 'phone', 'linkedin', 'role', 'company_id', 'prior', 'site']
    with psycopg.connect(env['DATABASE_URL'], connect_timeout=20) as conn:
        conn.read_only = True
        return [dict(zip(keys, r)) for r in conn.execute(PEOPLE).fetchall()]


class Command(BaseCommand):
    help = 'Import the people at mapped companies from the Company Map database'

    def add_arguments(self, parser):
        parser.add_argument('--env', default=str(Path.home() / 'emailcounter' / '.env'), help='.env holding the Company Map DATABASE_URL')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        rows = fetch(opts['env'])
        by_map = {m.map_id: m for m in MappedCompany.objects.all()}
        by_domain = {}
        for m in MappedCompany.objects.exclude(domain=''):
            by_domain.setdefault(m.domain, m)
        have = {p.source_id: p for p in MappedPerson.objects.all()}
        new, filled, seen, skipped = [], [], set(), {'no company in the tracker': 0, 'duplicate': 0, 'no name': 0}
        for r in rows:
            name = (r['name'] or '').strip()
            if not name:
                skipped['no name'] += 1
                continue
            dom = root(host(r['site'] or ''))
            dom = ALIASES.get(dom, dom)
            company = by_map.get(r['company_id']) or (by_domain.get(dom) if dom else None)
            if company is None:
                skipped['no company in the tracker'] += 1
                continue
            email = (r['email'] or '').strip().lower()
            email = email[:254] if '@' in email else ''
            linkedin = clean_url(r['linkedin'])
            key = (company.pk, email or linkedin.lower() or name.lower())
            if key in seen and r['id'] not in have:
                skipped['duplicate'] += 1
                continue
            seen.add(key)
            vals = dict(company=company, domain=(company.domain or dom)[:253], name=name[:200], title=(r['title'] or '').strip()[:300],
                        email=email, warm_via=warm_names(r.get('prior')), phone=(r['phone'] or '').strip()[:60], linkedin_url=linkedin, role=(r['role'] or '')[:30])
            person = have.get(r['id'])
            if person is None:
                new.append(MappedPerson(source_id=r['id'], **vals))
                continue
            changed = False
            for k, v in vals.items():
                if v and not getattr(person, k):  # fill gaps, never overwrite
                    setattr(person, k, v)
                    changed = True
            if changed:
                filled.append(person)
        self.stdout.write('%d people to add, %d existing to fill in; skipped %s' % (len(new), len(filled), skipped))
        if opts['dry_run']:
            return
        MappedPerson.objects.bulk_create(new, batch_size=500)
        if filled:
            MappedPerson.objects.bulk_update(filled, ['company', 'domain', 'title', 'email', 'phone', 'linkedin_url', 'role', 'warm_via'], batch_size=500)
        self.stdout.write(self.style.SUCCESS('Added %d, updated %d' % (len(new), len(filled))))
