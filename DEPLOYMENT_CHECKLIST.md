# Checklist de Deployment a Railway

## ✅ Cambios Completados

### Configuración de Django (settings.py)
- [x] Import de `os` para variables de entorno
- [x] `SECRET_KEY` desde variable de entorno `DJANGO_SECRET_KEY`
- [x] `DEBUG` desde variable de entorno (por defecto False)
- [x] `ALLOWED_HOSTS = ['*']` para aceptar cualquier dominio en Railway
- [x] Database configurada para PostgreSQL con variables de entorno
- [x] WhiteNoise middleware agregado para servir archivos estáticos
- [x] `STATIC_ROOT` y `STATICFILES_DIRS` configurados

### Archivos de Deployment
- [x] `requirements.txt` - Todas las dependencias necesarias
- [x] `Procfile` - Comando para ejecutar migraciones y servidor Gunicorn
- [x] `.env.example` - Template de variables de entorno
- [x] `RAILWAY_DEPLOYMENT.md` - Instrucciones detalladas

## 🔧 Próximos Pasos (En Railway)

### 1. Login y Setup Inicial
```bash
railway login
cd /Users/rebele/app-finanzas
railway init
```

### 2. Agregar PostgreSQL
```bash
railway add    # Seleccionar PostgreSQL
```

### 3. Configurar Variables de Entorno en Railway Dashboard

**Automáticas (from PostgreSQL service):**
- `PGDATABASE=${{Postgres.PGDATABASE}}`
- `PGUSER=${{Postgres.PGUSER}}`
- `PGPASSWORD=${{Postgres.PGPASSWORD}}`
- `PGHOST=${{Postgres.PGHOST}}`
- `PGPORT=${{Postgres.PGPORT}}`

**Manual:**
- `DJANGO_SECRET_KEY` - Generar una clave segura
- `DEBUG` - `False`

### 4. Deploy
```bash
railway up
```

### 5. Verificaciones Post-Deploy
- [ ] Revisar logs: `railway logs`
- [ ] Migraciones ejecutadas correctamente
- [ ] Archivos estáticos servidos
- [ ] Acceso a la URL pública del servicio
- [ ] Panel de Django admin funciona

## 📝 Notas Importantes

1. **Contraseña PostgreSQL**: Railway la genera automáticamente. Solo referenciarla con `${{Postgres.PGPASSWORD}}`
2. **SECRET_KEY**: Generar una nueva para producción. NO usar la default
3. **DEBUG**: Siempre debe ser `False` en producción
4. **Archivos estáticos**: WhiteNoise los sirve automáticamente desde `STATIC_ROOT`
5. **Migraciones**: Se ejecutan automáticamente cada vez que se hace deploy (vía Procfile)

## 🚀 Deployment desde GitHub (Alternativa)

Si prefieres hacer push a GitHub primero:

1. Commit y push de los cambios
2. En Railway: New Project → Deploy from GitHub
3. Seleccionar el repositorio
4. Agregar las variables de entorno
5. Agregar PostgreSQL
6. Click Deploy

Railway detectará automáticamente que es una app Django y usará el Procfile.

