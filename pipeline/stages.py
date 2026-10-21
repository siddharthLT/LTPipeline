STAGES = [
    (1, 'Find buyer'),
    (2, 'First reply'),
    (3, 'First call'),
    (4, 'Qualify or park'),
    (5, 'Build champion'),
    (6, 'Map the room'),
    (7, 'Pre-demo'),
    (8, 'Demo'),
    (9, 'Demo debrief'),
    (10, 'Pilot'),
    (11, 'Pilot close-out'),
    (12, 'Contract'),
]
STAGE_NAMES = dict(STAGES)
STAGE_COUNT = len(STAGES)

# Predictability score: steps 1-4 weigh 5% each (20%), steps 5-12 weigh 10% each (80%).
STAGE_WEIGHTS = {num: (5 if num <= 4 else 10) for num, _ in STAGES}
assert sum(STAGE_WEIGHTS.values()) == 100

# Typical working days a step takes once the one before it is done. Used to predict dates for
# every step still open; a step can override its predicted date with a target date.
STAGE_DAYS = {1: 7, 2: 5, 3: 7, 4: 5, 5: 14, 6: 10, 7: 7, 8: 10, 9: 5, 10: 30, 11: 14, 12: 21}

# The path after a demo. Each step is driven by the stages named here (see Account.path_steps).
PATH = [
    ('Demo', 'Steps 1\u20138'),
    ('Real usage', 'Usage checks'),
    ('Pilot / design deployment', 'Steps 10\u201311'),
    ('Annual contract', 'Step 12'),
    ('Integration / expansion', 'After contract'),
]

USAGE_CHECKS = [
    ('usage_tried', 'At least 1 user tried the product'),
    ('usage_value', 'At least 1 user reached value: decision makers enriched, an email written, or the copilot used'),
    ('usage_onboarded', '100% of invited users onboarded'),
]
