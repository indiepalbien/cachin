# Instrucciones de Deployment en Railway

## Cambios Realizados

Se han realizado los siguientes cambios para preparar la aplicación Django para deployment en Railway:

### 1. **settings.py** - Configuración de Django para producción

- ✅ Agregado `import os` para manejo de variables de entorno
- ✅ `SECRET_KEY` ahora lee de variable de entorno `DJANGO_SECRET_KEY` (con valor por defecto para desarrollo)
- ✅ `DEBUG` ahora lee de variable de entorno `DEBUG` (por defecto `False` para producción)
- ✅ `ALLOWED_HOSTS` configurado como `['*']` (Railway maneja los dominios)
- ✅ Base de datos cambiada de SQLite a PostgreSQL
- ✅ Agregado middleware `WhiteNoiseMiddleware` para servir archivos estáticos
- ✅ Configurado `STATIC_ROOT` y `STATICFILES_DIRS` para gestión de archivos estáticos

### 2. **Dependencias**

- ✅ `requirements.txt` generado con todas las dependencias necesarias:
  - gunicorn (servidor de producción)
  - psycopg (driver de PostgreSQL)
  - whitenoise (servir archivos estáticos)
  - django y otras dependencias del proyecto

### 3. **Procfile**

- ✅ `Procfile` creado con el comando para ejecutar:
  - Migraciones de base de datos
  - Servidor Gunicorn

## Próximos pasos en Railway

### 1. Crear Proyecto en Railway

```bash
railway login
railway init
```

### 2. Agregar Base de Datos PostgreSQL

```bash
railway add  # Selecciona PostgreSQL
```

### 3. Configurar Variables de Entorno

En el panel de Railway, configurar las siguientes variables:

**Variables de Base de Datos** (Railway las proporciona automáticamente):
- `PGDATABASE`: `${{Postgres.PGDATABASE}}`
- `PGUSER`: `${{Postgres.PGUSER}}`
- `PGPASSWORD`: `${{Postgres.PGPASSWORD}}`
- `PGHOST`: `${{Postgres.PGHOST}}`
- `PGPORT`: `${{Postgres.PGPORT}}`

**Variables de Seguridad**:
- `DJANGO_SECRET_KEY`: Generar una clave segura (usa una herramienta como Django Secret Key Generator)
- `DEBUG`: `False`

### 4. Deploy

```bash
railway up
```

### 5. Configurar Dominio Público

Una vez deployado:
1. Ir a Networking en los Settings del servicio
2. Click en "Generate Domain" para obtener una URL pública

## Verificación

Después del deployment, verificar que:
- ✅ Las migraciones se ejecutaron correctamente
- ✅ Los archivos estáticos se sirven correctamente
- ✅ La aplicación es accesible desde el dominio público
- ✅ Las variables de entorno están configuradas

## Notas Importantes

- El archivo `.env` **no debe commitirse** al repositorio. Las variables se configuran en Railway.
- Para desarrollo local, crear un archivo `.env` con valores locales.
- La contraseña de PostgreSQL y la SECRET_KEY deben ser valores seguros en producción.

