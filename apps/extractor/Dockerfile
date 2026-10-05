# syntax=docker/dockerfile:1
# The extractor as a server on port 8787. Build it from this folder. The data stays outside the
# image: mount the repo's data/ at /repo/data and .env.local at /repo/.env.local.

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# RapidOCR brings the desktop build of OpenCV, which loads these libraries even without a screen.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH=/app/.venv/bin:$PATH
ENV ROV_DATA_ROOT=/repo
# The container runs as the owner of the data folder, who has no home in the image.
ENV HOME=/tmp
EXPOSE 8787
CMD ["rov-extract", "serve", "--lan"]
