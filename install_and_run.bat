@echo off
title EmbroideryStudio - Installer
echo.
echo ============================================================
echo   EmbroideryStudio - Installing dependencies
echo ============================================================
echo.
echo Installing required Python packages...
echo.
pip install pyembroidery Pillow numpy opencv-python
echo.
echo ============================================================
echo   All done! Launching EmbroideryStudio...
echo ============================================================
echo.
python embroidery_studio.py
pause
