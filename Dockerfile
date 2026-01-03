FROM python:3.10-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "webhook_server:app", "--host", "0.0.0.0", "--port", "8082"]
