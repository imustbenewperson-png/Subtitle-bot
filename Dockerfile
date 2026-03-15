FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg wget && \
    wget -O /usr/share/fonts/kurdish.ttf https://github.com/alirezastack/Unikurd/raw/master/Unikurd-Web.ttf && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install python-telegram-bot==20.7

CMD ["python", "main.py"]
