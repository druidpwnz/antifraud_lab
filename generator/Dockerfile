# The generator image. Three jobs, one image - compose picks the job by command:
#     python /app/db/migrate.py     migrate: apply the migrations the database lacks
#     python backfill.py            seed: 14 days of history, once (skips if done)
#     python live.py                generator: carry on from sim_state (the default)
#
# Built from the REPO ROOT, not from generator/, because it also carries db/:
#     docker build -f generator/Dockerfile -t antifraud/generator .
# What it may copy is decided by the .dockerignore in the repo root.

FROM python:3.14-slim

# PYTHONUNBUFFERED: print() reaches `docker compose logs` at once, not in 4 KB lumps.
# PYTHONDONTWRITEBYTECODE: no .pyc files written into the image at run time.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A fixed, unprivileged user: nothing in the container runs as root.
RUN useradd --system --uid 10001 --no-create-home app

# Requirements before code: this layer is rebuilt only when requirements.txt
# changes, not on every code edit - so most rebuilds take seconds.
COPY generator/requirements.txt /app/generator/requirements.txt
RUN pip install -r /app/generator/requirements.txt

COPY db/migrate.py /app/db/migrate.py
COPY db/migrations/ /app/db/migrations/
COPY generator/*.py /app/generator/

ARG BUILD_VERSION=local
ENV BUILD_VERSION=${BUILD_VERSION}
LABEL org.opencontainers.image.revision=${BUILD_VERSION} \
    org.opencontainers.image.source="https://github.com/druidpwnz/antifraud_lab"

# The generator's modules import each other by plain name (import config), so it
# runs from its own folder - as locally.
WORKDIR /app/generator
USER app

# Exec form: python is PID 1 and receives SIGTERM itself - live.py then finishes the
# hour and commits. A shell form (CMD python live.py) would put /bin/sh in between.
CMD ["python", "live.py"]
