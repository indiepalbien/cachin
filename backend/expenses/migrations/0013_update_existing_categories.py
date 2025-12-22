# Generated migration to update existing categories with descriptions

from django.db import migrations


def update_existing_categories(apps, schema_editor):
    """Update existing categories to set counts_to_total=False for 'Pago de tarjetas'."""
    Category = apps.get_model('expenses', 'Category')
    
    # Set counts_to_total=False for all categories named "Pago de tarjetas" (case insensitive)
    Category.objects.filter(name__iexact='pago de tarjetas').update(counts_to_total=False)
    Category.objects.filter(name__iexact='pago tarjetas').update(counts_to_total=False)
    Category.objects.filter(name__iexact='tarjetas').update(counts_to_total=False)


def reverse_update(apps, schema_editor):
    """Reverse operation - set all to True."""
    Category = apps.get_model('expenses', 'Category')
    Category.objects.filter(name__iexact='pago de tarjetas').update(counts_to_total=True)
    Category.objects.filter(name__iexact='pago tarjetas').update(counts_to_total=True)
    Category.objects.filter(name__iexact='tarjetas').update(counts_to_total=True)


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0012_category_counts_to_total_category_description_and_more'),
    ]

    operations = [
        migrations.RunPython(update_existing_categories, reverse_update),
    ]
