"""Digest health: which tracker accounts got BioLens's scheduled digest email, and whether anyone there has ever opened the app."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from django.core.cache import cache

from . import posthog

SENT, SKIPPED = 'digest_email_sent', 'digest_email_skipped'
REASONS = {'user_opted_out': 'opted out', 'no_companies': 'no companies in the digest'}


def _client():
    return ("person.properties.email IS NOT NULL AND person.properties.email LIKE '%@%' "
            "AND person.properties.email NOT LIKE '%@lunartree.bio'")


def digest_rows(days):
    """[(email, day, event, reason, n)] across both projects."""
    q = """SELECT person.properties.email, toDate(timestamp), event, properties.reason, count() FROM events
      WHERE timestamp >= now() - INTERVAL %d DAY AND event IN ('%s', '%s') AND %s GROUP BY 1, 2, 3, 4 LIMIT 20000""" % (days, SENT, SKIPPED, _client())
    return [r for _, rows in posthog.hql_all(q) for r in rows]


def last_opened():
    """{email: latest page view, all time}: a person with no entry has never opened the app."""
    q = ("SELECT person.properties.email, max(timestamp) FROM events WHERE event = '$pageview' AND %s GROUP BY 1 LIMIT 20000" % _client())
    out = {}
    for _, rows in posthog.hql_all(q):
        for email, ts in rows:
            email = email.lower()
            if email not in out or str(ts) > str(out[email]):
                out[email] = ts
    return out


def data(days):
    k = 'posthog-digests-%d' % days
    got = cache.get(k)
    if got is None:
        with ThreadPoolExecutor(2) as ex:
            r, o = ex.submit(digest_rows, days), ex.submit(last_opened)
            got = {'rows': r.result(), 'opened': o.result()}
        cache.set(k, got, 300)
    return got


def build(accounts, days):
    by_domain = posthog.by_domain_of(accounts)
    got = data(days)
    run_days = sorted({str(r[1])[:10] for r in got['rows']})  # days the job ran for anyone
    accts = {}
    for email, day, event, reason, n in got['rows']:
        email, day = email.lower(), str(day)[:10]
        a = posthog.match_account(email, by_domain)
        if not a:
            continue
        m = accts.setdefault(a.pk, {'account': a, 'days': defaultdict(lambda: {'sent': 0, 'skipped': 0, 'reasons': Counter()}), 'users': {}})
        d = m['days'][day]
        u = m['users'].setdefault(email, {'email': email, 'sent': 0, 'skipped': 0, 'reasons': Counter(), 'last_sent': '', 'last_try': '', 'last_event': ''})
        if event == SENT:
            d['sent'] += n; u['sent'] += n
            u['last_sent'] = max(u['last_sent'], day)
        else:
            d['skipped'] += n; u['skipped'] += n
            d['reasons'][reason or 'unknown'] += n; u['reasons'][reason or 'unknown'] += n
        if day >= u['last_try']:  # the latest day decides the dot; a send beats a skip on the same day
            u['last_event'] = SENT if (event == SENT or (day == u['last_try'] and u['last_event'] == SENT)) else SKIPPED
            u['last_try'] = day
    cards = []
    for m in accts.values():
        strip = []
        for day in run_days:
            d = m['days'].get(day)
            if d and d['sent']:
                state, tip = 'ok', '%d sent' % d['sent'] + (', %d skipped' % d['skipped'] if d['skipped'] else '')
            else:
                why = ', '.join(REASONS.get(r, r) for r in d['reasons']) if d else 'no digest for this account'
                state, tip = 'bad', 'Not sent: ' + why
            strip.append({'day': day, 'state': state, 'tip': '%s · %s' % (datetime.strptime(day, '%Y-%m-%d').strftime('%b %-d'), tip)})
        people = []
        for u in sorted(m['users'].values(), key=lambda u: u['email']):
            opened = got['opened'].get(u['email'])
            people.append(dict(u, state='ok' if u['last_event'] == SENT else 'bad', opened=str(opened)[:10] if opened else '',
                               why=', '.join(REASONS.get(r, r) for r in u['reasons']) if u['skipped'] else ''))
        receiving = [p for p in people if p['sent']]
        cards.append({'account': m['account'], 'strip': strip, 'people': people, 'sent': sum(p['sent'] for p in people),
                      'skipped': sum(p['skipped'] for p in people), 'receiving': len(receiving),
                      'never': sum(1 for p in receiving if not p['opened']), 'last': strip[-1]['state'] if strip else 'bad'})
    cards.sort(key=lambda c: (c['last'] == 'ok', -c['account'].furthest_stage, c['account'].name))
    covered = {c['account'].pk for c in cards}
    return {'cards': cards, 'run_days': len(run_days), 'first': run_days[0] if run_days else '', 'last_run': run_days[-1] if run_days else '',
            'receiving_accounts': sum(1 for c in cards if c['receiving']),
            'digest_only_accounts': sum(1 for c in cards if c['receiving'] and c['never'] == c['receiving']),
            'never_opened_people': sum(c['never'] for c in cards), 'people_receiving': sum(c['receiving'] for c in cards),
            'without': sorted((a for a in accounts if a.pk not in covered), key=lambda a: (-a.furthest_stage, a.name))}
