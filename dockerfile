FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY testscraper.py .
COPY crawler_ui.py .

ENV USE_OLLAMA=0
ENV OUTPUT_DIR=/app/crawler_runs
ENV PYTHONUNBUFFERED=1

CMD ["python", "testscraper.py"]