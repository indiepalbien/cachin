
Este feature permite copiar y pegar transacciones de la páginas de un banco y agregalas en "bulk"

Para esto vamos a tener lo siguiente:

1. Una interfaz que nos permite pegar text libre en varias lineas. La UI debe preguntarle al usuario el banco de origen, pero debería probar todos los formatos asociados a ese banco hasta encontrar el "mejor"
2. Un parser que detecte el formato y genere la lista de transacciones apropiadas
3. Vamos a querer mostrarle al usuario todas las tranacciones y que el usuario apruebe cuales quiere agregar (por defecto todas)


El parser tiene que ser configurable con un archivo "yaml" donde se defininen los distintos tipos de formatos posibles

OBS: montons positivos son gastos y montons negativos son ingresos.

Por ejemplo:

ITAU:
- columnas separadas por tab
- columna 1: numero de cuenta (source)
- columna 2: el monto (amount) formato (,.)
- ...
- columna n: fecha (en formato XXX)

También tenes que tener una función que limpie fechas y montos (pase de 1,200.44 a 1200.44, etc)



======= EJEMPLOS =========

## ITAU (Debito)

05-12-25 	DEB. CAMBIOSCOMI..174735 	10,00 		6.079,21
05-12-25 	CRE. CAMBIOSOP....174735 		1.100,00 	7.179,21
08-12-25 	DEB. VARIOS TARJ. VISA 	833,73 		6.345,48

columnas: fecha, concepto (description), debito, credito, saldo (ignorar)

si hay debito y credito, entonces amount = debito - credito 

la currency tiene que venir dada como inpput del usuario (itau usd, o itau uyu) y estar como metadata en el yaml

## Itau Credito

**** 7654	TECHSTORE.COM	Comun	27/11/25	Dï¿½lares	2,99	
**** 7654	METRO PHARMACY	Comun	29/11/25	Pesos	1.372,00	
**** 7654	COCO MINIMARKET	Comun	29/11/25	Pesos	115,00	
**** 7654	CENTRAL CAFE	Comun	29/11/25	Pesos	195,50	
**** 7654	REDUC. IVA LEY 17934		29/11/25	Pesos	-14,42	
**** 7654	PARKING SERVICES	Comun	29/11/25	Dï¿½lares	0,60	
**** 7654	CENTRAL BAR	Comun	30/11/25	Pesos	1.030,00	

columnas: tarjeta (source, sin el ****: mapear a itau:<numero>), descpricion, Comun = ignorar, fecha, moneda, monto


## Scotia Credito

28/11/2025 	SKY AIRLINE / MONTEVIDEO 	UYU 0,00 	USD 140,50
28/11/2025 	SKY AIRLINE / MONTEVIDEO 	UYU 0,00 	USD 140,50
01/12/2025 	PAYPAL *MCDONALS / 4029357733 	UYU 0,00 	USD 50,00

columnas: fecha, concepto, monto en pesos, monto en usd

## BBVA Credito

19/11/2025 	5500321487659234 	METRO SUPPLIES 	734,00 		NOVIEMBRE / 2025
13/11/2025 	5500321487659234 	METRO SUPPLIES 	1.035,00 		NOVIEMBRE / 2025
11/11/2025 	5500321487659234 	METRO SUPPLIES 	315,00 		NOVIEMBRE / 2025

columnas: fecha, numero de tarjeta (source), descripcion, monto en pesos, monto en dolares, mes (ignora)


============ UI ============

En la página del perfil hay una opción abajo de agregar transaccion que nos lleva a una pagína nueva con el campo para copiar y elegir la fuente. Cuando hacemos click procesa las transacciones y las muestra debajo  (con una check para validar si la queremos agregar o no) y después botenes para agregar las tranasacciones seleccionadas.


=============== DISEÑO DE SOLUCIÓN ===============

### ARQUITECTURA GENERAL

```
┌─────────────────────────────────────────┐
│         UI Layer (Django Template)      │
│  - Input textarea para pegar datos      │
│  - Selector de banco                    │
│  - Selector de moneda (si aplica)       │
│  - Preview con checkboxes               │
│  - Botones de acción                    │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│    Parser Layer (Python Modules)        │
│  - Format detection                     │
│  - Data extraction                      │
│  - Validation                           │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│   Configuration Layer (YAML configs)    │
│  - Bank format definitions              │
│  - Parser rules                         │
│  - Data cleaning strategies             │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│      Database Layer (Django ORM)        │
│  - Save transactions                    │
│  - Update balances                      │
└─────────────────────────────────────────┘
```

### COMPONENTES PRINCIPALES

#### A. Backend - Estructura de carpetas

```
polls/
├── copy_paste/
│   ├── __init__.py
│   ├── parsers.py          # Lógica de parsing
│   ├── validators.py       # Validación de datos
│   ├── cleaners.py         # Limpieza de datos (montos, fechas)
│   ├── configs.yaml        # Configuración de formatos
│   └── utils.py            # Funciones auxiliares
├── views.py                # Vista para procesar bulk import
├── forms.py                # Formulario para paste
└── templates/
    └── polls/
        └── bulk_add.html   # Página con interface de paste
```

#### B. Configuración YAML (configs.yaml)

Estructura base para cada banco:

```yaml
banks:
  itau_debito:
    name: "ITAU Débito"
    delimiter: "\t"
    columns:
      - name: "fecha"
        index: 0
        type: "date"
        format: "DD-MM-YY"
      - name: "description"
        index: 1
        type: "string"
      - name: "debito"
        index: 2
        type: "amount"
      - name: "credito"
        index: 3
        type: "amount"
      - name: "saldo"
        index: 4
        type: "ignore"
    
    # Cálculo de amount: amount = debito - credito
    amount_calculation: "debito - credito"
    
    # Source es fijo (usuario elige cuenta al seleccionar itau_debito)
    source_prefix: "itau:"
    
    # Currency viene del usuario (itau_uyu, itau_usd)
    requires_currency: true
    
  itau_credito:
    name: "ITAU Crédito"
    delimiter: "\t"
    columns:
      - name: "tarjeta"
        index: 0
        type: "string"
      - name: "description"
        index: 1
        type: "string"
      - name: "tipo"
        index: 2
        type: "ignore"  # Comun = ignorar
      - name: "fecha"
        index: 3
        type: "date"
        format: "DD/MM/YY"
      - name: "currency"
        index: 4
        type: "currency"
      - name: "amount"
        index: 5
        type: "amount"
    
    amount_calculation: "direct"  # Usar directamente el campo amount
    source_prefix: "itau:"
    requires_currency: false  # Currency viene en los datos
  
  scotia_credito:
    name: "Scotia Crédito"
    delimiter: "\t"
    columns:
      - name: "fecha"
        index: 0
        type: "date"
        format: "DD/MM/YYYY"
      - name: "description"
        index: 1
        type: "string"
      - name: "monto_uyu"
        index: 2
        type: "amount"
      - name: "monto_usd"
        index: 3
        type: "amount"
    
    # Para formatos con múltiples montos: usar el que sea != 0
    amount_currency_pairs:
      - amount_field: "monto_uyu"
        currency: "UYU"
      - amount_field: "monto_usd"
        currency: "USD"
    
    amount_calculation: "use_non_zero"  # Estrategia: usar monto != 0
    source_prefix: "scotia:"
    requires_currency: false
  
  bbva_credito:
    name: "BBVA Crédito"
    delimiter: "\t"
    columns:
      - name: "fecha"
        index: 0
        type: "date"
        format: "DD/MM/YYYY"
      - name: "tarjeta"
        index: 1
        type: "string"
      - name: "description"
        index: 2
        type: "string"
      - name: "monto_uyu"
        index: 3
        type: "amount"
      - name: "monto_usd"
        index: 4
        type: "amount"
      - name: "mes"
        index: 5
        type: "ignore"
    
    amount_currency_pairs:
      - amount_field: "monto_uyu"
        currency: "UYU"
      - amount_field: "monto_usd"
        currency: "USD"
    
    amount_calculation: "use_non_zero"
    source_prefix: "bbva:"
    requires_currency: false
```

#### C. Módulos Python

**parsers.py:**
- `TransactionParser.parse(raw_text, bank, currency)` → List[TransactionDict]
- `FormatDetector.find_best_match(text, bank=None)` → (best_bank, confidence_score)
- `split_lines_by_delimiter(text, delimiter)` → List[str]

**cleaners.py:**
- `AmountCleaner.normalize_amount(value)` → float (1,200.44 → 1200.44)
- `DateCleaner.normalize_date(value, format_str)` → datetime
- `SourceCleaner.clean_source(value, bank)` → str
- `extract_amount_and_currency(row, config)` → (amount: float, currency: str)

**validators.py:**
- `validate_transaction(txn)` → bool, List[error_messages]
- `check_duplicate_in_batch(txn, batch)` → bool
- `check_required_fields(txn, config)` → bool

**utils.py:**
- Helper functions para parseo genérico

#### D. Vistas Django (views.py)

**BulkAddTransactionView (GET + POST):**
- GET: Renderiza template con form
- POST: Recibe raw_text y banco → Retorna JSON con preview

**ConfirmBulkTransactionsView (POST):**
- Recibe lista de transacciones a agregar
- Valida y crea Transaction objects
- Actualiza balances
- Retorna confirmación

#### E. Frontend (bulk_add.html)

```html
1. Input textarea para pegar
2. Selector de banco (dropdown con opciones de YAML)
3. Selector de moneda (si requires_currency=true)
4. Botón "Procesar" (AJAX)
5. Preview section (inicialmente oculta):
   - Tabla con checkboxes
   - Columnas: Fecha, Descripción, Monto, Moneda, Source
   - Toggle "Seleccionar todos"
   - Indicador de errores/warnings
6. Botón "Agregar seleccionadas" (AJAX)
7. Mensajes de éxito/error
```

### FLUJO DE EJECUCIÓN

1. Usuario paste datos en textarea
2. Selecciona banco (desplegable con opciones del YAML)
3. Si banco requiere currency (requires_currency=true), selecciona moneda
4. Click "Procesar" → AJAX POST /bulk-add/parse/
5. Backend:
   - Parsea raw_text según banco y currency
   - Limpia montos (1,200.44 → 1200.44) y fechas
   - Extrae amount/currency (si múltiples montos, usa el != 0)
   - Valida cada transacción
   - Retorna JSON con preview
6. Frontend muestra preview con checkboxes (default: todos checked)
7. Usuario revisa y deselecciona si necesario
8. Click "Agregar" → AJAX POST /bulk-add/confirm/
9. Backend:
   - Valida duplicados en batch
   - Crea Transaction objects
   - Guarda en DB
   - Retorna confirmación
10. Frontend muestra mensaje de éxito

### VALIDACIONES

✅ Formato reconocido correctamente
✅ Campos requeridos presentes
✅ Montos son números válidos (después de limpiar)
✅ Fechas están en formato válido
✅ No hay duplicados en la importación
✅ Source existe en el usuario
✅ Si hay múltiples montos, usar el != 0

### MANEJO DE ERRORES

- Formato no reconocido → Mostrar mensaje y opciones disponibles
- Parseo fallido en línea X → Mostrar línea problemática
- Validación fallida → Listar campos inválidos por línea
- Campos obligatorios faltantes → Marcar en preview
- Moneda no especificada cuando se requiere → Mostrar selector