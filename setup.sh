#!/bin/bash

# Configuration
PLUGIN_NAME="gimp_bridge"
GIMP_CONFIG_DIR="$HOME/Library/Application Support/GIMP/3.0"
PLUGIN_DIR="$GIMP_CONFIG_DIR/plug-ins/$PLUGIN_NAME"
SOURCE_PLUGIN="gimp_bridge.py"

echo "Setup GIMP MCP Bridge..."

# 1. Install Python Dependencies for the external server
echo "Installing dependencies for MCP server..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Warning: pip install failed. Ensure you have python installed."
fi

# 2. Setup GIMP Plugin
echo "Setting up GIMP Plugin..."

# Check if GIMP config dir exists, if not create it
if [ ! -d "$GIMP_CONFIG_DIR" ]; then
    echo "Creating GIMP config directory at $GIMP_CONFIG_DIR"
    mkdir -p "$GIMP_CONFIG_DIR"
fi

# Create specific plugin directory (GIMP 3.0 requirement: plugin in its own dir)
if [ ! -d "$PLUGIN_DIR" ]; then
    echo "Creating plugin directory at $PLUGIN_DIR"
    mkdir -p "$PLUGIN_DIR"
fi

# Copy the bridge script
cp "$SOURCE_PLUGIN" "$PLUGIN_DIR/$PLUGIN_NAME.py"

# Make it executable
chmod +x "$PLUGIN_DIR/$PLUGIN_NAME.py"

echo "Plugin installed to: $PLUGIN_DIR/$PLUGIN_NAME.py"
echo ""
echo "DONE!"
echo "---------------------------------------------------"
echo "To start:"
echo "1. Restart GIMP if it is running."
echo "2. In GIMP, go to Filters > Development > Start MCP Bridge Server."
echo "   (Wait for the 'MCP Bridge Server started' message)"
echo "3. In a new terminal, run the MCP server:"
echo "   python3 server.py"
