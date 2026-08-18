#!/bin/bash

# Function to pull a model asynchronously
pull_model_in_background() {
    local model=$1
    sleep 5
    echo "Pulling $model model in background..."
    if /bin/ollama pull "$model"; then
        echo "✓ Model $model pulled successfully!"
    else
        echo "✗ Failed to pull $model - will try again on next startup"
    fi
}

# Pull LLM model (tool-calling capable; override via OLLAMA_MODEL env)
pull_model_in_background "${OLLAMA_MODEL:-phi4-mini:3.8b}" &

# Pull vision model for chart analysis (override via OLLAMA_VISION_MODEL env)
pull_model_in_background "${OLLAMA_VISION_MODEL:-qwen2.5vl:3b}" &

# Pull embedding model for RAG
pull_model_in_background "nomic-embed-text" &

# Start and keep Ollama running in foreground
echo "Starting Ollama server..."
exec /bin/ollama serve
