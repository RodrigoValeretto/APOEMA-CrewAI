FROM python:3.13-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivos de dependências e README (necessário para o build)
COPY pyproject.toml uv.lock* README.md ./

# Instalar pip-tools para gerenciar dependências
RUN pip install --no-cache-dir pip-tools

# torch CPU-only primeiro: o wheel padrão do PyPI no Linux puxa nvidia-* CUDA
# (vários GB, estoura o disco do build). Instalado antes, o pip do passo abaixo
# considera torch/torchvision já satisfeitos e o docling não baixa CUDA.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.6" \
    "torchvision>=0.21"

# Instalar Python packages (inclui o extra 'converter': docling p/ PDF->JSON)
RUN pip install --no-cache-dir \
    psycopg[binary] \
    dramatiq[rabbitmq] \
    -e ".[converter]"

# Libs de sistema exigidas pelo docling/opencv no python:slim (libGL, glib, xcb)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    libxcb-shm0 \
    libxcb-xfixes0 \
    libxcb-render0 \
    libxcb-shape0 \
    libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Default to running the API server
# Override with command in docker-compose for different services (worker, etc.)
CMD ["python", "run_api.py"]