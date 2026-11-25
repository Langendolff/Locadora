#!/bin/bash
# Locadora: clique duas vezes no Finder para instalar ou atualizar (macOS + Docker Desktop).
# Na primeira vez, o macOS pode bloquear: clique com o botão direito > Abrir > Abrir.
cd "$(dirname "$0")" || exit 1
chmod +x setup.sh change-password.sh diagnostico.sh scripts/*.sh 2>/dev/null

printf '\n  \033[1;31mLocadora\033[0m\n  Seu serviço de streaming, no seu servidor.\n\n'

if ! docker info >/dev/null 2>&1; then
  echo "O Docker Desktop não está rodando. Abra o Docker Desktop, espere ele iniciar e tente de novo."
  read -n 1 -s -r -p "Pressione qualquer tecla para fechar."; exit 1
fi

if [ -f vpn/wg0.conf ]; then
  ./setup.sh
else
  conf=$(osascript -e 'POSIX path of (choose file with prompt "Locadora: escolha o arquivo WireGuard (.conf) da sua VPN" default location (path to downloads folder))' 2>/dev/null)
  if [ -z "$conf" ]; then
    echo "Nenhum arquivo escolhido."
    read -n 1 -s -r -p "Pressione qualquer tecla para fechar."; exit 1
  fi
  ./setup.sh "$conf"
fi
status=$?
echo
[ $status -eq 0 ] && open "http://localhost:$(grep -E '^SEERR_PORT=' .env | cut -d= -f2- | tr -d "'\"")" 2>/dev/null
read -n 1 -s -r -p "Pressione qualquer tecla para fechar."
exit $status
