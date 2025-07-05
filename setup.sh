#!/bin/bash

echo "🏕️ Setting up Southern California Campsite Tracker..."

# Create virtual environment
echo "📦 Creating Python virtual environment..."
python -m venv venv_linux
source venv_linux/bin/activate

# Install dependencies
echo "📋 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Copy environment file
echo "⚙️ Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env file - please edit with your credentials"
else
    echo "✅ .env file already exists"
fi

# Create templates directory
echo "📁 Creating dashboard templates..."
mkdir -p src/dashboard/templates
python -c "
import asyncio
from src.dashboard.calendar_view import create_templates_directory
asyncio.run(create_templates_directory())
"

# Test setup
echo "🧪 Testing configuration..."
python -m src.main setup

echo ""
echo "🎉 Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your MCP credentials"
echo "2. Run locally: python -m src.main dashboard"
echo "3. Access dashboard: http://localhost:8000"
echo ""
echo "For online deployment:"
echo "1. Push to GitHub"
echo "2. Configure repository secrets"
echo "3. GitHub Actions will auto-deploy to DigitalOcean"
echo ""
echo "Happy camping! 🏕️"