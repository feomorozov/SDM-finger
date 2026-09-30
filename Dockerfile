FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    RUNTIME_DIR=/tmp/motion-tracker

WORKDIR /app

COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY app.py ./
COPY illinoisBioE.png ./
COPY web ./web

EXPOSE 8000

CMD ["python", "app.py"]
