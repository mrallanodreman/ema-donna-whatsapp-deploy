FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system ema && useradd --system --gid ema --create-home ema

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN mkdir -p /app/data && chown -R ema:ema /app
USER ema

ENV EMA_HOST=0.0.0.0 \
    EMA_PORT=8099 \
    EMA_DATA_DIR=/app/data

EXPOSE 8099
VOLUME ["/app/data"]

CMD ["ema", "watch"]
