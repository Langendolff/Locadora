@echo off
rem Locadora: clique duas vezes para instalar ou atualizar.
title Locadora - instalador
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" %*
echo.
pause
