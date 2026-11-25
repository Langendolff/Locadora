@echo off
rem Locadora: clique duas vezes para conferir se está tudo funcionando (não muda nada).
title Locadora - diagnostico
wsl.exe -e bash -lc "cd ~/Locadora 2>/dev/null || { echo 'A Locadora nao esta instalada no WSL (~/Locadora). Rode o Instalar.bat.'; exit 1; }; ./diagnostico.sh"
echo.
pause
