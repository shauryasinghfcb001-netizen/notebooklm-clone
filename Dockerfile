FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-indic && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
ENV STORAGE_DIR=/data LLM_PROVIDER=mock TTS_PROVIDER=edge PORT=8000
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
