#!/bin/bash
# Setup script for creating virtual environment

set -e

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install project in editable mode
echo "Installing project..."
pip install -e .

# Install dev dependencies (optional)
if [ "$1" == "--dev" ]; then
    echo "Installing dev dependencies..."
    pip install -e ".[dev]"
fi

echo ""
echo "Virtual environment setup complete!"
echo "To activate it, run: source venv/bin/activate"
echo "To deactivate it, run: deactivate"


