from django.db import migrations

J = '\n'.join

# Starting hypotheses, not measured data. Edit them on the Usage playbook page as real usage comes in.
STAGES = [
    dict(order=1, name='Activated', window='First 7 days',
         healthy=J([
             'At least 1 invited user logs in within 48 hours of the invite',
             'Opens a workspace and reviews 5+ companies',
             'Reaches value once: enriches a decision maker, drafts an email, or asks the copilot a question',
             'Reviews Team Setup and flags what is wrong with it',
         ]),
         credits='Uses roughly 10-20% of the trial credits',
         moves_on='Two or more value actions across 2+ days. One login and nothing else is not activated.',
         gate=J([
             'Guide: a first-week checklist (open workspace, enrich one decision maker, draft one email, check Team Setup)',
             'Guide: nudge after a company profile view that has no enrichment yet',
             'Gate: the email builder opens after one decision maker is enriched, so users hit the useful path first',
             'Gate: trial runs on credits, with a day cap, not on unlimited open access',
         ])),
    dict(order=2, name='Real usage', window='Weeks 2-3',
         healthy=J([
             '2+ weekly active users, or the one named user if the team is a single BD person',
             '3+ sessions a week',
             '15+ companies reviewed and 10+ decision makers enriched',
             '5+ outreach drafts, with at least some sent',
             'Edits to Team Setup or the ICP, which shows they are shaping it to their market',
         ]),
         credits='Steady use of about 30-50% of trial credits by the end of week 3',
         moves_on='A repeat habit (the same day each week) plus one real account worked end to end. That is the signal to propose a pilot.',
         gate=J([
             'Guide: day-5 prompt to invite a teammate and day-10 prompt to upload a conference or account list',
             'Guide: weekly digest that points back to unreviewed high-fit companies',
             'Gate: CSV upload and extra workspaces unlock after the first workspace has been reviewed',
             'Gate: a usage review at day 14 before any extension, with the 3 value actions shown back to the user',
         ])),
    dict(order=3, name='Pilot', window='Weeks 4-12',
         healthy=J([
             'A recurring weekly workflow that someone owns (pipeline review, conference prep, weekly digest)',
             '50%+ of invited users active every week',
             'Outreach sent from the product, and replies or meetings that came out of it',
             'The feedback loop is closed: Team Setup corrected, workspaces rerun, accuracy improving',
             'A named internal owner who can say what the pilot is meant to prove',
         ]),
         credits='60-80% of the monthly pilot allowance used in each of the first two months; flat or falling use is a warning',
         moves_on='Pilot success criteria agreed in writing at the start and met by week 8. At least one meeting or opportunity credited to the product.',
         gate=J([
             'Guide: a pilot scorecard in the product showing active users, companies reviewed, outreach sent and meetings booked',
             'Gate: pilot credits reset monthly and do not roll over, so low use is visible rather than hidden',
             'Gate: advanced workflows (watchlists, Ask AI reports, integrations) unlock at set usage points',
             'Guide: a check-in at 50% of pilot credits and again at 80%',
         ])),
    dict(order=4, name='Annual contract', window='Decision point',
         healthy=J([
             'Pilot goal met and the buyer has seen the scorecard',
             'Credit burn at or above the pilot run rate for 2+ months',
             'More than one user depends on it weekly',
             'Security review and procurement started, with a signer named',
         ]),
         credits='Run rate that sizes the annual plan: roughly 2-3 months of pilot burn, annualised, plus headroom',
         moves_on='Buyer confirms budget and signer. Annual size is set from the run rate, not from list price.',
         gate=J([
             'Guide: at 70% of pilot credits, a prompt to book the annual conversation',
             'Gate: when pilot credits run out, the workspace drops to read-only instead of blocking, so the data stays visible',
             'Guide: a usage summary page the champion can forward to the buyer',
         ])),
    dict(order=5, name='Integration / expansion', window='After contract',
         healthy=J([
             'Weekly CSV exports, or repeated requests to push data into the CRM',
             '5+ active users, or a second team asking for access',
             'A second workflow in use (watchlist, conference lists, Ask AI research)',
             'Credit use above the plan allowance in 2 consecutive months',
         ]),
         credits='Sustained use above 100% of plan credits, or a second workflow adding 30%+ on top',
         moves_on='A CRM integration or larger contract conversation is justified when export or sync requests repeat and 2+ teams or users are active.',
         gate=J([
             'Guide: surface the integration option once a user exports for the third time',
             'Gate: integrations and extra seats sit on the annual plan, as the expansion step',
             'Guide: suggest the next workflow (watchlist, conference workspace) based on what the team already uses',
         ])),
]


def seed(apps, schema_editor):
    UsageStage = apps.get_model('pipeline', 'UsageStage')
    for s in STAGES:
        UsageStage.objects.get_or_create(order=s['order'], defaults=s)


class Migration(migrations.Migration):
    dependencies = [('pipeline', '0002_deal_snapshot_thesis_playbook')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
