FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
RUN useradd --system --uid 10003 portal
USER portal
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/health')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
