"""
Ejemplos de uso del sistema de reglas inteligentes de categorización.

Este archivo muestra cómo usar el rule_engine desde dentro de la aplicación.
"""

from django.contrib.auth import get_user_model
from decimal import Decimal
from expenses.models import Category, Payee, Transaction
from expenses.rule_engine import (
    sanitize_description,
    generate_categorization_rules,
    find_matching_rules,
    apply_best_matching_rule,
    apply_rules_to_all_transactions,
    get_user_rule_stats,
    cleanup_stale_rules,
)

User = get_user_model()


# ============================================================================
# EJEMPLO 1: Sanitizar una descripción
# ============================================================================

def example_sanitize():
    """Mostrar cómo se sanitiza una descripción."""
    
    descriptions = [
        "Sole y Gian f*HANDY*",
        "PAYPAL *NAMECHEAP",
        "STARB COFFEE SHOP",
        "TRANSFER TO JOHN DOE",
    ]
    
    for desc in descriptions:
        tokens = sanitize_description(desc)
        print(f"{desc:40} → {tokens}")


# ============================================================================
# EJEMPLO 2: Generar reglas cuando un usuario categoriza
# ============================================================================

def example_generate_rules(user):
    """
    Cuando un usuario categoriza una transacción manualmente,
    generar las 4 variantes de reglas.
    """
    
    # Obtener la categoría y payee
    category = Category.objects.get(user=user, name="Transferencias")
    payee = Payee.objects.get(user=user, name="Sole")
    
    # Generar reglas basadas en esa categorización
    rules = generate_categorization_rules(
        user=user,
        description="Sole y Gian f*HANDY*",
        amount=Decimal("582.00"),
        currency="UYU",
        category=category,
        payee=payee,
    )
    
    print(f"Se crearon {len(rules)} variantes de reglas:")
    for i, rule in enumerate(rules, 1):
        print(f"  {i}. {rule}")


# ============================================================================
# EJEMPLO 3: Encontrar reglas que coincidan con una transacción
# ============================================================================

def example_find_matching(user):
    """
    Buscar todas las reglas que coincidan con una descripción.
    Útil para debugging.
    """
    
    matches = find_matching_rules(
        user=user,
        description="Sole y Gian",
        amount=Decimal("600.00"),
        currency="UYU",
        threshold=0.5,
    )
    
    if matches:
        print(f"Se encontraron {len(matches)} reglas coincidentes:")
        for rule, score in matches:
            print(f"  - {rule} (puntuación: {score:.2f})")
    else:
        print("No se encontraron reglas coincidentes")


# ============================================================================
# EJEMPLO 4: Aplicar la mejor regla a una transacción individual
# ============================================================================

def example_apply_single_transaction(user):
    """
    Aplicar automáticamente la mejor regla a una transacción.
    """
    
    # Obtener una transacción sin categorizar
    transaction = Transaction.objects.filter(
        user=user,
        category__isnull=True,
    ).first()
    
    if not transaction:
        print("No hay transacciones sin categorizar")
        return
    
    print(f"Transacción antes: {transaction.description}")
    print(f"  Categoría: {transaction.category}")
    print(f"  Payee: {transaction.payee}")
    
    # Aplicar la mejor regla
    applied_rule = apply_best_matching_rule(transaction)
    
    if applied_rule:
        transaction.refresh_from_db()
        print(f"\n✓ Se aplicó la regla: {applied_rule}")
        print(f"  Categoría: {transaction.category}")
        print(f"  Payee: {transaction.payee}")
    else:
        print("\n✗ No se encontró una regla con suficiente confianza")


# ============================================================================
# EJEMPLO 5: Aplicar reglas a todas las transacciones sin categorizar
# ============================================================================

def example_batch_apply(user):
    """
    Aplicar reglas a todas las transacciones sin categorizar de un usuario.
    Útil para procesamiento en batch.
    """
    
    updated, total = apply_rules_to_all_transactions(user, max_transactions=1000)
    
    print(f"Transacciones sin categorizar: {total}")
    print(f"Transacciones categorizadas: {updated}")
    print(f"Éxito: {updated/total*100:.1f}%" if total > 0 else "N/A")


# ============================================================================
# EJEMPLO 6: Ver estadísticas de reglas de un usuario
# ============================================================================

def example_rule_stats(user):
    """
    Obtener estadísticas sobre las reglas de un usuario.
    """
    
    stats = get_user_rule_stats(user)
    
    print(f"Estadísticas de reglas para {user.username}:")
    print(f"  Total de reglas: {stats['total_rules']}")
    print(f"  Uso promedio: {stats['avg_usage']:.1f}")
    print(f"  Precisión promedio: {stats['avg_accuracy']:.1%}")
    print(f"  Total de aplicaciones: {stats['total_applications']}")


# ============================================================================
# EJEMPLO 7: Limpiar reglas obsoletas
# ============================================================================

def example_cleanup_rules(user):
    """
    Eliminar reglas que no se usan y tienen baja precisión.
    """
    
    deleted = cleanup_stale_rules(user, min_usage=0)
    
    print(f"Se eliminaron {deleted} reglas obsoletas")


# ============================================================================
# EJEMPLO 8: Usar en una vista Django (pseudo-código)
# ============================================================================

"""
# En una vista que actualice una transacción:

from django.shortcuts import render, redirect
from django.views.generic import UpdateView
from expenses.models import Transaction
from expenses.rule_engine import generate_categorization_rules

class TransactionUpdateView(UpdateView):
    model = Transaction
    fields = ["date", "description", "amount", "currency", "category", "payee", "comments"]
    
    def form_valid(self, form):
        # Guardar la transacción
        response = super().form_valid(form)
        
        # Generar reglas si la categoría o payee fueron seteados
        transaction = self.object
        if transaction.category or transaction.payee:
            generate_categorization_rules(
                user=self.request.user,
                description=transaction.description,
                amount=transaction.amount,
                currency=transaction.currency,
                category=transaction.category,
                payee=transaction.payee,
            )
        
        return response
"""


# ============================================================================
# EJEMPLO 9: Usar en un signal de Django
# ============================================================================

"""
# En expenses/signals.py:

from django.db.models.signals import post_save
from django.dispatch import receiver
from expenses.models import Transaction
from expenses.rule_engine import generate_categorization_rules

@receiver(post_save, sender=Transaction)
def create_categorization_rules(sender, instance, update_fields, **kwargs):
    # Solo si se actualizó category o payee
    if update_fields and ('category' in update_fields or 'payee' in update_fields):
        if instance.category or instance.payee:
            generate_categorization_rules(
                user=instance.user,
                description=instance.description,
                amount=instance.amount,
                currency=instance.currency,
                category=instance.category,
                payee=instance.payee,
            )
"""


# ============================================================================
# EJEMPLO 10: Monitorear aplicación de reglas
# ============================================================================

def example_monitor_rules(user):
    """
    Ejemplo de cómo monitorear qué reglas se usan más frecuentemente.
    """
    
    from expenses.models import CategorizationRule
    
    # Obtener las top 10 reglas más usadas
    top_rules = CategorizationRule.objects.filter(
        user=user
    ).order_by('-usage_count')[:10]
    
    print(f"Top 10 reglas más usadas para {user.username}:")
    for i, rule in enumerate(top_rules, 1):
        print(f"  {i}. {rule.description_tokens[:30]}...")
        print(f"     Usos: {rule.usage_count}, Precisión: {rule.accuracy:.1%}")
        print()


# ============================================================================
# Script de testing (descomentar para ejecutar)
# ============================================================================

"""
if __name__ == "__main__":
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'misfinanzas.settings')
    django.setup()
    
    # Obtener el primer usuario
    user = User.objects.first()
    
    if user:
        print("=" * 80)
        print(f"Testing con usuario: {user.username}")
        print("=" * 80)
        
        print("\n1. SANITIZACIÓN")
        example_sanitize()
        
        print("\n2. ESTADÍSTICAS")
        example_rule_stats(user)
        
        print("\n3. TRANSACCIONES SINGLE")
        # example_apply_single_transaction(user)
        
        print("\n4. BATCH PROCESSING")
        # example_batch_apply(user)
    else:
        print("No hay usuarios en la base de datos")
"""
