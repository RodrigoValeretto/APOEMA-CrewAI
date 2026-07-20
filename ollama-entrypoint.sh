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

# Pull LLM model
pull_model_in_background "gemma3:4b" &

# Pull embedding model for RAG
pull_model_in_background "nomic-embed-text" &

# Start and keep Ollama running in foreground
echo "Starting Ollama server..."
exec /bin/ollama serve
