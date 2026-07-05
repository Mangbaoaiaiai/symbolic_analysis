ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/symbolic_analysis/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        binutils \
        gcc \
        g++ \
        git \
        make \
        libffi-dev \
        libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/symbolic_analysis

COPY requirements.txt pyproject.toml setup.py README.md ./
COPY src ./src
COPY scripts ./scripts
COPY benchmarks ./benchmarks
COPY experiments ./experiments
COPY build_ardiff_path_benchmarks.py run_evaluation.py translate_ardiff_java_to_typed_c.py ./

RUN if [ -n "$PIP_INDEX_URL" ]; then \
        python -m pip install --upgrade pip -i "$PIP_INDEX_URL" && \
        pip install -r requirements.txt -i "$PIP_INDEX_URL"; \
    else \
        python -m pip install --upgrade pip && \
        pip install -r requirements.txt; \
    fi \
    && pip install -e .

CMD ["symbolicana", "check-deps"]
