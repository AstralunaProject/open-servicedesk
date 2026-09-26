FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHAMADOS_DATA_DIR=/data \
    PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY run.py wsgi.py ./

RUN useradd --system --uid 1000 --home /app chamados \
    && mkdir -p /data \
    && chown chamados /data
USER chamados

VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/saude' % os.environ.get('PORT', '8080'))"

CMD ["python", "run.py"]
