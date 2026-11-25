#!/usr/bin/env bash
# Limpeza automática dos filmes que todo mundo já viu (LIMPEZA_DIAS no .env).
#   ./limpeza.sh          mostra o que sairia hoje e o que sai em breve (não apaga nada)
#   ./limpeza.sh agora    roda a limpeza agora (normalmente roda sozinha todo dia às 4h)
set -euo pipefail
cd "$(dirname "$0")"
docker inspect -f '{{.State.Running}}' tarefas 2>/dev/null | grep -q true \
  || { echo "O serviço 'tarefas' não está rodando. Rode ./setup.sh" >&2; exit 1; }
exec docker exec tarefas python /scripts/tarefas.py limpeza "$@"
