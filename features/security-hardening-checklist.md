# Checklist de Endurecimiento y Mitigación de Bots (Namecheap + Railway + Django)

Esta lista resume TODO lo necesario para reducir probes automáticos (/wp-admin, /.env, xmlrpc.php…), endurecer tu despliegue en Railway y dejar menos ruido en logs. Cada ítem tiene una breve justificación.

## 1) DNS y perímetro (Namecheap con o sin Cloudflare)

- [ ] Apuntar dominio a Railway (mínimo viable)
  - Justificación: sirve tu app bajo tu dominio.
  - En Namecheap: crea `CNAME` para `www` → tu subdominio `xxxx.up.railway.app`.
  - Si quieres usar el apex (raíz) `cachinapp.com`, Namecheap no admite CNAME en apex; solución recomendada: usar Cloudflare como DNS (CNAME flattening) o redirigir `apex → www`.

- [ ] (Recomendado) Poner Cloudflare delante
  - Justificación: WAF gestionado, rate limiting y bot mitigation en el perímetro.
  - Pasos: en Namecheap cambia Nameservers → “Custom DNS” con los 2 nameservers que da Cloudflare; añade registros en Cloudflare (Proxy ON/“naranja”).

- [ ] SSL/TLS en Cloudflare
  - Justificación: cifrado extremo a extremo.
  - Ajuste: SSL/TLS → “Full (strict)”.

- [ ] Cloudflare WAF: activar Managed Rules
  - Justificación: bloquea patrones comunes (WordPress/PHP probes) sin tocar tu app.
  - WAF → Managed rules → activar OWASP + WordPress + PHP (si tu plan lo permite).

- [ ] Cloudflare Rate Limiting
  - Justificación: mitiga scraping/fuerza bruta.
  - Security → WAF → Rate limiting rules: por ejemplo 60 req/min por IP a `*cachinapp.com/*` con acción “Block” o “Challenge”. Ajusta según tráfico real.

- [ ] Cloudflare Firewall Rules (reglas simples)
  - Justificación: corta rutas que tu app no usa.
  - Security → WAF → Custom rules → Create:
    - Expresión: `(http.request.uri.path contains ".php") or (http.request.uri.path starts_with "/wp-") or (http.request.uri.path eq "/xmlrpc.php") or (http.request.uri.path eq "/.env")`
    - Acción: Block (o Managed Challenge).

- [ ] Proteger ruta de admin con Cloudflare Access (Zero Trust) o IP allowlist
  - Justificación: reduce muchísimo la superficie.
  - Zero Trust → Access → Applications → Self-hosted → Path `/TU_ADMIN_URL/*` → Política “Email ends with tu-dominio” o lista de usuarios.

## 2) Configuración en Railway (variables de entorno)

- [ ] `ALLOWED_HOSTS`
  - Justificación: restringe hosts válidos que sirve Django.
  - Valor ejemplo: `cachinapp.com,.railway.app`

- [ ] `ADMIN_URL`
  - Justificación: mover admin lejos de `/admin/` reduce probes.
  - Valor ejemplo: `secure-admin-89c1` (elige uno propio). Acceso en `https://cachinapp.com/secure-admin-89c1/`.

- [ ] `SECURE_SSL_REDIRECT=True`
  - Justificación: fuerza HTTPS en prod.

- [ ] (Opcional avanzado) HSTS
  - Justificación: fija HTTPS en navegadores.
  - `SECURE_HSTS_SECONDS=31536000`, `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`, `SECURE_HSTS_PRELOAD=True` (activa sólo cuando todo el dominio sirve HTTPS correctamente).

- [ ] `DJANGO_LOG_LEVEL=WARNING`
  - Justificación: reduce verbosidad en prod; los 404 ruidosos los filtra el nuevo logger.

- [ ] Revisar `USE_POSTGRES=True` y `DEBUG=False`
  - Justificación: activar rama de configuración de producción.

## 3) Cambios ya aplicados en el código (repasar y desplegar)

- [x] Middleware de bloqueo temprano
  - Archivo: `backend/misfinanzas/middleware.py`.
  - Justificación: devuelve 410 rápido para `/wp-admin`, `/.env`, `xmlrpc.php`, etc., reduciendo carga y ruido.

- [x] Filtro de logging para 404 ruidosos
  - Archivo: `backend/misfinanzas/logging_filters.py` y ajustes en `settings.LOGGING`.
  - Justificación: suprime WARN de probes comunes en `django.request`.

- [x] `robots.txt` y `favicon.ico`
  - Ruta: `robots.txt` (200) y `favicon.ico` (204 si no hay icono) en `misfinanzas/urls.py`; plantilla en `backend/templates/robots.txt`.
  - Justificación: evita 404 innecesarios.

- [x] `ADMIN_URL` configurable
  - Definido en `settings.py` y usado en `urls.py`.
  - Justificación: reduce escaneo sobre `/admin/` predecible.

- [x] Endurecimiento de seguridad en prod
  - HSTS, cookies seguras, redirect HTTPS, referrer policy.
  - Justificación: buenas prácticas de Django en producción.

## 4) Endurecimiento adicional (opcional muy recomendado)

- [x] Rate limiting/fuerza bruta en login dentro de Django (implementado)
  - Se añadió `django-axes` al proyecto y configurado en `INSTALLED_APPS`, `AUTHENTICATION_BACKENDS` y `MIDDLEWARE`.
  - Variables opcionales: `AXES_FAILURE_LIMIT` (por defecto 5), `AXES_COOLOFF_HOURS` (por defecto 1), `AXES_ENABLED` (auto True en prod), todas vía Railway.
  - Justificación: bloquea ataques de fuerza bruta al login.
  - Post-deploy: ejecutar migraciones (Axes crea sus tablas).
    ```bash
    # En Railway (o donde ejecutes manage.py)
    python backend/manage.py migrate
    ```
  - Verificación manual: provocar bloqueos con usuario real o inventado.
    ```bash
    # 5 intentos fallidos por defecto
    for i in {1..5}; do \
      curl -s -o /dev/null -w "%{http_code}\n" -c cookies.txt -b cookies.txt \
        -X POST https://cachinapp.com/accounts/login/ \
        -H "Content-Type: application/x-www-form-urlencoded" \
        --data "username=usuario&password=incorrecta&csrfmiddlewaretoken=$(curl -s https://cachinapp.com/accounts/login/ | grep -o 'name=\"csrfmiddlewaretoken\" value=\"[^\"]*' | sed -E 's/.*value=\"([^\"]*).*/\1/')"; \
    done
    # El siguiente intento debería dar 429/403 según configuración
    curl -i https://cachinapp.com/accounts/login/
    ```

- [ ] Cambiar URL de admin periódicamente y auditar usuarios admin
  - Justificación: reduce exposición y riesgo si se filtra la ruta.

- [ ] Telemetría/alertas
  - Sentry o equivalente (DSN via `SENTRY_DSN`).
  - Justificación: detectar picos, errores y patrones anómalos.

## 5) Verificación rápida (post-deploy)

- [ ] `robots.txt` responde 200
  - `curl -i https://cachinapp.com/robots.txt`

- [ ] `favicon.ico` responde 204 (si no tienes icono aún)
  - `curl -i https://cachinapp.com/favicon.ico`

- [ ] Probes devuelven 410
  - `curl -i https://cachinapp.com/wp-admin/setup-config.php`
  - `curl -i https://cachinapp.com/xmlrpc.php`
  - `curl -i https://cachinapp.com/.env`

- [ ] Admin responde en nueva ruta y está protegido
  - `curl -i https://cachinapp.com/$ADMIN_URL/`
  - Si usas Cloudflare Access/IP allowlist: confirmar challenge/bloqueo desde una red no permitida.

- [ ] Logs de Railway sin ruido de WordPress
  - Observar reducción de `WARNING django.request: Not Found: /wp-*`.

## 6) Notas sobre CSRF y orígenes confiables

- `CSRF_TRUSTED_ORIGINS` ya incluye `https://cachinapp.com` y dominios de Railway. Si usas `www.cachinapp.com` u otro subdominio, añade ese origen en settings o hazme saber y lo parametrizamos por env.

---

¿Quieres que deje preconfigurado `django-axes` (rate limiting) y un ejemplo de reglas específicas de Cloudflare para tu dominio? Puedo añadir el paquete y el snippet de settings si lo confirmas.
