FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY routers/ routers/

EXPOSE 5051

CMD ["gunicorn", "main:app", "--bind", "0.0.0.0:5051", "--timeout", "120", "--workers", "2"]
