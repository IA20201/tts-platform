@echo off
cd /d "%~dp0"
echo Starting MiMo TTS Server on http://localhost:18900
echo API docs: http://localhost:18900/docs
uv run server.py
pause
