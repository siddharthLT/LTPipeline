"""Action funnel and journey Sankey from PostHog: how far client users get in BioLens, across app-prod and Neuland."""
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache

from . import posthog

PROJECTS = {234813: 'app-prod', 600726: 'Neuland'}

# Ordered ladder of what a user can do in BioLens. A user is counted at the furthest rung they reached in the window.
STEPS = [
    ('visit', 'Opened BioLens', 'Any page view or tracked event'),
    ('look', 'Looked at a company', 'Opened a company profile, the company list or a workspace company'),
    ('dig', 'Dug into the intel', 'Read an assessment, asked the AI, generated a report or switched profile tabs'),
    ('work', 'Worked a lead', 'Assigned a lead, changed status, scored, added to a workspace or filtered'),
    ('contact', 'Got a contact', 'Added or downloaded decision makers'),
    ('reach', 'Sent outreach', 'Used the email composer to send'),
]
STEP_EVENTS = {
    'look': ['company_profile:viewed', 'all_companies:viewed', 'all_accounts:viewed', 'biolens_search:recent_workspace_click'],
    'dig': ['company_profile:assessment_viewed', 'company_profile:ask_ai_click', 'company_profile:view_tab_click', 'chat:user_message_submit',
            'chat:generate_report_click', 'chat:download_report_click'],
    'work': ['workspace_companies:lead_assigned', 'workspace_companies:account_status_changed', 'workspace_companies:internal_score_updated',
             'workspace_companies:company_added', 'workspace_companies:filter_applied', 'workspace:created'],
    'contact': ['decision_makers:added', 'decision_makers:list_downloaded'],
    'reach': ['outreach:email_used'],
}
EVENT_STEP = {e: k for k, evs in STEP_EVENTS.items() for e in evs}
KEYS = [k for k, _, _ in STEPS]
LABEL = {k: l for k, l, _ in STEPS}
# Places people go that are not rungs of the ladder: they show up in the journey Sankey (from page views) but not in the "how far" bars.
SIDE = [('home', 'Opened Homepage'), ('workspace', 'Viewed a Workspace'), ('insights', 'Checked Insights')]
JOURNEY = KEYS + [k for k, _ in SIDE]
LABEL.update(SIDE)
LABEL['stop'] = 'Stopped here'


# Page views that become journey steps: the first matching URL wins, so the homepage is only the bare /biolens
SIDE_CASE = ("multiIf(properties.`$current_url` LIKE '%%/biolens/insights%%', 'insights', properties.`$current_url` LIKE '%%/biolens/workspaces%%', 'workspace', "
             "match(properties.`$current_url`, '^https?://[^/]+/biolens/?([?#].*)?$'), 'home', '')")


def _users(days, sessions=False):
    """{(project, email): {step: first time}} for client users in the window; with sessions, {(project, email, session): ...} so each visit stands alone."""
    where = posthog._where(days)
    events = posthog._in(list(EVENT_STEP))
    out = defaultdict(dict)
    who = "person.properties.email" + (", properties.`$session_id`" if sessions else "")
    n = 2 if sessions else 1  # columns that identify the unit
    gb = lambda extra: ', '.join(str(i + 1) for i in range(n + extra))
    q_events = ("SELECT %s, event, min(timestamp) FROM events WHERE %s AND event IN (%s) GROUP BY %s LIMIT 50000" % (who, where, events, gb(1)))
    q_views = ("SELECT %s, min(timestamp) FROM events WHERE %s AND event = '$pageview' GROUP BY %s LIMIT 50000" % (who, where, gb(0)))
    q_side = ("SELECT %s, %s AS step, min(timestamp) FROM events WHERE %s AND event = '$pageview' AND step != '' GROUP BY %s LIMIT 50000"
              % (who, SIDE_CASE, where, gb(1)))

    def unit(pid, row):
        if sessions and not row[1]:  # no session id, so it cannot be told apart from another visit
            return None
        return (pid, row[0].lower(), row[1]) if sessions else (pid, row[0].lower())

    def put(k, step, ts):
        seen = out[k]
        seen[step] = min(seen[step], ts) if step in seen else ts

    with ThreadPoolExecutor(3) as ex:  # all three queries, on every project, at once
        got_events, got_views, got_side = ex.submit(posthog.hql_all, q_events), ex.submit(posthog.hql_all, q_views), ex.submit(posthog.hql_all, q_side)
        for pid, rows in got_events.result():
            for row in rows:
                if unit(pid, row):
                    put(unit(pid, row), EVENT_STEP[row[n]], row[n + 1])
        for pid, rows in got_views.result():
            for row in rows:
                if unit(pid, row):
                    out[unit(pid, row)].setdefault('visit', row[n])
        for pid, rows in got_side.result():
            for row in rows:
                if unit(pid, row):
                    put(unit(pid, row), row[n], row[n + 1])
    for seen in out.values():  # anyone with a tracked event has opened the app, even without a page view
        seen.setdefault('visit', min(seen.values()))
    return {k: v for k, v in out.items()}


def users(days):
    k = 'posthog-funnel-%d' % days
    data = cache.get(k)
    if data is None:
        data = _users(days)
        cache.set(k, data, 300)
    return data


def sessions(days):
    k = 'posthog-funnel-sessions-%d' % days
    data = cache.get(k)
    if data is None:
        data = _users(days, sessions=True)
        cache.set(k, data, 300)
    return data


def _journeys(data, by_domain):
    out = []
    for key, seen in data.items():
        pid, email = key[0], key[1]
        # journey: opening the app is always first, then the order each other step was first reached
        order = ['visit'] + sorted((s for s in seen if s != 'visit'), key=lambda s: (seen[s], JOURNEY.index(s)))
        out.append({'email': email, 'pid': pid, 'account': posthog.match_account(email, by_domain), 'path': order,
                    'far': max(KEYS.index(s) for s in seen if s in KEYS)})
    return out


def build(accounts, days, account_id=None, by='users'):
    """Funnel rows, journey Sankey and the people who stopped at each rung. account_id limits everything to one tracker account.
    by='sessions' draws the Sankey with one path per visit instead of one per person; the bars stay per person."""
    by_domain = posthog.by_domain_of(accounts)
    people = _journeys(users(days), by_domain)
    runs = _journeys(sessions(days), by_domain) if by == 'sessions' else people
    chips = Counter()  # who has users in the window, so the filter only offers companies with something to show
    for p in people:
        if p['account']:
            chips[p['account']] += 1
    chips = sorted(chips.items(), key=lambda kv: (-kv[1], kv[0].name))
    picked = next((a for a, _ in chips if a.pk == account_id), None)
    if picked:
        people = [p for p in people if p['account'] and p['account'].pk == picked.pk]
        runs = [p for p in runs if p['account'] and p['account'].pk == picked.pk]
    total = len(people)
    reached = Counter()
    for p in people:
        for i in range(p['far'] + 1):
            reached[i] += 1
    stopped = defaultdict(list)
    for p in people:
        if p['far'] < len(KEYS) - 1:
            stopped[p['far']].append(p)
    rows = []
    for i, (key, label, hint) in enumerate(STEPS):
        n = reached[i]
        prev = reached[i - 1] if i else n
        who = sorted(stopped[i], key=lambda p: (p['account'] is None, p['account'].name if p['account'] else p['email']))
        rows.append({'key': key, 'label': label, 'hint': hint, 'n': n, 'pct': round(n * 100 / total) if total else 0,
                     'width': round(n * 100 / total, 1) if total else 0, 'conv': round(n * 100 / prev) if prev else 0,
                     'lost': prev - n if i else 0, 'stopped': len(who),
                     'who': [{'email': p['email'], 'name': p['account'].name if p['account'] else '', 'pid': p['pid'],
                              'project': PROJECTS.get(p['pid'], str(p['pid']))} for p in who[:10]], 'more': max(len(who) - 10, 0)})
    top_paths = Counter(' > '.join(LABEL[s] for s in p['path']) for p in people).most_common(8)
    return {'chips': [{'pk': a.pk, 'name': a.name, 'logo_url': a.logo_url, 'n': n} for a, n in chips], 'picked': picked, 'total': total, 'rows': rows, 'top_paths': top_paths, 'sankey': sankey([p['path'] for p in runs], unit='session' if by == 'sessions' else 'user') if total and runs else None, 'by': by, 'n_runs': len(runs),
            'by_project': dict(Counter(PROJECTS.get(p['pid'], str(p['pid'])) for p in people))}


def sankey(paths, width=1560, height=520, node_w=14, pad=22, label_w=200, unit='user'):
    """Lay out a left-to-right journey Sankey. Column i is the i-th rung a user first reached; 'stop' is where their path ends."""
    cols = len(JOURNEY)
    links = Counter()
    nodes = Counter()
    for path in paths:
        for i, step in enumerate(path[:cols]):
            nodes[(i, step)] += 1
            if i + 1 < min(len(path), cols):
                links[((i, step), (i + 1, path[i + 1]))] += 1
        if len(path) < cols:
            nodes[(len(path), 'stop')] += 1
            links[((len(path) - 1, path[-1]), (len(path), 'stop'))] += 1
    n_users = len(paths)
    order = JOURNEY + ['stop']
    maxnodes = max(sum(1 for (c, _) in nodes if c == i) for i in range(cols))
    scale = (height - pad * (maxnodes - 1)) / n_users
    left = 16  # the last column's labels sit to its right, so it keeps label_w of room
    xs = [left + (width - left - label_w) * i / (cols - 1) for i in range(cols)]
    pos = {}
    for c in range(cols):
        col = sorted([k for k in nodes if k[0] == c], key=lambda k: order.index(k[1]))
        h = sum(nodes[k] * scale for k in col) + pad * (len(col) - 1)
        y = (height - h) / 2 if col else 0
        for k in col:
            pos[k] = {'x': xs[c] - node_w / 2, 'y': y, 'h': nodes[k] * scale, 'out': 0, 'in': 0}
            y += nodes[k] * scale + pad
    out_links = []
    for (a, b), v in sorted(links.items(), key=lambda kv: (pos[kv[0][0]]['y'], pos[kv[0][1]]['y'])):
        pa, pb = pos[a], pos[b]
        w = v * scale
        y0 = pa['y'] + pa['out'] + w / 2
        y1 = pb['y'] + pb['in'] + w / 2
        pa['out'] += w
        pb['in'] += w
        x0, x1 = pa['x'] + node_w, pb['x']
        xm = (x0 + x1) / 2
        out_links.append({'d': 'M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f' % (x0, y0, xm, y0, xm, y1, x1, y1), 'w': round(max(w, 0.8), 1),
                          'step': b[1] if b[1] == 'stop' else a[1], 'title': '%s → %s: %d %s%s' % (LABEL[a[1]], LABEL[b[1]], v, unit, '' if v == 1 else 's')})
    reached = Counter()
    for (c, _), n in nodes.items():
        reached[c] += n

    def drop(c, step):
        """Share of the people still in the funnel at the step before who ended their path here."""
        live = reached[c - 1] - nodes[(c - 1, 'stop')]  # people at the step before who had not already stopped
        return round(nodes[(c, step)] / live * 100) if step == 'stop' and live > 0 else None

    out_nodes = []
    for (c, step), p in pos.items():
        out_nodes.append({'x': round(p['x'], 1), 'y': round(p['y'], 1), 'h': round(max(p['h'], 1.5), 1), 'w': node_w, 'step': step,
                          'label': LABEL[step], 'n': nodes[(c, step)], 'drop': drop(c, step), 'tx': round(p['x'] + node_w + 8, 1),
                          'ty': round(p['y'] + max(p['h'], 1.5) / 2, 1)})
    heads = [{'x': round(x - node_w / 2, 1), 'text': 'Step %d' % i if i else 'Start'} for i, x in enumerate(xs)]
    return {'w': width, 'h': height, 'nodes': out_nodes, 'links': out_links, 'heads': heads}
