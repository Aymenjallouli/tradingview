@echo off
REM ============================================================
REM   ONE-CLICK START — runs all 5 trading bots + the dashboard
REM
REM   Before running, make sure:
REM     1. MetaTrader 5 is OPEN and logged into your Pepperstone demo
REM     2. The "Algo Trading" button in MT5 is GREEN
REM
REM   Then just double-click this file.
REM   The dashboard opens automatically at http://localhost:8800
REM ============================================================

cd /d "%~dp0"

echo Starting the 5 trading bots...
start "MT5 Bots" cmd /k python -u run_all.py

echo Waiting for bots to connect...
timeout /t 20 /nobreak >nul

echo Starting the dashboard...
start "MT5 Hub" cmd /k python -u mt5_hub.py

echo Waiting for dashboard...
timeout /t 6 /nobreak >nul

echo Opening the dashboard in your browser...
start http://localhost:8800

echo.
echo ============================================================
echo   RUNNING. Dashboard: http://localhost:8800
echo   Two windows opened (bots + hub). Close them to stop.
echo ============================================================
pause
