@echo off
REM Double-click this file to start the Nodal Analysis app.
REM It opens the app in your browser. Close this black window (or press Ctrl+C) to stop the app.

REM Go to the folder this file is in, so it works wherever you put the folder
cd /d "%~dp0"
title Nodal Analysis app

echo Starting the Nodal Analysis app...
echo (the browser opens by itself; keep this window open while you use the app)
echo.

python -m streamlit run app.py

REM If we get here, the app stopped. Keep the window open so any error message can be read.
echo.
echo The app has stopped. If this was not on purpose, read the message above.
pause
