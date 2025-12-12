"""Forms for polls app."""

from django import forms


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
