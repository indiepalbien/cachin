from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0006_useremailconfig_useremailmessage'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='external_id',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='transaction',
            name='status',
            field=models.CharField(choices=[('confirmed', 'Confirmed'), ('pending_duplicate', 'Pending duplicate')], default='confirmed', max_length=32),
        ),
        migrations.AddField(
            model_name='useremailmessage',
            name='processed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='useremailmessage',
            name='processing_error',
            field=models.TextField(blank=True),
        ),
        migrations.CreateModel(
            name='PendingTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_id', models.CharField(db_index=True, max_length=255)),
                ('payload', models.JSONField()),
                ('reason', models.CharField(default='duplicate', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='transaction',
            unique_together={('user', 'external_id')},
        ),
    ]
