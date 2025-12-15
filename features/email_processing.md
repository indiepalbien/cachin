

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

Parser de Visa con librería (mail-parser)
- Dependencia: `mail-parser` agregada a requirements/pyproject.
- Módulo: `backend/expenses/email_parsers/visa.py` usa `mailparser.parse_from_bytes` para extraer campos:
	- description ← Comercio
	- source ← Tarjeta con prefijo `visa:` (ej. visa:3048)
	- currency ← Moneda
	- amount ← Monto (Decimal)
	- external_id ← message-id (fallback: hash simple de contenido)
- Archivo de ejemplo: `features/ejemplo.eml`
- Para probar en shell local:
	```bash
	uv run python manage.py shell -c "from expenses.email_parsers.visa import parse_visa_alert; import pathlib; raw=pathlib.Path('features/ejemplo.eml').read_bytes(); print(parse_visa_alert(raw))"
	```

Ingesta automática y gating del remitente
- Procesa solo `UserEmailMessage` sin `processed_at`.
- Acepta Visa si el remitente es `DoNotReplyAlertadeComprasVisa@visa.com` en envelope From, en los From parseados del EML o si aparece en el cuerpo (para reenviados).
- Si no matchea, marca `processing_error="skipped_non_visa_sender"` y no intenta parsear.
- Logging: la ingesta registra envelope_from, froms parseados, saltos por remitente/amount/currency, creación de transacción o duplicados, y excepciones.


======================================= Hoy ========================

Acabo de crear un mail `ejmplo.md` que contiene uno de los mails que vamos a recibir y procesar.

En este caso se trata de un email de visa.

Tenemos que hacer parsear el contenido y generar una transacción con las siguientes características


comercio = description
tarjeta = source pero agreguemos "visa:" antes entonces 1234 es "visa:1234"
autorización -> ignorar pero tiene que ser un nuevo, si es "pending", ignorar
referencia -> ignorar
moneda = currency 
monto = amount
message-id -> external id


External id es una clave unica de cada transaccion que evita que agregemos transacciones duplicadas. No es la "unique id" pero no puede haber duplicadas. Si no tenemos esto, agreguemoslo.

Una segunda cosa: Si una transacción estuvise duplicada, deberímaos mostrarsela al usuario como "pendiente" en lugar de incluirla de entrada o rechazarla de entrada.

