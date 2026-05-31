FROM node:24-bookworm-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.11

ARG INSTALL_OLLAMA=1
LABEL app.install_ollama="${INSTALL_OLLAMA}"

ENV PYTHONUNBUFFERED=1
ENV OLLAMA_HOST=0.0.0.0:11434
ENV OLLAMA_HOME=/home/user/.ollama

RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    zstd \
    && rm -rf /var/lib/apt/lists/*

RUN if [ "$INSTALL_OLLAMA" = "1" ]; then \
      curl -fsSL https://ollama.com/install.sh | sh; \
    else \
      echo "Skipping Ollama install for hosted LLM provider image"; \
    fi

RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY scripts/docker-entrypoint.sh /usr/local/bin/agentic-document-entrypoint
RUN chmod +x /usr/local/bin/agentic-document-entrypoint

COPY . .
COPY --from=frontend-build /frontend/dist /app/frontend/dist
RUN mkdir -p /home/user/.ollama && chown -R user:user /app /home/user/.ollama

USER user
ENV PATH="/home/user/.local/bin:$PATH"
EXPOSE 7860
CMD ["agentic-document-entrypoint"]
