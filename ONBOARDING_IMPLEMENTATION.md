# Implementación del Flow de Onboarding

## Resumen

Se ha implementado un sistema completo de onboarding para nuevos usuarios que los guía a través de 5 pasos configurando:
1. Categorías por defecto
2. Proyectos
3. Integración con Splitwise
4. Configuración de email
5. Finalización del onboarding

## Archivos Creados

### 1. `backend/expenses/default_config.py`
Archivo de configuración centralizada con:
- 7 categorías por defecto (Casa, Transporte, Salidas, Entretenimiento, Otros gastos, Pago de tarjetas, Ingresos)
- 1 proyecto de ejemplo (Vacaciones de verano)
- Mapeo de pasos de onboarding

### 2. `backend/expenses/onboarding_middleware.py`
Middleware que:
- Detecta si el usuario ha completado el onboarding
- Redirige automáticamente al paso correspondiente según `onboarding_step`
- Permite acceso a URLs específicas durante el onboarding

### 3. `backend/expenses/templatetags/expense_filters.py`
Filtros de template personalizados:
- `multiply`: Para calcular porcentajes de progreso en la barra

### 4. Migraciones
- `0012_category_counts_to_total_category_description_and_more.py`: Agrega nuevos campos
- `0013_update_existing_categories.py`: Actualiza categorías existentes

## Archivos Modificados

### 1. `backend/expenses/models.py`
- **Nuevo modelo `UserProfile`**: con campo `onboarding_step` (0-5)
- **Category**: agregados `counts_to_total` y `description`
- **Project**: agregado `description`

### 2. `backend/expenses/signals.py`
- Nuevo signal para crear `UserProfile` al registrarse
- Nuevo signal para crear categorías y proyectos por defecto
- Signal existente de email config mantenido

### 3. `backend/expenses/views.py`
- Funciones helper: `_get_onboarding_context()` y `_advance_onboarding()`
- `CategoryListView`: agregado contexto y manejo de POST para avanzar
- `ProjectListView`: agregado contexto y manejo de POST para avanzar
- `splitwise_status`: agregado contexto y manejo de POST para avanzar
- `profile`: agregado manejo de finalización de onboarding y contexto

### 4. `backend/expenses/urls.py`
- Eliminadas rutas específicas de onboarding (se reutilizan vistas existentes)

### 5. `backend/expenses/admin.py`
- Registrado `UserProfile` en el admin

### 6. `backend/misfinanzas/settings.py`
- Agregado `OnboardingMiddleware` a la lista de middleware

### 7. Templates actualizados:
- **`backend/templates/manage/list.html`**: Banner de onboarding para pasos 1 y 2
- **`backend/templates/manage/splitwise.html`**: Banner de onboarding para paso 3
- **`backend/templates/profile.html`**: Banner de onboarding para pasos 4 y 5

## Flujo de Usuario

### Registro
1. Usuario se registra → se crea `UserProfile` con `onboarding_step=1`
2. Se crean 7 categorías por defecto (con descripciones)
3. Se crea 1 proyecto de ejemplo
4. Se crea configuración de email única

### Paso 1: Categorías (manage/categories/)
- Usuario ve banner explicativo con categorías predefinidas
- Puede editar/agregar/eliminar categorías
- Botón "Mis Categorías Están Listas" → avanza a paso 2

### Paso 2: Proyectos (manage/projects/)
- Usuario ve banner explicativo sobre qué son los proyectos
- Ve el proyecto de ejemplo "Vacaciones de verano"
- Puede editar/agregar/eliminar proyectos
- Botón "Ya Configuré Mis Proyectos" → avanza a paso 3

### Paso 3: Splitwise (manage/splitwise/)
- Usuario ve banner explicativo sobre Splitwise
- Puede conectar su cuenta de Splitwise (opcional)
- Botón "Ya Configuré Split / Volveré Más Tarde" → avanza a paso 4

### Paso 4: Email (profile/)
- Usuario ve su dirección de email única para reenvíos
- Banner explica cómo usar la funcionalidad
- Botón "Ya Configuré el Mail / Volveré Más Tarde" → avanza a paso 5

### Paso 5: Finalizar (profile/)
- Usuario ve resumen de funcionalidades disponibles
- Botón "¡Empezar a Usar Cachin!" → `onboarding_step=0` (completo)
- Redirige a perfil sin banner de onboarding

## Características Destacadas

### ✅ Reutilización de código
- No se crearon vistas duplicadas
- Se modificaron las vistas existentes para soportar modo onboarding
- Templates existentes adaptados con banners condicionales

### ✅ Configuración centralizada
- Archivo `default_config.py` permite modificar fácilmente categorías/proyectos por defecto
- Fácil agregar más pasos o cambiar el flujo

### ✅ UX mejorada
- Barra de progreso visual en cada paso
- Explicaciones claras de cada funcionalidad
- Opción de "volver más tarde" para pasos opcionales
- Recordatorios de que todo es modificable después

### ✅ Robustez
- Middleware maneja automáticamente las redirecciones
- Signals crean datos por defecto de forma confiable
- Migraciones incluyen actualización de datos existentes

## Próximos Pasos

Para activar el onboarding en tu aplicación:

1. **Aplicar migraciones**:
   ```bash
   cd backend
   python manage.py migrate
   ```

2. **Crear superusuario** (si no existe):
   ```bash
   python manage.py createsuperuser
   ```

3. **Probar con un usuario nuevo**:
   - Registrar un nuevo usuario
   - Verificar que se redirija automáticamente al paso 1
   - Completar todo el flujo

4. **Opcional - Resetear onboarding de usuario existente**:
   ```python
   # En Django shell
   from django.contrib.auth import get_user_model
   User = get_user_model()
   user = User.objects.get(username='tu_usuario')
   user.profile.onboarding_step = 1
   user.profile.save()
   ```

## Notas Técnicas

- El middleware se ejecuta después de `AuthenticationMiddleware` para tener acceso a `request.user`
- Las URLs permitidas durante onboarding están hardcodeadas en el middleware
- El campo `counts_to_total` en Category permite excluir "Pago de tarjetas" de totales mensuales
- Los signals se ejecutan automáticamente al crear un usuario (no requiere cambios en la vista de registro)
