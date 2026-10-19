FROM docker.1ms.run/python:3.12-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        build-essential \
        gcc \
        libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/symbolicana

COPY requirements.txt pyproject.toml setup.py ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir --force-reinstall z3-solver==4.12.2.0 \
    && python -c "import angr, claripy, z3; assert z3.get_version_string() == '4.12.2'; print('angr', angr.__version__, 'claripy', claripy.__version__, 'z3', z3.get_version_string())"

COPY . .

ENV PYTHONPATH=/workspace/symbolicana/src
ENV PYTHONUNBUFFERED=1

CMD ["python", "run_experiment.py", "--help"]
