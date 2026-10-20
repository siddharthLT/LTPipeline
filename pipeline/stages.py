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
