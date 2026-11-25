#!/bin/bash
# Locadora: clique duas vezes no Finder para conferir se está tudo funcionando (não muda nada).
cd "$(dirname "$0")" || exit 1
chmod +x diagnostico.sh 2>/dev/null
./diagnostico.sh
status=$?
echo
read -n 1 -s -r -p "Pressione qualquer tecla para fechar."
exit $status
