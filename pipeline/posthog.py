"""Product usage from PostHog, joined to tracker accounts by email domain."""
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

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


def project_ids():
    """PostHog projects to read: app-prod (our usual data) and lunartree-neuland-prod (Neuland's usage)."""
    return [int(p) for p in os.environ.get('POSTHOG_PROJECT_IDS', '234813,600726').split(',') if p.strip()]


def hql(query, pid):
    key = os.environ.get('POSTHOG_API_TRACKER') or os.environ.get('POSTHOG_API_KEY')
    if not key:
        raise NotConfigured('POSTHOG_API_TRACKER is not set')
    host = os.environ.get('POSTHOG_HOST', 'https://us.posthog.com')
    req = urllib.request.Request(
        '%s/api/projects/%s/query/' % (host, pid),
        data=json.dumps({'query': {'kind': 'HogQLQuery', 'query': query}}).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    for attempt in range(3):  # PostHog now and then answers 502/503/504 or drops the connection; a retry usually works
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get('results', [])
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(1.5 * (attempt + 1))


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
    merged = {}
    for pid in project_ids():
        for u in (dict(zip(keys, r)) for r in hql(q, pid)):
            m = merged.get(u['email'])  # the same person can appear in more than one project
            if not m:
                merged[u['email']] = u
                continue
            for k in ('evts', 'sessions', 'acts', 'ai', 'rage', 'pvs', 'profiles'):
                m[k] += u[k]
            m['feats'] = max(m['feats'], u['feats'])
            m['name'] = m['name'] or u['name']
            if str(u['last_seen']) > str(m['last_seen']):
                m['last_seen'] = u['last_seen']
    return sorted(merged.values(), key=lambda u: -u['evts'])


def daily_rows(days):
    cols = ','.join("countIf(event = '%s')" % e for e in ACTION_EVENTS)
    q = """SELECT toDate(timestamp) AS day, person.properties.email AS email, countIf(event = '$pageview') AS pvs,
      %s, countIf(event IN (%s)) AS total FROM events WHERE %s GROUP BY day, email
      ORDER BY day DESC, total DESC LIMIT 5000""" % (cols, _in(ALL_EVENTS), _where(days))
    merged = {}
    for pid in project_ids():
        for r in hql(q, pid):
            m = merged.get((str(r[0]), r[1]))
            if not m:
                merged[(str(r[0]), r[1])] = list(r)
                continue
            for i in range(2, len(r)):  # pageviews, each action count, total
                m[i] += r[i]
    return sorted(merged.values(), key=lambda r: (str(r[0]), r[-1]), reverse=True)


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
    if u['evts'] > 10 or u['pvs'] >= 10:
        return 'Browser'
    return 'Low'


def by_domain_of(accounts):
    out = {}
    for a in accounts:
        d = (a.domain or '').lower().replace('https://', '').replace('http://', '').replace('www.', '').strip('/')
        if d:
            out[d] = a
    return out


def join(accounts, days):
    """Group usage by tracker account. Returns (matched rows, unmatched domains, daily by account pk)."""
    by_domain = by_domain_of(accounts)
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


# ---- shapes for the visual overview ----

def initials(name, email):
    words = [w for w in re.split(r'[\s._-]+', (name or '').strip()) if w]
    if len(words) < 2:
        words = [w for w in re.split(r'[\s._+-]+', (email or '').split('@')[0]) if w] or ['?']
    return (words[0][0] + (words[1][0] if len(words) > 1 else '')).upper()


def shape(rows, daily, days):
    """Pulse series, feature totals, tier mix and per-account heat strips from the cached rows."""
    today = datetime.now(timezone.utc).date()
    span = [(today - timedelta(days=i)).isoformat() for i in range(days, -1, -1)]
    pulse = {d: {'day': d, 'total': 0, 'acts': 0, 'users': set()} for d in span}
    names = {d: (today - timedelta(days=days - i)).strftime('%b %-d') for i, d in enumerate(span)}
    feats = [0] * len(ACTIONS)
    per_acct = defaultdict(lambda: defaultdict(int))
    for r in daily:
        p = pulse.get(r['day'])
        if not p:
            continue
        p['total'] += r['total'] + r['pvs']; p['acts'] += sum(r['counts']); p['users'].add(r['email'])
        for i, c in enumerate(r['counts']):
            feats[i] += c
        if r['account']:
            per_acct[r['account'].pk][r['day']] += r['total'] + r['pvs']
    series = []
    peak = max([p['total'] for p in pulse.values()] + [1])
    for d in span:
        p = pulse[d]
        series.append({'day': d, 'label': names[d], 'total': p['total'], 'acts': p['acts'], 'users': len(p['users']),
                       'h': round(p['total'] / peak * 100, 1), 'share': round(p['acts'] / p['total'] * 100) if p['total'] else 0})
    users = [u for m in rows for u in m['users']]
    feature_rows = [{'label': label, 'n': n} for (_, label), n in zip(ACTIONS, feats)]
    feature_rows += [{'label': 'AI messages', 'n': sum(u['ai'] for u in users)},
                     {'label': 'Company profiles read', 'n': sum(u['profiles'] for u in users)}]
    feature_rows.sort(key=lambda f: -f['n'])
    top = max([f['n'] for f in feature_rows] + [1])
    for f in feature_rows:
        f['w'] = round(f['n'] / top * 100, 1)
    mix = [{'tier': t, 'n': sum(1 for u in users if u['tier'] == t)} for t in ('Power', 'Active', 'Browser', 'Low')]
    cards = []
    for m in rows:
        v = per_acct.get(m['account'].pk, {})
        hi = max(v.values()) if v else 1
        strip = [{'day': d, 'label': names[d], 'n': v.get(d, 0),
                  'lvl': 0 if not v.get(d) else 1 + min(3, int(4 * v[d] / (hi + 1)))} for d in span]
        cards.append(dict(m, strip=strip, active_days=sum(1 for c in strip if c['n']),
                          people=[{'ini': initials(u['name'], u['email']), 'who': u['name'] or u['email'], 'tier': u['tier']}
                                  for u in sorted(m['users'], key=lambda u: -u['evts'])]))
    cards.sort(key=lambda c: (-c['active_days'], -c['sessions'], c['account'].name))
    return {'series': series, 'peak': peak, 'features': feature_rows, 'mix': mix, 'cards': cards,
            'unused': [f['label'] for f in feature_rows if not f['n']],
            'active_users': len({r['email'] for r in daily}), 'first': names[span[0]], 'last': names[span[-1]]}


# ---- who is on BioLens right now ----

LIVE_MINUTES = 5


def live(accounts):
    """Client users with an event in the last few minutes, across both projects, newest first. Cached for 30 seconds."""
    people = cache.get('posthog-live')
    if people is None:
        q = """SELECT person.properties.email, any(person.properties.name), max(timestamp),
          argMax(properties.`$current_url`, timestamp), argMax(properties.`$session_id`, timestamp)
          FROM events WHERE %s GROUP BY person.properties.email LIMIT 200""" % _where(0).replace(
            'timestamp >= now() - INTERVAL 0 DAY', 'timestamp >= now() - INTERVAL %d MINUTE' % LIVE_MINUTES)
        merged = {}
        for pid in project_ids():
            for email, name, last, url, sid in hql(q, pid):
                email = email.lower()
                if email not in merged or str(last) > str(merged[email]['last']):
                    merged[email] = {'email': email, 'name': name or '', 'last': last, 'area': area_of(url) or 'BioLens',
                                     'replay': replay_url(sid, pid) if sid else ''}
        people = sorted(merged.values(), key=lambda p: str(p['last']), reverse=True)
        cache.set('posthog-live', people, 30)
    by_domain = by_domain_of(accounts)
    now = datetime.now(timezone.utc)
    out = []
    for p in people:
        acct = match_account(p['email'], by_domain)
        out.append({'who': p['name'] or p['email'], 'email': p['email'], 'account': acct.name if acct else '', 'area': p['area'],
                    'ago': max(0, int((now - _when(p['last'])).total_seconds())), 'replay': p['replay']})
    return out


# ---- session recordings ----

REPLAY_RETENTION_DAYS = 30
# Page areas, read from the URLs a session visited. First match wins.
AREAS = [
    (r'^(login|register|signup|reset-password|update-password)', 'Signing in'),
    (r'^biolens/products', 'Products'),
    (r'^biolens/workspaces/[^/]+/companies', 'Workspace companies'),
    (r'^biolens/workspaces/[^/]+/conference', 'Conferences'),
    (r'^biolens/workspaces/[^/]+/funnel', 'Funnel'),
    (r'^biolens/workspaces', 'Workspaces'),
    (r'^biolens/companies', 'Company profile'),
    (r'^biolens/all-accounts', 'All accounts'),
    (r'^biolens/insights', 'Insights'),
    (r'^biolens/signals', 'Signals'),
    (r'^biolens/r-d', 'R&D'),
    (r'^biolens/create', 'Create'),
    (r'^biolens/team-setup', 'Team setup'),
    (r'^biolens/admin/digests', 'Digests'),
    (r'^biolens/notifications', 'Notifications'),
    (r'^biolens/users', 'Users'),
    (r'^biolens/?$', 'Home'),
]
# Events worth a mark on the timeline: event -> (what the person did, kind of mark)
MOMENTS = {
    'outreach:email_used': ('Sent an email', 'act'),
    'decision_makers:list_downloaded': ('Downloaded a DM list', 'act'),
    'decision_makers:added': ('Added DMs', 'act'),
    'workspace_companies:account_status_changed': ('Changed a status', 'act'),
    'workspace_companies:internal_score_updated': ('Scored an account', 'act'),
    'workspace_companies:lead_assigned': ('Assigned a lead', 'act'),
    'workspace_companies:company_added': ('Added a company', 'act'),
    'workspace:created': ('Created a workspace', 'act'),
    'chat:download_report_click': ('Downloaded a report', 'act'),
    'chat:user_message_submit': ('Asked AI', 'ai'),
    'company_profile:ask_ai_click': ('Asked AI', 'ai'),
    'company_profile:viewed': ('Viewed a company', 'view'),
    'company_profile:assessment_viewed': ('Read an assessment', 'view'),
    '$rageclick': ('Rage click', 'rage'),
    '$pageview': (None, 'nav'),
}
MARK_RANK = {'rage': 4, 'act': 3, 'ai': 3, 'view': 2, 'nav': 1}
# Recording length buckets, light to deep teal as they get longer
BUCKETS = [('blip', 'Under 30s', 30), ('short', '30s to 2 min', 120), ('mid', '2 to 10 min', 600),
           ('long', '10 to 30 min', 1800), ('deep', '30 min +', 10 ** 9)]


def bucket(sec):
    for key, _, top in BUCKETS:
        if sec < top:
            return key


def area_of(url):
    path = re.sub(r'^https?://[^/]+/?', '', url or '').split('?')[0].split('#')[0].lower()
    for pat, label in AREAS:
        if re.match(pat, path):
            return label
    return None


def replay_url(session_id, pid):
    return '%s/project/%s/replay/%s' % (os.environ.get('POSTHOG_HOST', 'https://us.posthog.com'), pid, session_id)


def _when(s):
    return datetime.fromisoformat(str(s).replace('Z', '+00:00'))


def _title(moments, areas):
    said = [m for kind in ('act', 'ai', 'view') for m in moments if m[1] == kind]
    labels = list(dict.fromkeys(l for l, _ in said))
    if labels:
        return ' · '.join(labels[:2])
    seen = [a for a in areas if a != 'Signing in']
    if seen:
        return 'Browsed ' + ', '.join(seen[:2])
    return 'Sign-in only' if areas else 'Quick visit'


def recordings(days):
    """Cached replay sessions for the window, each with the person, the pages it visited and a timeline of marks."""
    days = min(days, REPLAY_RETENTION_DAYS)  # PostHog deletes footage after 30 days; scanning 90 days of events only makes the query time out (503)
    k = 'posthog-recordings-%d' % days
    data = cache.get(k)
    if data is not None:
        return data
    q = """SELECT s.session_id, s.start_time, s.end_time, s.active_milliseconds, s.click_count, s.keypress_count,
      s.console_error_count, s.first_url, s.all_urls, s.retention_period_days, e.email, e.name, e.country, e.browser, e.os, e.device
      FROM session_replay_events s LEFT JOIN (
        SELECT properties.`$session_id` AS sid,
          argMaxIf(person.properties.email, timestamp, person.properties.email IS NOT NULL) AS email,
          argMaxIf(person.properties.name, timestamp, person.properties.name IS NOT NULL) AS name,
          argMaxIf(person.properties.`$geoip_country_name`, timestamp, person.properties.`$geoip_country_name` IS NOT NULL) AS country,
          argMaxIf(person.properties.`$browser`, timestamp, person.properties.`$browser` IS NOT NULL) AS browser,
          argMaxIf(person.properties.`$os`, timestamp, person.properties.`$os` IS NOT NULL) AS os,
          argMaxIf(person.properties.`$device_type`, timestamp, person.properties.`$device_type` IS NOT NULL) AS device
        FROM events WHERE timestamp >= now() - INTERVAL %(d)d DAY GROUP BY sid) e ON s.session_id = e.sid
      WHERE s.start_time >= now() - INTERVAL %(d)d DAY AND e.email IS NOT NULL AND e.email LIKE '%%@%%'
        AND e.email NOT LIKE '%%@lunartree.bio'
      ORDER BY s.start_time DESC LIMIT 1500""" % {'d': days + 1}
    sessions = [(pid,) + tuple(r) for pid in project_ids() for r in hql(q, pid)]
    marks = defaultdict(list)
    ev_q = """SELECT properties.`$session_id`, timestamp, event FROM events
      WHERE timestamp >= now() - INTERVAL %d DAY AND event IN (%s) AND person.properties.email LIKE '%%@%%'
        AND person.properties.email NOT LIKE '%%@lunartree.bio' ORDER BY timestamp LIMIT 40000""" % (days + 1, _in(MOMENTS))
    for pid in project_ids():
        for sid, ts, ev in hql(ev_q, pid):
            marks[sid].append((_when(ts), ev))
    now = datetime.now(timezone.utc)
    out = []
    for pid, sid, start, end, active_ms, clicks, keys, errors, first_url, urls, keep, email, name, country, browser, os_, device in sessions:
        start, end = _when(start), _when(end)
        if start + timedelta(days=keep or REPLAY_RETENTION_DAYS) < now:
            continue  # PostHog has already deleted the footage
        dur = max(1, int((end - start).total_seconds()))
        buckets_at, moments = {}, []
        for ts, ev in marks.get(sid, []):
            label, kind = MOMENTS[ev]
            pct = min(100.0, max(0.0, (ts - start).total_seconds() / dur * 100))
            slot = round(pct * 2) / 2
            if kind != 'nav' and label:
                moments.append((label, kind))
            if buckets_at.get(slot, ('', 0))[1] < MARK_RANK[kind]:
                buckets_at[slot] = (kind, MARK_RANK[kind])
        areas = list(dict.fromkeys(a for a in (area_of(u) for u in (urls or [first_url])) if a))
        out.append({
            'id': sid, 'url': replay_url(sid, pid), 'email': email, 'name': name or '', 'ini': initials(name, email),
            'country': country or '', 'browser': browser or '', 'os': os_ or '', 'device': device or '',
            'start': start, 'dur': dur, 'active': int((active_ms or 0) / 1000), 'clicks': clicks or 0, 'keys': keys or 0,
            'errors': errors or 0, 'areas': areas, 'pages': len(urls or []),
            'marks': [{'at': at, 'kind': v[0]} for at, v in sorted(buckets_at.items())],
            'did': list(dict.fromkeys(l for l, kind in moments if kind != 'rage'))[:4],
            'rage': sum(1 for _, kind in moments if kind == 'rage'),
            'title': _title(moments, areas), 'bucket': bucket(dur),
            'live': min(100, round(((active_ms or 0) / 1000) / dur * 100)),
        })
    out.sort(key=lambda r: r['start'], reverse=True)
    cache.set(k, out, 300)
    return out
