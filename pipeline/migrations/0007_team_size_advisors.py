from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pipeline', '0006_account_segment'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='sales_marketing_team',
            field=models.PositiveIntegerField(blank=True, help_text='People in sales and marketing (Apollo)', null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='team_size_source',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='account',
            name='advisors',
            field=models.CharField(blank=True, help_text='Advisors who connect us: Abhishek, Lavanya, Mak, PK, Naren', max_length=200),
        ),
    ]
