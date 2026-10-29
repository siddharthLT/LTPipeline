"""Product usage from PostHog, joined to tracker accounts by email domain."""
import json
import os
import urllib.request
from collections import defaultdict

from django.core.cache import cache

ACTIONS = [
    ('outreach:email_used', 'Emails sent'),
    ('decision_makers:list_downloaded', 'DM lists downloaded'),
    ('decision_makers:added', 'DMs added'),
    ('workspace_companies:account_status_changed', 'Status changes'),
    ('workspace_companies:internal_score_updated', 'Scores updated'),
    ('workspace_companies:lead_assigned', 'Leads assigned'),
    ('workspace_companies:company_added', 'Added to workspace'),
    ('workspace:created', 'Workspaces created'),
]
SHORT = ['Emails', 'DM DL', 'DM +', 'Status', 'Score', 'Lead', 'Add WS', 'WS new']
ALL_EVENTS = [e for e, _ in ACTIONS] + [
    'outreach:email_abandoned', 'decision_makers:removed', 'workspace_companies:filter_applied',
    'chat:user_message_submit', 'chat:download_report_click',
]
ACTION_EVENTS = [e for e, _ in ACTIONS]
AI_EVENTS = ['chat:response_received', 'chat:user_message_submit']
# Extra email domains that belong to a tracker account (domain on the account is matched automatically).
ALIASES = {'tenshi.co.in': 'insta-pill.com', 'arcolab.com': 'insta-pill.com', 'synthegoreagents.com': 'synthego.com', 'shilpabio.com': 'shilpa.com'}


class NotConfigured(Exception):
    pass


def _in(events):
    return ','.join("'%s'" % e for e in events)


def hql(query):
    key = os.environ.get('POSTHOG_API_KEY')
    if not key:
        raise NotConfigured('POSTHOG_API_KEY is not set')
    host = os.environ.get('POSTHOG_HOST', 'https://us.posthog.com')
    pid = os.environ.get('POSTHOG_PROJECT_ID', '234813')
    req = urllib.request.Request(
        '%s/api/projects/%s/query/' % (host, pid),
        data=json.dumps({'query': {'kind': 'HogQLQuery', 'query': query}}).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get('results', [])


def _where(days):
    return ("timestamp >= now() - INTERVAL %d DAY AND person.properties.email IS NOT NULL "
            "AND person.properties.email LIKE '%%@%%' AND person.properties.email NOT LIKE '%%@lunartree.bio'" % days)


def user_rows(days):
    q = """SELECT person.properties.email AS email, any(person.properties.name) AS name,
      countIf(event IN (%(all)s)) AS evts, countDistinct(properties.`$session_id`) AS sessions,
      countIf(event IN (%(act)s)) AS acts, countIf(event IN (%(ai)s)) AS ai,
      countIf(event = '$rageclick') AS rage, countIf(event = '$pageview') AS pvs,
      countDistinct(CASE WHEN event IN (%(all)s) THEN event END) AS feats,
      max(timestamp) AS last_seen, countIf(event = 'company_profile:assessment_viewed') AS profiles
      FROM events WHERE %(w)s GROUP BY email ORDER BY evts DESC LIMIT 500""" % {
        'all': _in(ALL_EVENTS), 'act': _in(ACTION_EVENTS), 'ai': _in(AI_EVENTS), 'w': _where(days)}
    keys = ['email', 'name', 'evts', 'sessions', 'acts', 'ai', 'rage', 'pvs', 'feats', 'last_seen', 'profiles']
    return [dict(zip(keys, r)) for r in hql(q)]


def daily_rows(days):
    cols = ','.join("countIf(event = '%s')" % e for e in ACTION_EVENTS)
    q = """SELECT toDate(timestamp) AS day, person.properties.email AS email, countIf(event = '$pageview') AS pvs,
      %s, countIf(event IN (%s)) AS total FROM events WHERE %s GROUP BY day, email
      ORDER BY day DESC, total DESC LIMIT 600""" % (cols, _in(ALL_EVENTS), _where(days))
    return hql(q)


def usage(days):
    """Cached users and daily rows for the window."""
    k = 'posthog-usage-%d' % days
    data = cache.get(k)
    if data is None:
        data = {'users': user_rows(days), 'daily': daily_rows(days)}
        cache.set(k, data, 300)
    return data


def domain_of(email):
    return (email or '').rsplit('@', 1)[-1].lower().strip()


def match_account(email, by_domain):
    d = domain_of(email)
    d = ALIASES.get(d, d)
    if d in by_domain:
        return by_domain[d]
    parts = d.split('.')
    for i in range(1, len(parts) - 1):  # sub.domain.com -> domain.com
        if '.'.join(parts[i:]) in by_domain:
            return by_domain['.'.join(parts[i:])]
    return None


def tier(u):
    if u['acts'] >= 3 and u['feats'] >= 4:
        return 'Power'
    if u['acts'] >= 1 or (u['evts'] > 50 and u['feats'] >= 3):
        return 'Active'
    if u['evts'] > 10:
        return 'Browser'
    return 'Low'


def join(accounts, days):
    """Group usage by tracker account. Returns (matched rows, unmatched domains, daily by account pk)."""
    by_domain = {}
    for a in accounts:
        d = (a.domain or '').lower().replace('https://', '').replace('http://', '').replace('www.', '').strip('/')
        if d:
            by_domain[d] = a
    data = usage(days)
    matched, other = {}, defaultdict(lambda: {'users': 0, 'evts': 0, 'acts': 0, 'emails': []})
    email_acct = {}
    for u in data['users']:
        u['tier'] = tier(u)
        a = match_account(u['email'], by_domain)
        email_acct[u['email']] = a
        if a:
            m = matched.setdefault(a.pk, {'account': a, 'users': [], 'evts': 0, 'sessions': 0, 'acts': 0,
                                          'ai': 0, 'rage': 0, 'profiles': 0, 'last_seen': None, 'feats': 0})
            m['users'].append(u)
            for k in ('evts', 'sessions', 'acts', 'ai', 'rage', 'profiles'):
                m[k] += u[k]
            m['feats'] = max(m['feats'], u['feats'])
            if u['last_seen'] and (not m['last_seen'] or u['last_seen'] > m['last_seen']):
                m['last_seen'] = u['last_seen']
        else:
            o = other[domain_of(u['email'])]
            o['users'] += 1; o['evts'] += u['evts']; o['acts'] += u['acts']; o['emails'].append(u['email'])
    rows = sorted(matched.values(), key=lambda m: -m['evts'])
    unmatched = sorted(({'domain': d, **v} for d, v in other.items()), key=lambda x: -x['evts'])
    daily = []
    for r in data['daily']:
        a = email_acct.get(r[1])
        daily.append({'day': str(r[0])[:10], 'email': r[1], 'account': a, 'pvs': r[2],
                      'counts': r[3:3 + len(ACTIONS)], 'total': r[-1]})
    totals = {'users': len(data['users']), 'matched_users': sum(len(m['users']) for m in rows),
              'evts': sum(u['evts'] for u in data['users']), 'acts': sum(u['acts'] for u in data['users']),
              'ai': sum(u['ai'] for u in data['users']), 'rage': sum(u['rage'] for u in data['users'])}
    return rows, unmatched, daily, totals
