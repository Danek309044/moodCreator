FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first so the layer is cached when only app code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Data directory is created here but overridden by the volume mount at runtime
RUN mkdir -p /app/data

EXPOSE 4444

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "4444"]