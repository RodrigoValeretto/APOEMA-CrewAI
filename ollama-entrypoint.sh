#!/bin/bash

# Function to pull model asynchronously
pull_model_in_background() {
    sleep 5
    echo "Pulling gemma3:4b model in background..."
    if /bin/ollama pull gemma3:4b; then
        echo "✓ Model pulled successfully!"
    else
        echo "✗ Failed to pull model - will try again on next startup"
    fi
}

# Start model pull in background
pull_model_in_background &

# Start and keep Ollama running in foreground
echo "Starting Ollama server..."
exec /bin/ollama serve
