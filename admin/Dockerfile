# The admin panel image.    docker build -t antifraud/admin admin/

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

USER app
EXPOSE 5000

# gunicorn, not `flask run` - Flask's own server is for development only.
# Two worker processes: one slow API call does not hold up every other page. That is
# also why SECRET_KEY must be set - each worker signs and checks the session cookie,
# and with a random key per worker, every other request would look logged out.
# "app:create_app()" - the module, and the factory gunicorn calls to get the app.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "app:create_app()"]
