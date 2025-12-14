

Queremos agregar un sistema mediante el cual cada usuario tiene asignada una casilla de mail a la que puede reenviar transacciones.

El sistema deberia de forma periodica revisar el mail, descargar todos los mails asociados y procesarlos. Por ahora vamos a ignorar la parte de generar la transaccion de un mail y vamos a enforcarnos en obtener dichos mails.

Tenemos acceso a cuentas de mail @cachinapp.com y me gustaría que para cada usuario generaramos una cuenta de mail con el formato <random-string>.automation@cachinapp.com por ejemplo: az4b6811adkasdz.automatino@cachinapp.com

Esto se gudaría con una modelo de configuración de usuario y se crearía automaticamente cuando un usario nuevo se crea.

Por otra parte, queremos implementar un script que dadas las credenciales de la casilla de correo se conceta y descarga todos los mails nuevos. Ya vamos a qurerar condiciones de que mail descargar y que mail no.


Luego de descargar cada mail, vamos a iterar por todos los mails y si hay un usario para el que coincide la dirección (la bandeja permite recibir mails con varias direcciones), entonces vamos a descarglo (el mail) en formato eml, guardarlo en la base de datos y mostrarselo al usuario.

Vamos a tener un modelo de mails asocidos a cada usario y cada usuario va a poder ver los mails que procesamos. Entonces en el perfil de cada usario vamos a poder ver todos los mails automatizados que recibimos. 


Cosas que tenemos que implementar:


1) Asociarle a cada usuario una casilla de mail
2) Un script que se conecta (usario y contraseña) al mail y descarga todos los últimos mails. Esto tiene que correr en el background (celery?)
3) Un script que para email valido, lo guarda en el perfil del usuario corrspondiente.
4) Tenemos que ver si usamos celery como hacemos para poder correr local y en railway (y si necesitamos hacer cambios)


---

Estado actual (implementado) — 2025-12-14

- Modelos creados:
	- `expenses.models.UserEmailConfig`: genera automáticamente alias por usuario con formato `automation.<random>@cachinapp.com` al crear un usuario.
	- `expenses.models.UserEmailMessage`: guarda el EML crudo y metadatos (subject, from, to, message_id).
- Señal `post_save` en `expenses/signals.py` para auto-crear el alias al crear un nuevo usuario.
- Admin actualizado (`expenses/admin.py`) para gestionar y visualizar estas entidades.
- Comando IMAP: `manage.py fetch_emails` (en `expenses/management/commands/fetch_emails.py`):
	- Se conecta por IMAP, busca `UNSEEN`, matchea destinatarios con los alias y guarda los emails.
	- Configurable por variables: `EMAIL_FETCH_IMAP_HOST`, `EMAIL_FETCH_IMAP_PORT`, `EMAIL_FETCH_IMAP_SSL`, y opcionalmente `EMAIL_FETCH_USER`/`EMAIL_FETCH_PASS`.
- Perfil del usuario (`backend/templates/profile.html`) muestra el alias y lista básica de emails guardados.
- `.env.example` actualizado con todas las variables necesarias.
- Documentación en `README.md` con instrucciones para correr el comando local y en Railway.

Pendiente / Próximos pasos

- Filtros de ingestión: decidir criterios de qué emails descargar/ignorar (dominios, remitentes, tamaños, adjuntos).
- Descargar EML por demanda: endpoint para bajar el archivo EML de un email almacenado.
- Parser de mails → transacciones: transformar emails válidos en transacciones.
- UI de administración: test de conexión IMAP y reintentos.

---

Ejecución periódica con Celery (2025-12-14)

- Tarea: `expenses.tasks.fetch_emails_task` ejecuta el management command `fetch_emails`.
- Schedule: Celery Beat, diario 04:00 UTC (config en `CELERY_BEAT_SCHEDULE`).

Variables nuevas
- `CELERY_BROKER_URL` (p.ej. `redis://localhost:6379/0` o `REDIS_URL` en Railway)
- `CELERY_RESULT_BACKEND` (puede ser el mismo Redis: `redis://.../1`)
- `CELERY_TIMEZONE` (default `UTC`)
- `CELERY_TASK_ALWAYS_EAGER` (poner `True` para ejecutar sin broker en local)

Local (rápido, sin Redis)
1) En `.env`: `CELERY_TASK_ALWAYS_EAGER=True`
2) Invoca la tarea para probar:
	```bash
	uv run python manage.py shell -c "from expenses.tasks import fetch_emails_task; fetch_emails_task.delay()"
	```
	(Se ejecuta inline en modo eager.)

Local (con Redis)
1) `brew install redis` (si no lo tienes) y luego `redis-server` en otra terminal.
2) En `.env`:
	```
	CELERY_BROKER_URL=redis://localhost:6379/0
	CELERY_RESULT_BACKEND=redis://localhost:6379/1
	CELERY_TASK_ALWAYS_EAGER=False
	CELERY_TIMEZONE=UTC
	```
3) Corre worker y beat en terminales separadas:
	```bash
	uv run celery -A misfinanzas worker -l info
	uv run celery -A misfinanzas beat -l info
	```
4) Para forzar ejecución inmediata:
	```bash
	uv run python manage.py shell -c "from expenses.tasks import fetch_emails_task; fetch_emails_task.delay()"
	```

Railway
1) Añade servicio Redis y usa su `REDIS_URL` para `CELERY_BROKER_URL` y `CELERY_RESULT_BACKEND`.
2) Procfile (procesos):
	```
	web: cd backend && python manage.py migrate && python manage.py collectstatic --noinput && gunicorn --worker-tmp-dir /dev/shm misfinanzas.wsgi:application
	worker: cd backend && celery -A misfinanzas worker -l info
	beat: cd backend && celery -A misfinanzas beat -l info
	```
3) Mantén `CELERY_TASK_ALWAYS_EAGER=False` en producción.
4) Verifica logs de `beat` (programa la tarea) y `worker` (ejecuta la tarea). Para probar sin esperar la hora:
	```bash
	railway run --service <web-or-worker> "cd backend && python manage.py shell -c \"from expenses.tasks import fetch_emails_task; fetch_emails_task.delay()\""
	```

Estado pendiente actualizado
- Filtros de ingestión: decidir criterios de qué emails descargar/ignorar.
- Descargar EML por demanda: endpoint para bajar el archivo EML almacenado.
- Parser de mails → transacciones.
- UI de administración: test de conexión IMAP y reintentos.