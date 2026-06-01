#!/bin/bash
# GiguaT startup script for Render
set -e
echo "GiguaT starting..."
echo "Python: $(python3 --version 2>&1 || python --version 2>&1)"
echo "Working dir: $(pwd)"
echo "Files: $(ls -la DDTank_gui.py index.html 2>&1)"
echo "Picture dir: $(ls picture/ 2>&1 | head -5)"
exec python3 DDTank_gui.py
