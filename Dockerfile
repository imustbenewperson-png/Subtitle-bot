FROM jrottenberg/ffmpeg:4.4-alpine

RUN apk add --no-cache python3 py3-pip

WORKDIR /app

COPY requirements.txt .
RUN pip3 install -r requirements.txt --break-system-packages

COPY main.py .

CMD ["python3", "main.py"]
