FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        git \
        curl \
        unzip \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN ARCH=$(uname -m) \
    && curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-${ARCH}.zip" -o /tmp/awscli.zip \
    && unzip -q /tmp/awscli.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscli.zip /tmp/aws

WORKDIR /app

COPY docker/requirements-cloud.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir 'numpy<2' 'cython>=0.29' \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && apt-get purge -y build-essential git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /root/.cache

COPY examples /app/examples
COPY outputs/nse_baseline_750_long /app/model_seed/nse_baseline_750_long
COPY outputs/pit_universe.parquet /app/model_seed/pit_universe.parquet
COPY docker/run_daily_cloud.sh /app/run_daily_cloud.sh
RUN chmod +x /app/run_daily_cloud.sh /app/examples/run_daily.sh

ENV MODEL_DIR=outputs/nse_baseline_750_long \
    PYTHONPATH=/app

ENTRYPOINT ["/app/run_daily_cloud.sh"]
