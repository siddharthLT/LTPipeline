"""ARR forecast for the dashboard: when each account is predicted to sign, weighted by its score."""
import calendar
import datetime
import re

DEFAULT_ARR = 15000   # lowest tier, used when an account has no deal value yet
USER_PRICE = 2000     # assumed yearly price per user, to turn ARR into an expected user count
MONTHS = 12


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


def build(accounts, today=None):
    """accounts need .score, .deal_value and .contract_info (done/date). Returns 13 points, month 0..12."""
    today = today or datetime.date.today()
    deals = []
    for a in accounts:
        info = a.contract_info
        arr = parse_arr(a.deal_value) or DEFAULT_ARR
        deals.append({'signed': bool(info['done']), 'date': today if info['done'] else info['date'],
                      'p': 1.0 if info['done'] else a.score / 100, 'arr': arr})
    points = []
    for m in range(MONTHS + 1):
        cutoff = add_months(today, m)
        hit = [d for d in deals if d['date'] <= cutoff]
        points.append({
            'month': m, 'date': cutoff.strftime('%b %-d, %Y'),
            'accounts': round(sum(d['p'] for d in hit), 1), 'arr': round(sum(d['p'] * d['arr'] for d in hit)),
            'users': round(sum(d['p'] * d['arr'] for d in hit) / USER_PRICE),
            'best_accounts': len(hit), 'best_arr': sum(d['arr'] for d in hit),
            'best_users': round(sum(d['arr'] for d in hit) / USER_PRICE),
        })
    return {'points': points, 'user_price': USER_PRICE, 'total': len(deals)}
