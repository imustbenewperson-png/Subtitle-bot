FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg wget fontconfig && \
    wget -O /usr/share/fonts/kurdish.ttf "https://github.com/silnrsi/font-scheherazade/releases/download/v3.300/ScheherazadeNew-Regular.ttf" && \
    fc-cache -fv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install python-telegram-bot==20.7

CMD ["python", "main.py"]
