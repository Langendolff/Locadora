#!/usr/bin/env bash
# Pessoas da casa e a preferência de áudio e legenda de cada uma.
#   ./pessoas.sh                                   lista as pessoas e as preferências
#   ./pessoas.sh nova Ana                          cadastra (pergunta senha, áudio e legenda)
#   ./pessoas.sh nova Ana original en              já com áudio original e legenda em inglês
#   ./pessoas.sh preferencia Ana dublado pt-br     muda a preferência
# Áudio: dublado (PT-BR quando existir) | original.  Legenda: pt-br | en | nenhuma.
# Vale para os pedidos no Seerr, a reprodução no Jellyfin e as legendas que o Bazarr baixa.
set -euo pipefail
cd "$(dirname "$0")"
die() { printf '\033[1;31mERRO:\033[0m %s\n' "$*" >&2; exit 1; }
[[ -f .env ]] || die "rode ./setup.sh primeiro"
docker inspect seerr >/dev/null 2>&1 || die "a Locadora não está rodando. Rode ./setup.sh"

senha=""
if [[ ${1:-} == nova ]]; then
  [[ -n ${2:-} ]] || die "uso: ./pessoas.sh nova NOME [dublado|original] [pt-br|en|nenhuma]"
  [[ -t 0 ]] || die "rode num terminal (a senha é pedida)"
  while :; do
    read -rsp "Senha para $2 (mín. 4 caracteres): " senha; echo
    read -rsp "Repita: " s2; echo
    [[ $senha == "$s2" && ${#senha} -ge 4 ]] && break
    echo "Senhas diferentes ou curtas demais, tente de novo."
  done
fi

# Usa o mesmo projeto compose dos containers que estão rodando (a pasta pode ter sido renomeada)
proj=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' seerr 2>/dev/null || true)
tty=-T; [[ -t 0 ]] && tty=""
exec docker compose ${proj:+-p "$proj"} run --rm --no-deps $tty -e PESSOA_SENHA="$senha" setup \
  python /scripts/configure.py pessoas "$@" 2> >(grep -vE '^ ?(Container|Network) ' >&2)
