FROM python:3.11-slim

WORKDIR /app

# 仅装生产依赖(slim + edge-tts 运行时需要 apt ffmpeg / libespeak 暂时不需要,TTS 走 edge-tts 在线)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码
COPY app.py wsgi.py ./
COPY extensions ./extensions
COPY web ./web

# data / certs / logs 用 volume 挂载,不写进镜像
RUN mkdir -p /app/data /app/certs /app/logs

ENV PYTHONUNBUFFERED=1
EXPOSE 5002

# 默认 2 worker × 4 thread = 8 并发(SQLite 写并发友好);通过环境变量可覆盖
ENV GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=4 \
    GUNICORN_TIMEOUT=60

CMD ["sh", "-c", "gunicorn -w ${GUNICORN_WORKERS} -k gthread --threads ${GUNICORN_THREADS} --timeout ${GUNICORN_TIMEOUT} -b 0.0.0.0:5002 --access-logfile - --error-logfile - wsgi:app"]