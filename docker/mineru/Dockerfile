# The MinerU service in production: Linux with an NVIDIA GPU (>= 8 GB VRAM, >= 16 GB RAM) and the NVIDIA
# Container Toolkit. MinerU is pinned and its models are in the image, so a file is read the same way wherever
# the image runs. Built and started with the compose profile: `docker compose --profile mineru up -d mineru`.
# On a Mac, where Docker has no GPU, run-dev.sh runs MinerU natively instead (README: Running MinerU).
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.27 /uv /usr/local/bin/uv

# The engines the models are fetched for and served with: vLLM for the VLM, torch for the small models.
ENV MINERU_HOME=/opt/mineru \
    MINERU_MODEL_SOURCE=huggingface \
    MINERU_MODEL_SMALL_BACKEND=torch \
    MINERU_MODEL_VLM_ENGINE=vllm \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# vLLM's Triton kernels compile a small C launcher on their first run: the slim image has no compiler.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
RUN uv pip install --system --no-cache "mineru[full]==4.0.12"

# The service runs as mineru, which owns MINERU_HOME: MinerU writes its config and model locks there.
RUN useradd --create-home --uid 10001 mineru && mkdir -p "$MINERU_HOME" /uploads && chown mineru "$MINERU_HOME" /uploads
USER mineru

# opendatalab/MinerU-4_models_torch and opendatalab/MinerU2.5-Pro-2605-1.2B, both Apache 2.0.
RUN mineru-kit models download --tier standard && mineru-kit models verify --tier standard

EXPOSE 8010

# MINERU_API_KEY, when set, is the key every request must carry (METAMORPH_MINERU_API_KEY on the connectors).
# No image analysis: it writes descriptions of pictures as if they were the page's text (as docker/mineru/run-dev.sh).
ENTRYPOINT ["/bin/sh", "-c", "exec mineru-kit api-server --host 0.0.0.0 --port 8010 --tier standard --preload-models --disable-image-analysis --upload-dir /uploads --concurrency \"${MINERU_CONCURRENCY:-1}\" ${MINERU_API_KEY:+--api-key \"$MINERU_API_KEY\"}"]
