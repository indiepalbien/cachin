from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0024_merge_amortize_and_source_bank_mapping'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='is_reimbursable',
            field=models.BooleanField(
                default=False,
                help_text='Mark if this expense will be reimbursed. Excluded from category totals and budgets.',
            ),
        ),
    ]
