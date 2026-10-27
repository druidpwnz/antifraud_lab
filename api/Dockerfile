# The API image.    docker build -t antifraud/api api/

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
COPY app/ ./app/

ARG BUILD_VERSION=local
ENV BUILD_VERSION=${BUILD_VERSION}
LABEL org.opencontainers.image.revision=${BUILD_VERSION} \
    org.opencontainers.image.source="https://github.com/druidpwnz/antifraud_lab"

USER app
EXPOSE 8000

# No --reload: that is for development. --host 0.0.0.0: listen on the container's
# network, not only on its own localhost, or nothing outside could connect.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
