FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY manage.py .
COPY config ./config
COPY core ./core
COPY listener ./listener

RUN DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput \
    && useradd --create-home app \
    && mkdir -p /app/media \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
