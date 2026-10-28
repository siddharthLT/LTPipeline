"""ARR forecast for the dashboard: which tier each account is predicted to sign, and when."""
import calendar
import datetime
import re

from .stages import STAGE_DAYS, STAGE_WEIGHTS

# Pricing framework: one base fee a year for unlimited seats, with a yearly credit allotment.
TIERS = [
    {'key': 'starter', 'name': 'Starter', 'arr': 36000, 'credits': 60000},
    {'key': 'growth', 'name': 'Growth', 'arr': 48000, 'credits': 120000},
    {'key': 'enterprise', 'name': 'Enterprise', 'arr': 72000, 'credits': 250000},
]
FLOOR_ARR = TIERS[0]['arr']          # no account is forecast below Starter
GROWTH_TEAM = 20                     # sales and marketing people: under 20 Starter, 20-99 Growth, 100+ Enterprise
ENTERPRISE_TEAM = 100
ADVISORS = ('Abhishek', 'Lavanya', 'Mak', 'PK', 'Naren')   # the only connections that count
# Timing: each factor stretches the time an account still needs.
TEAM_DELAY = {'small': 1.6, 'mid': 1.25, 'large': 1.0, 'unknown': 1.25}
NO_CONNECTION_DELAY = 1.5
SECURITY_REVIEW_DAYS = 45            # Enterprise needs a dedicated-instance and security review
ENTERPRISE_SIGNALS = re.compile(r'dedicated instance|private cloud|soc ?2|sharepoint|onedrive|\bsaml\b|\bscim\b|\bsso\b|'
                                r'security (review|note|doc|brief|slide)|client-cloud', re.I)
GROWTH_SIGNALS = re.compile(r'salesforce|\bcrm\b|hubspot', re.I)
MONTHS = 18
NEW_CONVERSATIONS_PER_MONTH = 6   # how many cold accounts the team can start working each month
COLD_CYCLE_DAYS = sum(STAGE_DAYS.values())          # the date formula's span for a cold account (135 days)
FIRST_CALL_SCORE = sum(STAGE_WEIGHTS[n] for n in (1, 2, 3))   # score of an account that has just had its first call
DEFAULT_CYCLE_MONTHS = 3        # typical cold account; 6 when being conservative
DEFAULT_CONVERSION = 0.20       # chance an account that has had a first call signs


def parse_arr(text):
    """'$30K' -> 30000, '$12-25K' -> 18500 (midpoint), '$1.2M' -> 1200000. None when no number."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*([kKmM])?', text or '')
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    mult = {'k': 1_000, 'm': 1_000_000}.get((m.group(3) or '').lower(), 1)
    value = (lo + hi) / 2 * mult
    if not m.group(3) and value < 1000:   # '$30' with no suffix is almost certainly $30K
        value *= 1000
    return round(value)


def add_months(day, n):
    month = day.month - 1 + n
    year = day.year + month // 12
    month = month % 12 + 1
    return datetime.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def close_probability(score, conversion):
    """Chance an account signs. `conversion` at the first call, rising to 100% at contract.

    Before the first call it scales down in proportion (a 5% account is a third of the way there).
    """
    if score >= FIRST_CALL_SCORE:
        return conversion + (1 - conversion) * (score - FIRST_CALL_SCORE) / (100 - FIRST_CALL_SCORE)
    return conversion * score / FIRST_CALL_SCORE


def tier_for_arr(value):
    """Tier a contract value belongs to: nearest bracket, so $45K reads as Growth and $150K as Enterprise."""
    if value < 42000:
        return TIERS[0]
    return TIERS[1] if value < 60000 else TIERS[2]


def advisor_names(text):
    found = [n for n in ADVISORS if re.search(r'\b%s\b' % n, text or '', re.I)]
    return found


def predict_tier(a, signed):
    """(tier, arr, reasons). Signed accounts use their real contract; others come from team size and what they ask for."""
    manual = parse_arr(getattr(a, 'deal_value', ''))
    team = getattr(a, 'sales_marketing_team', None)
    text = getattr(a, 'signal_text', '') or ''
    if signed:
        arr = manual or FLOOR_ARR
        return tier_for_arr(arr), arr, ['signed contract']
    reasons = []
    if team is None:
        idx = 0
        reasons.append('team size unknown, assumed Starter')
    else:
        idx = 2 if team >= ENTERPRISE_TEAM else 1 if team >= GROWTH_TEAM else 0
        reasons.append('%d in sales and marketing' % team)
    if GROWTH_SIGNALS.search(text) and idx < 1:
        idx = 1
        reasons.append('asked about CRM')
    if ENTERPRISE_SIGNALS.search(text) and idx < 2:
        idx = 2
        reasons.append('asked about security or hosting')
    tier = TIERS[idx]
    if manual and manual >= FLOOR_ARR and manual != tier['arr']:
        reasons.append('deal value set to %s' % money(manual))
        return tier_for_arr(manual), manual, reasons
    return tier, tier['arr'], reasons


def money(v):
    return '$%dK' % round(v / 1000)


def team_band(team):
    if team is None:
        return 'unknown'
    return 'large' if team >= ENTERPRISE_TEAM else 'mid' if team >= GROWTH_TEAM else 'small'


def build(accounts, today=None, cycle_months=DEFAULT_CYCLE_MONTHS, conversion=DEFAULT_CONVERSION):
    """accounts need .name, .score, .deal_value and .contract_info (done/date); optional .sales_marketing_team,
    .advisors, .signal_text and .pk. Returns MONTHS + 1 points, month 0..MONTHS.

    This only reshapes the graph. Scores and the dashboard dates are not changed.
    - Tier: signed accounts use their contract. Others take it from sales and marketing team size (under 20
      Starter, 20-99 Growth, 100+ Enterprise), moved up when they asked for CRM sync or security and hosting
      terms, and replaced by a deal value of $36K or more when one is set. Nothing is forecast below Starter.
    - Timing: the date formula gives the time left from the score. The graph stretches it so a cold account
      takes `cycle_months`, then by team size (small x1.6, mid x1.25, large x1.0), by connection (no advisor
      x1.5), and Enterprise adds a security review. Cold accounts start in a queue, about 6 a month.
    - Likelihood: close_probability(). Expected signings are whole accounts: the summed likelihood of every
      account due by a date, rounded; the accounts counted are the most likely ones, and their contract values
      make the ARR. The set only grows month to month, so ARR never goes down.
    """
    today = today or datetime.date.today()
    factor = cycle_months * 30.4 / COLD_CYCLE_DAYS
    # Cold accounts are worked in order, so the least ready ones start last: higher score first, then an
    # advisor connection, then a bigger team.
    cold = sorted((a for a in accounts if not a.contract_info['done'] and a.score < FIRST_CALL_SCORE),
                  key=lambda a: (-a.score, 0 if advisor_names(getattr(a, 'advisors', '')) else 1,
                                 ('large', 'mid', 'unknown', 'small').index(team_band(getattr(a, 'sales_marketing_team', None))),
                                 a.name))
    start_days = {a.name: (i // NEW_CONVERSATIONS_PER_MONTH) * 30.4 for i, a in enumerate(cold)}
    deals = []
    for a in accounts:
        info = a.contract_info
        signed = bool(info['done'])
        tier, arr, reasons = predict_tier(a, signed)
        team = getattr(a, 'sales_marketing_team', None)
        advisors = advisor_names(getattr(a, 'advisors', ''))
        if signed:
            due = today
        else:
            days = max((info['date'] - today).days, 0) * factor
            days *= TEAM_DELAY[team_band(team)] * (1.0 if advisors else NO_CONNECTION_DELAY)
            if tier['key'] == 'enterprise':
                days += SECURITY_REVIEW_DAYS
            due = today + datetime.timedelta(days=round(days + start_days.get(a.name, 0)))
            reasons.append('advisor ' + ', '.join(advisors) if advisors else 'no advisor connection')
            reasons.append('score %d%%' % a.score)
        deals.append({'name': a.name, 'pk': getattr(a, 'pk', None), 'date': due, 'tier': tier, 'arr': arr,
                      'p': 1.0 if signed else close_probability(a.score, conversion), 'reasons': reasons})
    signed_names = [d['name'] for d in deals if d['p'] == 1.0]
    points, chosen = [], []
    for m in range(MONTHS + 1):
        cutoff = add_months(today, m)
        hit = [d for d in deals if d['date'] <= cutoff]
        extra = int(sum(d['p'] for d in hit) + 0.5) - len(chosen)
        if extra > 0:
            rest = sorted((d for d in hit if d not in chosen), key=lambda d: (-d['p'], d['date'], d['name']))
            chosen += rest[:extra]
        arr = sum(d['arr'] for d in chosen)
        best = sum(d['arr'] for d in hit)
        by_tier = {t['key']: sum(d['arr'] for d in chosen if d['tier']['key'] == t['key']) for t in TIERS}
        count_tier = {t['key']: sum(1 for d in chosen if d['tier']['key'] == t['key']) for t in TIERS}
        points.append({
            'month': m, 'date': cutoff.strftime('%b %-d, %Y'),
            'accounts': len(chosen), 'arr': arr, 'by_tier': by_tier, 'count_tier': count_tier,
            'credits': sum(d['tier']['credits'] for d in chosen),
            'names': [d['name'] for d in chosen if d['name'] not in signed_names],
            'best_accounts': len(hit), 'best_arr': best,
        })
    chosen_names = {d['name'] for d in chosen}
    horizon = add_months(today, MONTHS)
    entries = [{'name': d['name'], 'pk': d['pk'], 'tier': d['tier']['name'], 'arr': d['arr'], 'date': d['date'],
                'chance': round(d['p'] * 100), 'reasons': d['reasons'], 'counted': d['name'] in chosen_names}
               for d in sorted(deals, key=lambda d: (d['date'], -d['p'], d['name']))
               if d['p'] < 1.0 and d['date'] <= horizon]
    return {'points': points, 'signed': signed_names, 'total': len(deals), 'entries': entries,
            'tiers': TIERS, 'months': MONTHS, 'cycle_months': cycle_months, 'conversion': round(conversion * 100)}
