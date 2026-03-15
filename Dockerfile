FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg fontconfig && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN cp Speda-Bold.ttf /usr/share/fonts/ && fc-cache -fv

RUN pip install python-telegram-bot==20.7

CMD ["python", "main.py"]
