FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 DATABASE=/data/dero.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dero ./dero
RUN useradd -r -u 10001 app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "dero:create_app()"]
