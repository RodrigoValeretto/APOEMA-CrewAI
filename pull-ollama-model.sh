#!/bin/bash

# Script to pull the Ollama model after containers are running
echo "Pulling gemma3:4b model from Ollama..."
docker exec apoema-ollama ollama pull gemma3:4b

if [ $? -eq 0 ]; then
    echo "✓ Model pulled successfully!"
    echo "You can now start your analysis with model: 'ollama'"
else
    echo "✗ Failed to pull model"
    exit 1
fi