"""Forms for expenses app."""

from django import forms
from .models import Exchange, Transaction, Category, Project, Payee, Source, Balance, BudgetGroup, Budget, SourceBankMapping, IBKRSymbolCurrency


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


class ImageUploadForm(forms.Form):
    """Form for uploading transaction images (receipts, invoices)."""

    images = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
            'capture': 'environment',  # Mobile camera preference
        }),
        label='Imágenes',
        required=False,
        help_text='Sube fotos de recibos, facturas o capturas de transacciones.'
    )


class BalanceForm(forms.ModelForm):
    """Form for creating/editing balance records."""

    class Meta:
        model = Balance
        fields = ['source', 'start_date', 'end_date', 'currency', 'amount']
        widgets = {
            'start_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'end_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'currency': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'USD',
                'maxlength': '3'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '1000.00'
            }),
        }


class BalanceCurrencyForm(forms.ModelForm):
    """Form for adding a single currency balance (used in formsets)."""

    class Meta:
        model = Balance
        fields = ['currency', 'amount']
        widgets = {
            'currency': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'USD',
                'maxlength': '3'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '1000.00'
            }),
        }


class BudgetGroupForm(forms.ModelForm):
    class Meta:
        model = BudgetGroup
        fields = ['name', 'currency']
        widgets = {
            'currency': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'USD',
                'maxlength': '3',
            }),
        }


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ['group', 'effective_date', 'amount', 'categories']
        widgets = {
            'effective_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '300.00',
            }),
            'categories': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['group'].queryset = BudgetGroup.objects.filter(user=user)
            self.fields['categories'].queryset = Category.objects.filter(user=user).order_by('name')


class SourceBankMappingForm(forms.ModelForm):
    class Meta:
        model = SourceBankMapping
        fields = ['bank_code', 'currency', 'source']
        widgets = {
            'currency': forms.TextInput(attrs={
                'placeholder': 'USD, UYU, o en blanco para cualquiera',
                'maxlength': '3',
            }),
        }

    def __init__(self, *args, user=None, banks=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['source'].queryset = Source.objects.filter(user=user)
        if banks:
            self.fields['bank_code'] = forms.ChoiceField(
                choices=[('', '--- Selecciona banco ---')] + list(banks.items()),
                label='Banco',
            )


class IBKRSymbolCurrencyForm(forms.ModelForm):
    class Meta:
        model = IBKRSymbolCurrency
        fields = ['symbol', 'currency']
        widgets = {
            'symbol': forms.TextInput(attrs={'placeholder': 'e.g. SUSW', 'style': 'text-transform:uppercase'}),
            'currency': forms.TextInput(attrs={'placeholder': 'e.g. EUR', 'maxlength': '3', 'style': 'text-transform:uppercase'}),
        }

    def clean_symbol(self):
        return self.cleaned_data['symbol'].strip().upper()

    def clean_currency(self):
        return self.cleaned_data['currency'].strip().upper()


class TransactionForm(forms.ModelForm):
    """Form for creating/editing transactions with user-filtered fields."""

    class Meta:
        model = Transaction
        fields = ["date", "description", "amount", "currency", "source", "category", "project", "payee", "comments", "amortize_months", "amortize_start_date", "is_reimbursable"]
        widgets = {
            'date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '100.00'
            }),
            'currency': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'USD',
                'maxlength': '3'
            }),
            'amortize_months': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'placeholder': 'Ej: 10',
            }),
            'amortize_start_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control',
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            # Filter querysets to only show records belonging to the current user
            self.fields['category'].queryset = Category.objects.filter(user=user)
            self.fields['project'].queryset = Project.objects.filter(user=user)
            self.fields['payee'].queryset = Payee.objects.filter(user=user)
            self.fields['source'].queryset = Source.objects.filter(user=user)

