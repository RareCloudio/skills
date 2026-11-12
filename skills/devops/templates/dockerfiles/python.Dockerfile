# Python web app served by gunicorn (WSGI: Django, Flask) with a requirements.txt.
# Copy to the project root as `Dockerfile`, next to the `.dockerignore` template.
#
# Placeholders (sample values in brackets, used when this file is checked):
#   <PYTHON_VERSION>  the Python minor line the project runs on, a tag the publisher keeps
#                     rebuilding (references/first-deploy.md, "Image tags") [3.14]
#   <PORT>            port gunicorn binds inside the container [8000]
#   <HEALTH_PATH>     path that answers 200 when the app can serve [/healthz]
#   <WSGI_APP>        module:callable gunicorn loads [app:app]
#
# ASGI (FastAPI, Starlette): add `-k uvicorn.workers.UvicornWorker` or run uvicorn instead.
# Poetry or uv: export a locked requirements file in the build stage, or install with the tool
# into the same /opt/venv path.

FROM python:<PYTHON_VERSION>-slim-trixie AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
# The virtualenv lives at the same path in both stages: its scripts carry that path in their
# first line, so copying it anywhere else breaks every entry point (gunicorn included).
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

FROM python:<PYTHON_VERSION>-slim-trixie
# Unbuffered output, or print() lines reach `docker logs` late or not at all before a crash.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
# Owned by root: the app can read its code but not change it.
COPY . .
USER app
EXPOSE <PORT>
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:<PORT><HEALTH_PATH>', timeout=3)"]
CMD ["gunicorn", "--bind", "0.0.0.0:<PORT>", "--workers", "2", "--access-logfile", "-", "<WSGI_APP>"]
