#!/usr/bin/env bash
# Troca a senha do admin em todos os serviços (Deluge, Radarr, Sonarr, Prowlarr, Jellyfin/Seerr).
#   ./change-password.sh          -> pergunta a senha nova
#   ou coloque NEW_STACK_PASSWORD='...' no .env e rode o script
set -euo pipefail
cd "$(dirname "$0")"
die() { printf '\033[1;31mERRO:\033[0m %s\n' "$*" >&2; exit 1; }
get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]$//"; }

[[ -f .env ]] || die "rode ./setup.sh primeiro"
new=$(get_env NEW_STACK_PASSWORD || true)
if [[ -z $new ]]; then
  [[ -t 0 ]] || die "coloque NEW_STACK_PASSWORD='...' no .env ou rode num terminal"
  read -rsp "Senha nova (mín. 8 caracteres): " new; echo
  read -rsp "Repita: " new2; echo
  [[ $new == "$new2" ]] || die "as senhas não conferem"
fi
[[ ${#new} -ge 8 ]] || die "a senha precisa ter pelo menos 8 caracteres"
[[ $new != *"'"* ]] || die "a senha não pode conter aspas simples (')"

PROJ=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' gluetun 2>/dev/null || true)
docker compose ${PROJ:+-p "$PROJ"} run --rm -e NEW_STACK_PASSWORD="$new" setup python /scripts/configure.py passwd

# Grava a senha nova no .env e remove a temporária
KEY=STACK_PASSWORD VAL="'$new'" awk 'BEGIN{FS=OFS="="} $1=="NEW_STACK_PASSWORD"{next} $1==ENVIRON["KEY"]{print $1, ENVIRON["VAL"]; next} {print}' .env > .env.tmp
cat .env.tmp > .env && rm .env.tmp
echo ".env atualizado."
