# Deploy a Railway - Guía Rápida

## TL;DR - Pasos Rápidos

```bash
# 1. Login en Railway
railway login

# 2. Inicializar proyecto
cd /Users/rebele/app-finanzas
railway init

# 3. Agregar PostgreSQL
railway add  # Selecciona PostgreSQL

# 4. Configurar variables en Railway Dashboard
# Ir a: https://railway.com/dashboard
# Variables → Add Variables
# PGDATABASE, PGUSER, PGPASSWORD, PGHOST, PGPORT (referencias a Postgres service)
# DJANGO_SECRET_KEY (generar clave segura)
# DEBUG = False

# 5. Deploy
railway up
```

## Variables de Entorno a Configurar en Railway

Copiar exactamente estas referencias (Railway las resolverá automáticamente):

```
PGDATABASE=${{Postgres.PGDATABASE}}
PGUSER=${{Postgres.PGUSER}}
PGPASSWORD=${{Postgres.PGPASSWORD}}
PGHOST=${{Postgres.PGHOST}}
PGPORT=${{Postgres.PGPORT}}
DJANGO_SECRET_KEY=<generar-nueva-clave-aquí>
DEBUG=False
```

## Generar DJANGO_SECRET_KEY

Opción 1: En terminal Python
```python
from django.core.management.utils import get_random_secret_key
print(get_random_secret_key())
```

Opción 2: Online
https://djecrety.ir/

## Verificar después del Deploy

```bash
# Ver logs
railway logs

# Verificar health
railway status

# SSH a la aplicación
railway shell
```

## Problemas Comunes

**Error: PGDATABASE not set**
→ Agregar variables de PostgreSQL en Railway Dashboard

**Error: ModuleNotFoundError**
→ Verificar que requirements.txt tiene todas las dependencias

**Error: Static files not found**
→ WhiteNoise está en MIDDLEWARE, debería funcionar automáticamente

**Error: Database connection**
→ Verificar que las referencias a variables de Postgres son correctas con `${{Postgres.VAR}}`

## Documentación Completa

Ver: [RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md)
Ver: [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md)
