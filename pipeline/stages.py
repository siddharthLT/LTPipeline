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

# A step is done only when every one of its criteria is met. Criteria are yes/no facts, each one provable
# from an email, a call or the product, so "done" is decided by evidence and not by anyone's judgement.
CRITERIA = {
    1: [('named', 'A named person who feels the problem (name and role)'),
        ('reachable', 'A verified way to reach them (email or LinkedIn)')],
    2: [('replied', 'A real reply from that person, not an auto-reply')],
    3: [('call_held', 'First call held with a named contact'),
        ('problem_heard', 'Their problem heard in their own words')],
    4: [('icp_fit', 'ICP fit checked against their stated criteria'),
        ('budget', 'Budget, pricing sensitivity or buying process captured'),
        ('decision', 'Decision recorded: continue or park')],
    5: [('champion_named', 'A champion named: someone who wants this to work'),
        ('champion_acted', 'The champion has acted for us: an intro, a forward, data shared or an internal meeting')],
    6: [('buyer', 'Buyer identified: who holds the budget and signs'),
        ('users', 'Day-to-day users identified'),
        ('blockers', 'Blockers identified'),
        ('buyer_reached', 'Buyer met, or confirmed in writing as aware')],
    7: [('workspace', 'Workspace set up on their ICP'),
        ('agenda', 'Attendees and agenda agreed with the champion')],
    8: [('demo_held', 'Demo held with the users'),
        ('real_data', 'Shown on their own accounts or workspace, not a generic demo')],
    9: [('debrief', 'Debrief held with the champion'),
        ('objections', 'Objections and open questions logged'),
        ('next_step', 'Next step agreed: trial, pilot or decision date')],
    10: [('scope', 'Pilot scope and success criteria agreed in writing'),
         ('access', 'Every pilot user has access'),
         ('used', 'At least one user reached value in the product')],
    11: [('review', 'Success criteria reviewed against usage'),
         ('shown_buyer', 'Results shown to the buyer'),
         ('go_no_go', 'Go or no-go recorded')],
    12: [('price', 'Price and term agreed'),
         ('procurement', 'Security and procurement cleared'),
         ('signed', 'Contract signed')],
}
assert set(CRITERIA) == set(STAGE_NAMES)
