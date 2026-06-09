FROM python:3.13-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivos de dependências
COPY pyproject.toml uv.lock* ./

# Instalar pip-tools para gerenciar dependências
RUN pip install --no-cache-dir pip-tools

# Instalar Python packages
RUN pip install --no-cache-dir \
    psycopg[binary] \
    dramatiq[rabbitmq] \
    -e .

COPY . .

CMD ["python", "main.py"]