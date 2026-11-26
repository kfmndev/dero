FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 DATABASE=/data/dero.db USERS_FILE=/data/users.txt
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
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
