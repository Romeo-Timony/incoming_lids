FROM python:3.12-slim

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

ENV OPERATOR_CHAT_FILE=/app/data/.operator_chat_id

CMD ["python", "main.py"]
