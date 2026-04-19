# Generated migration for transaction amortization fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0020_imageupload_image_alter_imageupload_image_path'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='amortize_months',
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text='Spread this transaction over N months in category totals. Leave blank for no amortization.',
            ),
        ),
        migrations.AddField(
            model_name='transaction',
            name='amortize_start_date',
            field=models.DateField(
                blank=True,
                null=True,
                help_text="First month of the amortization window. Defaults to the transaction's own month if left blank.",
            ),
        ),
    ]
