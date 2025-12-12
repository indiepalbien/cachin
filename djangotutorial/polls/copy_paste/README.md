# Copy-Paste Bulk Transaction Import

Este módulo permite importar múltiples transacciones bancarias copiando y pegando datos directamente desde las páginas web de los bancos.

## Características

- **Soporte para múltiples bancos**: ITAU (Débito y Crédito), Scotia (Crédito), BBVA (Crédito)
- **Detección automática de formatos**: Parseo basado en configuración YAML
- **Limpieza de datos**: Normalización automática de montos, fechas y monedas
- **Validación**: Verificación de campos requeridos y duplicados
- **Preview antes de importar**: Los usuarios pueden revisar y seleccionar qué transacciones importar

## Uso

### 1. Acceder a la interfaz

Navega a `/polls/bulk-add/` en tu aplicación Django.

### 2. Seleccionar banco y pegar datos

1. Selecciona el banco desde el dropdown
2. Si el banco requiere moneda (ej: ITAU Débito), selecciónala
3. Copia los datos desde la página del banco y pégalos en el textarea
4. Click en "Process Data"

### 3. Revisar y confirmar

1. Revisa las transacciones detectadas en la tabla
2. Desmarca las que no quieres importar
3. Click en "Add Selected Transactions"

## Formatos soportados

### ITAU Débito

```
05-12-25	DEB. CAMBIOSCOMI..174735	10,00		6.079,21
05-12-25	CRE. CAMBIOSOP....174735		1.100,00	7.179,21
```

- Columnas: fecha, descripción, débito, crédito, saldo
- Requiere selección de moneda (UYU/USD)
- Amount = débito - crédito

### ITAU Crédito

```
**** 7654	TECHSTORE.COM	Comun	27/11/25	Dólares	2,99
**** 7654	METRO PHARMACY	Comun	29/11/25	Pesos	1.372,00
```

- Columnas: tarjeta, descripción, tipo, fecha, moneda, monto
- La moneda viene en los datos (se normaliza automáticamente)

### Scotia Crédito

```
28/11/2025	SKY AIRLINE / MONTEVIDEO	UYU 0,00	USD 140,50
01/12/2025	PAYPAL *MCDONALS	UYU 0,00	USD 50,00
```

- Columnas: fecha, descripción, monto UYU, monto USD
- Usa automáticamente el monto != 0

### BBVA Crédito

```
19/11/2025	5500321487659234	METRO SUPPLIES	734,00		NOVIEMBRE / 2025
13/11/2025	5500321487659234	METRO SUPPLIES	1.035,00		NOVIEMBRE / 2025
```

- Columnas: fecha, tarjeta, descripción, monto UYU, monto USD, mes
- Usa automáticamente el monto != 0

## Arquitectura

```
polls/copy_paste/
├── __init__.py
├── configs.yaml         # Configuración de formatos bancarios
├── parsers.py           # Lógica de parsing y detección
├── cleaners.py          # Normalización de datos (montos, fechas, monedas)
├── validators.py        # Validación de transacciones
└── utils.py             # Utilidades (carga de config, etc)
```

## Agregar un nuevo banco

Para agregar soporte para un nuevo banco, edita `configs.yaml`:

```yaml
nuevo_banco:
  name: "Nombre del Banco"
  description: "Descripción del formato"
  delimiter: "\t"  # Separador de columnas
  requires_currency: false  # true si necesita selección manual
  source_prefix: "banco:"
  columns:
    - name: "fecha"
      index: 0
      type: "date"
      format: "%d/%m/%Y"
    - name: "description"
      index: 1
      type: "string"
    - name: "amount"
      index: 2
      type: "amount"
    - name: "currency"
      index: 3
      type: "currency"
  amount_calculation: "direct"  # o "debito - credito" o "use_non_zero"
```

## API Endpoints

### `GET /polls/bulk-add/`
Muestra la interfaz de importación

### `POST /polls/bulk-add/parse/`
Parsea los datos y retorna preview

**Request:**
```json
{
  "raw_text": "...",
  "bank": "itau_debito",
  "currency": "UYU"  // opcional
}
```

**Response:**
```json
{
  "success": true,
  "transactions": [...],
  "validation_errors": [...],
  "total_parsed": 10,
  "total_valid": 9
}
```

### `POST /polls/bulk-add/confirm/`
Guarda las transacciones seleccionadas

**Request:**
```json
{
  "transactions": [
    {
      "date": "2025-12-05",
      "description": "TECHSTORE.COM",
      "amount": "2.99",
      "currency": "USD",
      "source": "itau:7654"
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "created": 1,
  "message": "1 transaction(s) created successfully"
}
```

## Testing

Para probar el módulo manualmente:

```python
from djangotutorial.polls.copy_paste.parsers import TransactionParser
from djangotutorial.polls.copy_paste.utils import load_yaml_config

config = load_yaml_config()
parser = TransactionParser(config)

raw_text = """05-12-25\tDEB. EJEMPLO\t10,00\t\t6.079,21"""
transactions, errors = parser.parse(raw_text, "itau_debito", "UYU")

print(transactions)
```
