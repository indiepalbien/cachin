# Smart Categorization Rules System

Un sistema inteligente basado en reglas para categorizar transacciones automáticamente.

## Cómo funciona

### 1. **Sanitización de descripciones**

Cuando un usuario categoriza una transacción, el sistema extrae palabras clave significativas de la descripción:

```
Entrada:       "Sole y Gian f*HANDY*"
Tokens:        ["sole", "gian"]
(se ignora:    "y", "f*handy*" - palabras genéricas)

Entrada:       "PAYPAL *NAMECHEAP"
Tokens:        ["namecheap"]
(se ignora:    "paypal" - procesador de pagos genérico)

Entrada:       "STARB ONLINE PAYMENT"
Tokens:        ["starb"]
(se ignora:    "online", "payment" - palabras genéricas)
```

### 2. **Generación de reglas**

Cuando se categoriza una transacción, se crean **4 variantes de reglas**:

```python
transacción: "Sole y Gian f*HANDY*" | $582.00 | UYU
categoría: "Transferencias" | payee: "Sole"

Regla 1: (sole, gian)
Regla 2: (sole, gian) + $582.00 + UYU  [más específica]
Regla 3: (sole, gian) + UYU
Regla 4: (sole, gian) + $582.00
```

Cada regla se almacena por separado para poder usar la más específica que coincida.

### 3. **Aplicación de reglas**

El sistema busca reglas coincidentes en este orden:

1. **Busca por tokens**: Encuentra todas las reglas que contienen los tokens de la descripción
2. **Valida cantidad y moneda**: Si la regla especifica monto/moneda, verifica que coincidan
3. **Calcula puntuación**: Las reglas más específicas (con más tokens, monto, moneda) puntúan más alto
4. **Aplica la mejor**: Si la puntuación es suficientemente alta (≥0.3), aplica la categoría/payee

### 4. **Mejora continua**

- **Contador de uso**: Cada vez que se aplica una regla, aumenta su contador
- **Puntuación de precisión**: Las reglas bien usadas tienen mayor prioridad
- **Limpieza**: Las reglas no utilizadas con baja precisión se pueden eliminar periódicamente

## Uso en la aplicación

### Automático (Signals)

Cuando un usuario actualiza la categoría o payee de una transacción, el sistema automáticamente:

```python
1. Extrae tokens significativos de la descripción
2. Crea 4 variantes de reglas
3. Almacena las reglas para uso futuro
```

### Aplicar a transacciones existentes

```bash
# Aplicar reglas a todas las transacciones de un usuario
python manage.py apply_categorization_rules --user=alice

# Aplicar a un máximo de 100 transacciones
python manage.py apply_categorization_rules --user=bob --max=100

# Aplicar a todos los usuarios
python manage.py apply_categorization_rules
```

### Desde código Python

```python
from expenses.rule_engine import (
    generate_categorization_rules,
    find_matching_rules,
    apply_best_matching_rule,
    apply_rules_to_all_transactions,
)

# 1. Generar reglas cuando se categoriza
rules = generate_categorization_rules(
    user=request.user,
    description="Sole y Gian f*HANDY*",
    amount=Decimal("582.00"),
    currency="UYU",
    category=category_obj,
    payee=payee_obj,
)

# 2. Encontrar reglas coincidentes
matches = find_matching_rules(
    user=request.user,
    description="Sole y Gian f*HANDY*",
    amount=Decimal("582.00"),
    currency="UYU",
    threshold=0.5,  # Solo reglas con ≥50% de precisión
)

# 3. Aplicar la mejor regla a una transacción
applied_rule = apply_best_matching_rule(transaction)

# 4. Aplicar reglas a muchas transacciones
updated, total = apply_rules_to_all_transactions(user, max_transactions=1000)
```

## Palabras genéricas ignoradas

Se ignoran automáticamente palabras como:

- **Procesadores de pago**: paypal, stripe, square, shopify, fastspring
- **Bancos**: bank, transfer, payment, deposit, withdrawal
- **Acciones genéricas**: transaction, pago, compra, venta, order
- **Palabras comunes**: the, a, an, de, la, el, y, o, para, por
- **Patrones**: ref, id, invoice, ticket, via

Esto evita que reglas genéricas bloqueen las más específicas.

## Puntuación de especificidad

Una regla puntúa mayor si:

- Tiene más tokens (máx 0.5 puntos)
- Especifica monto (0.25 puntos)
- Especifica moneda (0.15 puntos)

Se usa para ordenar las coincidencias y seleccionar la mejor automáticamente.

## Ejemplos de uso

### Ejemplo 1: Transacciones a mismo contacto

```
Usuario categoriza:
- 15/12: "Sole 100 UYU" → Categoría "Personales"
- 18/12: "Sole 150 UYU" → Categoría "Personales"
- 20/12: "Sole 200 UYU" → Sin categorizar (pendiente manual)

Sistema automáticamente categoriza la tercera:
✓ Encuentra regla (sole) con puntuación 0.5+
✓ Aplica "Personales" automáticamente
```

### Ejemplo 2: Múltiples procesadores

```
Usuario categoriza:
- "PAYPAL *NETFLIX" → "Entretenimiento"
- "STRIPE *AMAZON" → "Compras"
- "SQUARE *UBER" → "Transporte"

Después:
- "PAYPAL *COURSE" → Se aplica automáticamente con alta confianza
- "STRIPE *BOOKSTORE" → Se aplica automáticamente
```

### Ejemplo 3: Transferencias internacionales

```
Usuario categoriza:
- "WISE TRANSFER 500.00 USD" → "Transferencias" | Payee "Hermano"
- "WISE TRANSFER 500.00 USD" → "Transferencias" | Payee "Hermano" (después)

Sistema crea reglas:
1. (wise, transfer) → Hermano
2. (wise, transfer, 500.00, USD) → Hermano [más específica]
3. (wise, transfer, USD) → Hermano
4. (wise, transfer, 500.00) → Hermano

Futuras transacciones con "WISE TRANSFER 500.00 USD" se categorizan automáticamente.
```

## Configuración recomendada

En tu `settings.py` o archivo de configuración:

```python
# Umbral mínimo de precisión para aplicar reglas automáticamente
CATEGORIZATION_RULE_MIN_ACCURACY = 0.5

# Umbral mínimo de puntuación para aplicar una regla
CATEGORIZATION_RULE_MIN_SCORE = 0.3

# Limpiar reglas sin usar con precisión baja después de este período
CATEGORIZATION_RULE_CLEANUP_DAYS = 90

# Máximo de reglas por usuario (opcional)
CATEGORIZATION_RULE_MAX_PER_USER = 5000
```

## Ventajas del sistema

✅ **Aprende del usuario**: Mejora con cada categorización manual  
✅ **Automático**: Después de unos pocos ejemplos, categoriza nuevas transacciones  
✅ **Flexible**: Soporta múltiples campos (descripción, monto, moneda)  
✅ **Específico**: Elige la regla más específica cuando hay múltiples coincidencias  
✅ **Mantenible**: Identifica y elimina reglas obsoletas  
✅ **Integrado**: Funciona con el flujo normal de categorización  

## Próximas mejoras posibles

- [ ] UI para ver y editar reglas directamente
- [ ] Métricas de precisión por categoría
- [ ] Predicción de confianza (mostrar al usuario)
- [ ] Reglas basadas en patrones más complejos
- [ ] Aprendizaje por patrones de gasto (tendencias)
- [ ] Exportar/importar reglas entre usuarios
- [ ] Webhook para integración con otras apps
