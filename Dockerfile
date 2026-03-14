FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-noto \
    fonts-noto-core \
    fonts-noto-extra \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .

CMD ["python", "main.py"]
