FROM python:3.13-slim
# uv installs exactly what uv.lock says; the digest pins the image, Dependabot updates both
COPY --from=ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 DATABASE=/data/dero.db USERS_FILE=/data/users.txt UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
# Shown in the page footer (no .git folder in the image): --build-arg DERO_COMMIT=$(git rev-parse HEAD)
ARG DERO_COMMIT=
ENV DERO_COMMIT=$DERO_COMMIT
COPY dero ./dero
RUN useradd -r -u 10001 app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
# --preload: create the app (and the database) once in the master, not racing in every worker.
# -k gthread --threads: every open "Live visits" stream (server-sent events) holds one thread, so workers need threads.
# --no-control-socket: gunicorn 27 otherwise writes a socket to ~/.gunicorn, and the app user has no home dir.
CMD ["gunicorn", "--preload", "--no-control-socket", "-k", "gthread", "-w", "2", "--threads", "16", "-b", "0.0.0.0:8000", "dero:create_app()"]
