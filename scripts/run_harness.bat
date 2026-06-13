@echo off
title Brickomancer Harness
cd /d C:\Users\abero\dev\brickomancer
set PATH=%PATH%;C:\Tools\LPub3D
echo.
echo  Brickomancer Evaluation Harness
echo  ================================
echo  Project: %CD%
echo  Server:  http://localhost:8005
echo  Output:  tests\harness\runs\
echo.
uv run python tests/harness/run_harness.py %*
echo.
echo  Done. Press any key to close.
pause >nul
