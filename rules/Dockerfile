# The rules runner image.    docker build -t antifraud/rules rules/

FROM python:3.14-slim

# PYTHONUNBUFFERED: logs reach `docker compose logs` at once.
# PYTHONDONTWRITEBYTECODE: no .pyc files written into the image at run time.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --no-create-home app

WORKDIR /app
# Requirements before code, so a code change does not reinstall every package.
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY runner.py .
COPY sql/ ./sql/

ARG BUILD_VERSION=local
ENV BUILD_VERSION=${BUILD_VERSION}
LABEL org.opencontainers.image.revision=${BUILD_VERSION} \
    org.opencontainers.image.source="https://github.com/druidpwnz/antifraud_lab"

USER app

# Exec form: python is PID 1 and gets SIGTERM itself, and stops within a second.
CMD ["python", "runner.py"]
