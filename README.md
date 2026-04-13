### Pre-commit
```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit install --hook-type pre-push
# запуск в ручную
pre-commit run --all-files
```

### Swagger
```bash
# запуск приложения
docker compose up --build
```

```http
# Открываешь
http://localhost:8000/docs
```
Там будет Swagger UI.

### Полезные ссылки
```http
# Swagger UI:
http://localhost:8000/docs

# ReDoc:
http://localhost:8000/redoc

# OpenAPI schema:
http://localhost:8000/openapi.json

# Health:
http://localhost:8000/health
```