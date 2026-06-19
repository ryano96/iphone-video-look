FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fontconfig \
        fonts-urw-base35 \
    && printf '%s\n' \
        '<?xml version="1.0"?>' \
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">' \
        '<fontconfig>' \
        '  <alias><family>Helvetica</family><prefer><family>Nimbus Sans</family></prefer></alias>' \
        '  <alias><family>Helvetica Neue</family><prefer><family>Nimbus Sans</family></prefer></alias>' \
        '</fontconfig>' \
        > /etc/fonts/local.conf \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py processor.py jobs.py snap_caption.py ./
COPY static/ ./static/

ENV PORT=10000
EXPOSE 10000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000}"]