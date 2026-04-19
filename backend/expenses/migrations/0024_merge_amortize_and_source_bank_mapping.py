# Merge migration: combines amortize_fields branch with source_bank_mapping branch

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0021_transaction_amortize_fields'),
        ('expenses', '0023_add_source_bank_mapping'),
    ]

    operations = [
    ]
