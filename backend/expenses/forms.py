"""Forms for expenses app."""

from django import forms
from .models import Exchange


class ExchangeForm(forms.ModelForm):
    """Form for creating/editing exchange rates."""
    
    class Meta:
        model = Exchange
        fields = ['date', 'source_currency', 'target_currency', 'rate']
        widgets = {
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'source_currency': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'USD'
            }),
            'target_currency': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'UYU'
            }),
            'rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.00000001',
                'placeholder': '40.00'
            }),
        }
        help_texts = {
            'rate': 'Ejemplo: Si 1 USD = 40 UYU, ingresa "USD" en moneda origen, "UYU" en moneda destino, y "40" en tasa.',
        }


class BulkTransactionForm(forms.Form):
    """Form for bulk transaction import."""
    
    raw_text = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 10,
            'placeholder': 'Paste transaction data here (tab-separated or space-separated columns)',
        }),
        label='Transaction Data',
        required=True,
    )
    
    bank = forms.ChoiceField(
        widget=forms.Select(attrs={
            'class': 'form-control',
        }),
        label='Bank',
        required=True,
    )
    
    currency = forms.ChoiceField(
        widget=forms.Select(attrs={
            'class': 'form-control',
        }),
        label='Currency',
        required=False,
        initial='',
        choices=[
            ('', '--- Select currency (if required) ---'),
            ('UYU', 'UYU - Uruguayan Peso'),
            ('USD', 'USD - US Dollar'),
        ],
    )
    
    def __init__(self, *args, banks=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Populate bank choices
        if banks:
            self.fields['bank'].choices = [
                ('', '--- Select bank ---'),
            ] + list(banks.items())
