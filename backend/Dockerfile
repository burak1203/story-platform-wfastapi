FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Sema Alembic ile yonetiliyor: acilista "alembic upgrade head" bunlara ihtiyac duyar
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

EXPOSE 8000

# Tek worker: es zamanlilik kilidi surec ici (worker artirmadan once kilit DB-atomik olmali).
# --no-access-log: SSE ucunda JWT ?token= ile geldigi icin access loglari sir sizdirir.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--no-access-log"]
