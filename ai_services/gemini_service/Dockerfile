FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY ai_services/requirements-base.txt ai_services/requirements-base.txt
COPY ai_services/gemini_service/requirements.txt ai_services/gemini_service/requirements.txt
RUN pip install -r ai_services/gemini_service/requirements.txt

COPY ai_services/__init__.py ai_services/__init__.py
COPY ai_services/common ai_services/common
COPY ai_services/gemini_service ai_services/gemini_service

RUN useradd --create-home app
USER app

EXPOSE 8000

CMD ["uvicorn", "ai_services.gemini_service.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
