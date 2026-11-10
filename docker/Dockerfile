# Inference images copy adapters and method inputs only. Benchmark labels stay in the evaluator.
FROM python:3.10.20-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/cleanbench OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
WORKDIR /opt/cleanbench
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential util-linux && rm -rf /var/lib/apt/lists/*
COPY docker/requirements/ /opt/requirements/
COPY docker/setup_upstream.py /opt/setup_upstream.py
ENTRYPOINT ["python", "-m", "baselines.runner"]

FROM python:3.12.12-slim-bookworm AS replay
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/cleanbench
COPY scripts/reproduce_table3.py scripts/reproduce_table3.py
COPY src/reproducibility/ src/reproducibility/
COPY reproducibility/table3/ reproducibility/table3/
ENTRYPOINT ["python", "scripts/reproduce_table3.py"]
CMD ["--output", "/results/table3"]

FROM base AS spelling
RUN pip install --no-cache-dir -r /opt/requirements/spelling.txt
COPY baselines/ baselines/

FROM base AS api
RUN pip install --no-cache-dir -r /opt/requirements/api.txt
COPY baselines/ baselines/

FROM eclipse-temurin:8-jdk-jammy AS java8
FROM base AS classical
COPY --from=java8 /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends ant && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r /opt/requirements/classical.txt
RUN python /opt/setup_upstream.py adr llunatic
COPY baselines/native/external/nadeef/NadeefBatch.java baselines/native/external/nadeef/NadeefBatch.java
COPY baselines/native/external/llunatic/NativeBridge.java baselines/native/external/llunatic/NativeBridge.java
RUN mkdir -p baselines/native/external/nadeef/build/adapter baselines/native/external/llunatic/build && \
    ln -s /opt/java/openjdk baselines/native/external/nadeef/mamba_env && \
    ant -f baselines/native/external/adr/adr_repo/NADEEF-master/build.xml -Dbuild.root=/opt/cleanbench/baselines/native/external/nadeef/build jar && \
    javac -encoding UTF-8 -cp 'baselines/native/external/nadeef/build/bin/*' -d baselines/native/external/nadeef/build/adapter baselines/native/external/nadeef/NadeefBatch.java && \
    javac -cp 'baselines/native/external/llunatic/upstream/lib/*' -d baselines/native/external/llunatic/build baselines/native/external/llunatic/NativeBridge.java
COPY baselines/ baselines/

FROM base AS uniclean
COPY --from=java8 /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH SPARK_LOCAL_IP=127.0.0.1 PYSPARK_PYTHON=/usr/local/bin/python
RUN pip install --no-cache-dir -r /opt/requirements/uniclean.txt
RUN python /opt/setup_upstream.py uniclean
COPY baselines/ baselines/

FROM base AS katara
RUN pip install --no-cache-dir gdown==5.2.0 py7zr==1.0.0
RUN python /opt/setup_upstream.py katara
RUN gdown 1cmpjsUATPIJFNz32VJyl_5yN8Nx4og2h -O /tmp/knowledge-base.7z && \
    echo '5e299f28980f5a2e3e2f9c712d21aae19f24f6e59b8b3181f094efc8f0f0c431  /tmp/knowledge-base.7z' | sha256sum -c - && \
    python -c "import py7zr; py7zr.SevenZipFile('/tmp/knowledge-base.7z').extractall('baselines/native/external/katara/knowledge-base')" && rm /tmp/knowledge-base.7z
COPY baselines/ baselines/

FROM python:3.12.12-slim-bookworm AS neuspell
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/cleanbench OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
WORKDIR /opt/cleanbench
COPY docker/requirements/neuspell.txt /opt/requirements.txt
RUN pip install --no-cache-dir torch==2.12.1 --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r /opt/requirements.txt
COPY docker/setup_neuspell.py /opt/setup_neuspell.py
RUN python /opt/setup_neuspell.py
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
COPY baselines/ baselines/
ENTRYPOINT ["python", "-m", "baselines.runner"]

FROM base AS cleanagent
RUN pip install --no-cache-dir -r /opt/requirements/cleanagent.txt
RUN python /opt/setup_upstream.py cleanagent
COPY baselines/ baselines/

FROM python:3.12.12-slim-bookworm AS cocoon
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/cleanbench OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /opt/cleanbench
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential && rm -rf /var/lib/apt/lists/*
COPY docker/requirements/ /opt/requirements/
COPY docker/setup_upstream.py /opt/setup_upstream.py
ENTRYPOINT ["python", "-m", "baselines.runner"]
RUN apt-get update && apt-get install -y --no-install-recommends unixodbc-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -c /opt/requirements/cocoon-constraints.txt -r /opt/requirements/cocoon.txt
RUN python /opt/setup_upstream.py cocoon
COPY baselines/ baselines/

FROM node:22-bookworm-slim AS node22
FROM base AS coding
COPY --from=node22 /usr/local/ /usr/local/
RUN pip install --no-cache-dir -r /opt/requirements/coding.txt
RUN npm install -g @openai/codex@0.158.0 @github/copilot@1.0.88
COPY baselines/ baselines/
