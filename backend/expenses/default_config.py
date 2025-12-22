"""
Default configuration for new users.

This file contains initial values that are created when a new user registers,
such as default categories and projects.
"""

DEFAULT_CATEGORIES = [
    {
        "name": "Casa",
        "counts_to_total": True,
        "description": "Gastos relacionados con el hogar: alquiler, servicios, mantenimiento."
    },
    {
        "name": "Transporte",
        "counts_to_total": True,
        "description": "Transporte público, combustible, mantenimiento de vehículo, Uber, etc."
    },
    {
        "name": "Salidas",
        "counts_to_total": True,
        "description": "Restaurantes, bares, cafés, y comidas fuera de casa."
    },
    {
        "name": "Entretenimiento",
        "counts_to_total": True,
        "description": "Cine, streaming, juegos, eventos, y otras actividades recreativas."
    },
    {
        "name": "Otros gastos",
        "counts_to_total": True,
        "description": "Gastos varios que no encajan en otras categorías."
    },
    {
        "name": "Pago de tarjetas",
        "counts_to_total": False,
        "description": "Pagos de resúmenes de tarjeta. Esta categoría NO cuenta en el total mensual para evitar duplicar gastos ya registrados."
    },
    {
        "name": "Ingresos",
        "counts_to_total": True,
        "description": "Salario, freelance, y otras fuentes de ingreso."
    },
]

DEFAULT_PROJECTS = [
    {
        "name": "Vacaciones de verano",
        "description": "Proyecto de ejemplo para agrupar gastos de tus vacaciones, incluso si están en distintas categorías."
    },
]

ONBOARDING_STEPS = {
    0: "completed",  # Onboarding finished
    1: "categories",  # Configure initial categories
    2: "projects",    # Learn about and configure projects
    3: "splitwise",   # Configure Splitwise integration
    4: "email",       # Configure email forwarding
    5: "finish",      # Finish onboarding
}
