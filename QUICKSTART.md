# Quickstart: Sistema de Reglas Inteligentes

## 📥 Instalación (Ya completada)

```bash
# ✅ Modelo agregado a models.py
# ✅ Migration 0011_add_categorization_rules.py creada
# ✅ python manage.py migrate (ejecutado)
# ✅ Signal agregado a signals.py
# ✅ Admin configurado
```

## 🎯 Uso Inmediato

### Opción 1: Automático (Recomendado)
El sistema funciona automáticamente. Simplemente:

1. **Usuario categoriza una transacción manualmente** en la interfaz
2. **Sistema automáticamente** crea 4 variantes de reglas (via Django Signal)
3. **Futuras transacciones similares** se categorizan automáticamente

### Opción 2: Procesar Transacciones Existentes
```bash
# Aplicar reglas a transacciones sin categorizar
python manage.py apply_categorization_rules --user=alice

# Procesar máximo 100
python manage.py apply_categorization_rules --user=bob --max=100

# Todos los usuarios
python manage.py apply_categorization_rules
```

### Opción 3: Desde Código Python
```python
from expenses.rule_engine import apply_best_matching_rule

# Aplicar una regla a una transacción
applied = apply_best_matching_rule(transaction)
if applied:
    print(f"Categorizada como: {transaction.category}")
```

## 📊 Ver Reglas en Admin

```
1. Ir a http://localhost:8000/admin/
2. Login
3. Ir a "Categorization Rules"
4. Ver todas las reglas creadas
5. Filtrar por usuario, categoría, etc.
```

## 📈 Ejemplo Paso a Paso

### Paso 1: Usuario categoriza
```
Transacción: "STARB COFFEE SHOP" | $5.50 | USD
Usuario asigna: Category="Food" | Payee="Starbucks"
```

### Paso 2: Sistema crea reglas automáticamente
```
✓ Regla 1: (starb, coffee, shop) → Food | Starbucks
✓ Regla 2: (starb, coffee, shop) + 5.50 + USD → [específica]
✓ Regla 3: (starb, coffee, shop) + USD
✓ Regla 4: (starb, coffee, shop) + 5.50
```

### Paso 3: Próxima transacción se categoriza automáticamente
```
Transacción nueva: "STARB COFFEE DOWNTOWN" | $5.75 | USD
✓ Sistema detecta coincidencia
✓ Se asigna automáticamente: Category="Food" | Payee="Starbucks"
```

## 🔍 Debugging

### Ver qué reglas coinciden
```python
from expenses.rule_engine import find_matching_rules

matches = find_matching_rules(
    user=user,
    description="STARB COFFEE",
    amount=Decimal("5.50"),
    currency="USD",
)

for rule, score in matches:
    print(f"Coincidencia: {rule} (puntuación: {score:.2f})")
```

### Ver estadísticas
```python
from expenses.rule_engine import get_user_rule_stats

stats = get_user_rule_stats(user)
print(f"Total reglas: {stats['total_rules']}")
print(f"Total usos: {stats['total_applications']}")
print(f"Precisión promedio: {stats['avg_accuracy']:.1%}")
```

## 🧪 Verificar Instalación

```bash
# Correr tests
python manage.py test expenses.test_rule_engine

# Esperado: 25 tests OK
```

## ⚙️ Configuración (Valores por defecto)

```python
# En rule_engine.py:
MIN_ACCURACY_THRESHOLD = 0.5        # Mínimo para considerar una regla
MIN_SCORE_TO_APPLY = 0.1            # Mínimo para aplicar automáticamente
MIN_TOKEN_LENGTH = 2                # Longitud mínima de token
```

## 📚 Archivos de Referencia

- **Documentación completa**: [CATEGORIZATION_RULES.md](backend/expenses/CATEGORIZATION_RULES.md)
- **Motor de reglas**: [rule_engine.py](backend/expenses/rule_engine.py)
- **Ejemplos de código**: [examples_rules.py](backend/expenses/examples_rules.py)
- **Tests**: [test_rule_engine.py](backend/expenses/test_rule_engine.py)

## 🚀 Próximos Pasos (Opcionales)

1. **Ver UI para reglas** - Agregar vista para visualizar reglas del usuario
2. **Mostrar confianza** - Cuando se sugiere una categorización automática, mostrar % confianza
3. **Limpiar reglas obsoletas** - Crear task periodica para `cleanup_stale_rules()`
4. **Métricas** - Dashboard mostrando reglas más usadas por categoría

## 💡 Tips

- Las descripciones se **normalizan a minúsculas** automáticamente
- Las palabras genéricas como "paypal", "bank", etc. se **ignoran automáticamente**
- Las reglas se **mejoran con uso** - más aplicaciones = mayor prioridad
- El sistema es **case-insensitive** - "STARB" coincide con "starb"
- Las reglas **no sobrescriben categorías existentes** - solo completan las vacías

## ❓ Preguntas Frecuentes

**P: ¿Las reglas se crean automáticamente?**
R: Sí, via Django Signal cuando se actualiza category/payee.

**P: ¿Puedo editar reglas?**
R: Sí, en el admin panel en `/admin/expenses/categorizationrule/`

**P: ¿Las reglas se aplican automáticamente?**
R: Sí, cuando transacciones nuevas coinciden. Usa `apply_rules_to_all_transactions()` para existentes.

**P: ¿Qué pasa si hay múltiples reglas?**
R: Se elige la más específica y con mayor contador de uso.

**P: ¿Puedo deshabilitar el sistema?**
R: Sí, comentar el Signal en `signals.py` o no usar `apply_best_matching_rule()`.

---

**✅ Sistema listo para usar!**
