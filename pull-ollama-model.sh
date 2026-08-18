#!/bin/bash

# Script to pull the Ollama model (tool-calling capable) after containers are running
MODEL="${OLLAMA_MODEL:-phi4-mini:3.8b}"
echo "Pulling $MODEL model from Ollama..."
docker exec apoema-ollama ollama pull "$MODEL"

if [ $? -eq 0 ]; then
    echo "✓ Model pulled successfully!"
    echo "You can now start your analysis with model: 'ollama'"
else
    echo "✗ Failed to pull model"
    exit 1
fi
