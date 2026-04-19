import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0026_add_virtual_transaction_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='IBKRSymbolCurrency',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(help_text='Ticker symbol, e.g. SUSW', max_length=20)),
                ('currency', models.CharField(help_text='Settlement currency, e.g. EUR', max_length=3)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'IBKR symbol currency',
                'verbose_name_plural': 'IBKR symbol currencies',
            },
        ),
        migrations.AlterUniqueTogether(
            name='ibkrsymbolcurrency',
            unique_together={('user', 'symbol')},
        ),
    ]
