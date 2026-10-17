FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ORCH_DB_PATH=/data/orchestrator.db
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN useradd --system --uid 10002 orch && mkdir /data && chown orch /data
USER orch
VOLUME /data
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8001/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
