# App-Finanzas — Quick start

Rápido y mínimo para ejecutar la app de desarrollo.

Prerequisitos
- macOS / Linux
- `curl` (para instalar `uv`)

Instalación de `uv`
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Arrancar en modo desarrollo
```bash
# crear/usar venv gestionado por uv
uv venv

# añadir dependencias necesarias (ejemplo)
uv add fastapi uvicorn jinja2 sqlalchemy pydantic celery

# generar lock y sincronizar (reproducible)
uv lock
uv sync

# ejecutar servidor
uv run uvicorn backend.main:app --reload --port 8000

# abrir http://127.0.0.1:8000/
```

Tests
```bash
uv run pytest -q
```

Estructura notable
- `backend/` — código FastAPI
- `backend/api/` — routers
- `backend/services/` — lógica de negocio
- `backend/templates/` y `backend/static/` — frontend mínimo
- `AGENTE.md` — guía de arquitectura y flujo para añadir features

Si querés que automatice la creación de la estructura de carpetas o añada un ejemplo de test, decime y lo hago.
# app-finzas
# app-finzas
