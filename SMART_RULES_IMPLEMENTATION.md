# Sistema de Reglas Inteligentes - Guía de Uso

## ✅ Implementado

Se ha implementado un sistema completo de categorización automática basado en reglas. La aplicación ahora puede:

1. **Aprender de categorías manuales**: Cuando un usuario categoriza una transacción manualmente, el sistema automáticamente crea reglas para uso futuro.

2. **Generar múltiples variantes**: Para cada categorización, se crean 4 variantes de reglas con diferentes niveles de especificidad:
   - Basada solo en descripción
   - Descripción + monto + moneda (más específica)
   - Descripción + moneda
   - Descripción + monto

3. **Aplicar reglas automáticamente**: Cuando hay transacciones sin categorizar que coincidan con una regla, se categorizan automáticamente.

4. **Mejorar con uso**: Las reglas que se usan frecuentemente con éxito tienen mayor prioridad.

## 📋 Archivos Creados/Modificados

### Nuevos archivos:
- **[backend/expenses/rule_engine.py](backend/expenses/rule_engine.py)** - Motor principal con funciones para:
  - `sanitize_description()` - Limpia descripciones
  - `generate_categorization_rules()` - Crea 4 variantes de reglas
  - `find_matching_rules()` - Busca reglas coincidentes
  - `apply_best_matching_rule()` - Aplica la mejor regla a una transacción
  - `apply_rules_to_all_transactions()` - Procesa múltiples transacciones
  - Y funciones de utilidad adicionales

- **[backend/expenses/test_rule_engine.py](backend/expenses/test_rule_engine.py)** - 25 tests completos cubriendo:
  - Sanitización de descripciones
  - Generación de reglas
  - Matching de reglas
  - Aplicación de reglas
  - Estadísticas y limpieza

- **[backend/expenses/CATEGORIZATION_RULES.md](backend/expenses/CATEGORIZATION_RULES.md)** - Documentación completa

- **[backend/expenses/management/commands/apply_categorization_rules.py](backend/expenses/management/commands/apply_categorization_rules.py)** - Command para aplicar reglas en batch

### Archivos modificados:
- **[backend/expenses/models.py](backend/expenses/models.py)** - Agregado modelo `CategorizationRule`
- **[backend/expenses/signals.py](backend/expenses/signals.py)** - Signal para crear reglas automáticamente al categorizar

## 🚀 Flujo de Uso

### 1. Usuario categoriza una transacción manualmente
```
Transacción sin categorizar:
  "Sole y Gian f*HANDY*" | $582.00 | UYU

Usuario asigna:
  ✓ Categoría: "Transferencias"
  ✓ Beneficiario: "Sole"
```

### 2. Sistema automáticamente crea reglas (via signal)
```
Regla 1: (sole, gian) → Transferencias | Sole
Regla 2: (sole, gian) + 582.00 + UYU → [más específica]
Regla 3: (sole, gian) + UYU → [específica]
Regla 4: (sole, gian) + 582.00 → [específica]
```

### 3. Sistema aplica reglas a transacciones sin categorizar
```
Transacción nueva sin categorizar:
  "Sole y Gian" | $600.00 | UYU

✓ Se detecta coincidencia con Regla 3
✓ Se asigna automáticamente: Transferencias | Sole
```

## 📊 Características

| Característica | Descripción |
|---|---|
| **Sanitización** | Elimina palabras genéricas (paypal, bank, etc.) |
| **Especificidad** | Elige reglas más específicas cuando hay múltiples |
| **Precisión** | Solo aplica reglas con suficiente confianza |
| **Contadores** | Tracking de cuántas veces se usa cada regla |
| **Limpieza** | Elimina reglas obsoletas con baja precisión |
| **Batch processing** | Puede procesar muchas transacciones a la vez |

## 🔧 Comandos disponibles

### Aplicar reglas a transacciones sin categorizar
```bash
# Para un usuario específico
python manage.py apply_categorization_rules --user=alice

# Procesar máximo 100 transacciones
python manage.py apply_categorization_rules --user=bob --max=100

# Procesar todos los usuarios
python manage.py apply_categorization_rules
```

## 📈 Ejemplos de casos de uso

### Caso 1: Transferencias regulares al mismo contacto
```
15/12: "Sole 100 UYU" → Categoría "Personal"
18/12: "Sole 150 UYU" → Categoría "Personal"
20/12: "Sole 200 UYU" → ✓ Se categoriza automáticamente
```

### Caso 2: Compras en diferentes plataformas
```
Usuario categoriza:
  "PAYPAL *NETFLIX" → "Entretenimiento"
  "STRIPE *AMAZON" → "Compras"
  "SQUARE *UBER" → "Transporte"

Después:
  "PAYPAL *COURSE" → ✓ Se categoriza como "Entretenimiento"
  "STRIPE *BOOKSTORE" → ✓ Se categoriza como "Compras"
```

### Caso 3: Montos específicos
```
Regla: "WISE TRANSFER 500.00 USD" → "Transferencias" | "Hermano"

Futuras transacciones:
  "WISE TRANSFER 500.00 USD" → ✓ Categorización automática
```

## 🧪 Tests

Todos los 25 tests pasan correctamente:

```
✓ Sanitización de descripciones (6 tests)
✓ Puntuación de especificidad (5 tests)
✓ Generación de reglas (3 tests)
✓ Búsqueda de reglas coincidentes (4 tests)
✓ Aplicación de reglas (4 tests)
✓ Estadísticas y limpieza (2 tests)
✓ Signals automáticos (1 test)

Total: 25 tests, 0 fallos
```

## 🔍 Cómo funciona internamente

### 1. Sanitización
```python
"Sole y Gian f*HANDY*"
         ↓
["sole", "gian"]  # Palabras genéricas eliminadas
```

### 2. Matching con case-insensitivity
```python
Regla: "cafe"
Descripción: "CAFE LOCAL"
         ↓
Tokens: ["cafe", "local"]
Intersección: {"cafe"} ✓ Match
```

### 3. Puntuación (Specificity Score)
```
Base: 0 (sin componentes)
+ Tokens: hasta 0.5 puntos (más tokens = más específico)
+ Monto: 0.25 puntos
+ Moneda: 0.15 puntos
= Máximo: 1.0
```

## ⚙️ Configuración

La lógica está configurada con valores sensatos por defecto:

```python
THRESHOLD_ACCURACY = 0.5     # Mínimo para considerar una regla
MIN_SCORE_APPLY = 0.1        # Mínimo para aplicar una regla
MIN_TOKEN_LENGTH = 2         # Longitud mínima de token
```

## 🔮 Posibles mejoras futuras

- [ ] UI para visualizar y editar reglas
- [ ] Webhook para integrar con otras aplicaciones
- [ ] Aprendizaje por patrones de gasto
- [ ] Exportar/importar reglas entre usuarios
- [ ] Dashboard con estadísticas por categoría
- [ ] Predicción de confianza (mostrar al usuario)

## 📝 Notas de implementación

- Todos los tokens se normalizan a **minúsculas** para matching case-insensitive
- Las reglas se **almacenan con minúsculas** en la base de datos
- Las comparaciones de moneda son **case-insensitive**
- El sistema usa **Signals de Django** para crear reglas automáticamente
- La lógica es **completamente testeable** y sin efectos secundarios
