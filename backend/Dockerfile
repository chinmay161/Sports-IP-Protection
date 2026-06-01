FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libpq-dev \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /tmp/sports-ip

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
