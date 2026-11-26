#!/usr/bin/env bash
# Confere se a Locadora está funcionando e diz, em português, o que fazer quando não está.
#   ./diagnostico.sh
# Só lê: não muda nada. Compatível com o bash 3.2 do macOS.
set -uo pipefail
cd "$(dirname "$0")"

ERR=0; WARN=0
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
aviso() { printf '  \033[33m!\033[0m %s\n' "$1"; [[ -n ${2:-} ]] && printf '      → %s\n' "$2"; WARN=$((WARN+1)); }
erro()  { printf '  \033[31m✗\033[0m %s\n' "$1"; [[ -n ${2:-} ]] && printf '      → %s\n' "$2"; ERR=$((ERR+1)); }
secao() { printf '\033[1m%s\033[0m\n' "$*"; }
get_env() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]$//"; }
fim() {
  echo
  if [[ $ERR -gt 0 ]]; then
    printf '\033[1;31m%s problema(s)\033[0m e %s aviso(s). Comece pelo primeiro ✗ da lista.\n' "$ERR" "$WARN"
    printf 'Mais ajuda: docs/solucao-de-problemas.md\n'
    exit 1
  elif [[ $WARN -gt 0 ]]; then
    printf '\033[1;33mFuncionando, com %s aviso(s).\033[0m\n' "$WARN"
  else
    printf '\033[1;32mTudo certo.\033[0m\n'
  fi
  exit 0
}

# ---------- Instalação ----------
secao "Instalação"
if ! command -v docker >/dev/null 2>&1; then
  erro "Docker não encontrado" "instale o Docker (Linux) ou o Docker Desktop (macOS/Windows)"; fim
fi
if ! docker info >/dev/null 2>&1; then
  erro "o Docker não está rodando" "inicie o Docker (ou abra o Docker Desktop) e rode de novo"; fim
fi
ok "Docker rodando"
if [[ ! -f .env ]]; then erro "falta o arquivo .env" "rode ./setup.sh"; fim; fi
[[ -f vpn/wg0.conf ]] && ok "configuração da VPN presente" \
  || erro "falta vpn/wg0.conf" "rode ./setup.sh caminho/da/sua-vpn.conf"

# ---------- Containers ----------
secao "Serviços"
SERVICOS="gluetun deluge prowlarr flaresolverr radarr sonarr bazarr jellyfin seerr tarefas painel"
[[ -n $(get_env TS_AUTHKEY) ]] && SERVICOS="$SERVICOS tailscale"
[[ $(get_env COMPOSE_PROFILES) == *painel* ]] && SERVICOS="$SERVICOS operador"
parados=""
for s in $SERVICOS; do
  st=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$s" 2>/dev/null) \
    || { erro "$s não existe" "rode ./setup.sh"; parados="$parados $s"; continue; }
  case $st in
    "running unhealthy") erro "$s está rodando, mas com falha" "veja: docker compose logs --tail 50 $s" ;;
    running*) : ;;
    *) erro "$s está parado ($st)" "rode ./setup.sh ou veja: docker compose logs --tail 50 $s"; parados="$parados $s" ;;
  esac
  reinicios=$(docker inspect -f '{{.RestartCount}}' "$s" 2>/dev/null || echo 0)
  [[ ${reinicios:-0} -gt 5 ]] && aviso "$s reiniciou $reinicios vezes" "veja: docker compose logs --tail 50 $s"
done
[[ -z $parados ]] && ok "todos os $(echo $SERVICOS | wc -w | tr -d ' ') serviços rodando"

# Containers criados a partir de outra pasta (ex.: a pasta foi renomeada ou movida)
PROJ=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' gluetun 2>/dev/null || true)
DIR=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' gluetun 2>/dev/null || true)
if [[ -n $DIR && $DIR != "$PWD" ]]; then
  aviso "os serviços foram iniciados de outra pasta ($DIR)" \
        "o ./setup.sh daqui vai dar 'container name already in use'. Para reiniciar a partir desta pasta: docker compose -p $PROJ down && ./setup.sh"
fi
CP=""; [[ -n $PROJ ]] && CP="-p $PROJ"

# ---------- VPN ----------
secao "VPN"
if [[ " $parados " == *" gluetun "* || " $parados " == *" deluge "* ]]; then
  erro "sem VPN: gluetun ou deluge parado" "veja: docker compose logs --tail 50 gluetun"
else
  vpn_ip=$(docker exec deluge curl -fsS --max-time 15 https://ipinfo.io/ip 2>/dev/null || true)
  casa_ip=""
  command -v curl >/dev/null 2>&1 && casa_ip=$(curl -fsS --max-time 10 https://ipinfo.io/ip 2>/dev/null || true)
  if [[ -z $vpn_ip ]]; then
    erro "o Deluge está sem internet: a VPN não está conectada" \
         "veja: docker compose logs --tail 30 gluetun. Servidor gratuito da Proton não permite P2P; o .conf pode ter expirado"
  elif [[ -n $casa_ip && $vpn_ip == "$casa_ip" ]]; then
    erro "o Deluge está saindo com o IP da sua casa ($vpn_ip), não pela VPN" \
         "pare os downloads agora: docker compose stop deluge. Depois rode ./setup.sh"
  else
    ok "downloads saem pela VPN (IP $vpn_ip)"
  fi
fi
FWD=""
if [[ $(get_env VPN_PORT_FORWARDING) == on ]]; then
  FWD=$(tr -dc '0-9' < config/gluetun/forwarded_port 2>/dev/null || true)
  if [[ -n $FWD ]]; then ok "porta $FWD aberta pela VPN (mais fontes, downloads mais rápidos)"
  else aviso "a VPN não abriu porta (port forwarding)" \
             "os downloads funcionam, mas mais devagar. Confira se o .conf é de um servidor P2P com NAT-PMP"
  fi
fi

if [[ -n $(get_env TS_AUTHKEY) && " $parados " != *" tailscale "* ]]; then
  ts=$(docker exec tailscale tailscale status --json 2>/dev/null || true)
  nome=$(printf '%s' "$ts" | sed -n 's/.*"DNSName": *"\([^"]*\)\.".*/\1/p' | head -1)
  if printf '%s' "$ts" | grep -q '"BackendState": *"Running"' && [[ -n $nome ]]; then
    ok "acesso de fora de casa: https://$nome (Seerr em :8443)"
  else
    erro "o Tailscale não está conectado" \
         "a chave TS_AUTHKEY pode ter expirado ou já ter sido usada: gere outra no painel do Tailscale, troque no .env e rode ./setup.sh"
  fi
fi

# ---------- Disco ----------
secao "Disco"
data=$(get_env DATA_ROOT); data=${data:-./data}
if [[ ! -d $data ]]; then
  erro "a pasta de mídia não existe ($data)" "confira DATA_ROOT no .env e se o disco está montado"
else
  livre_kb=$(df -Pk "$data" | awk 'NR==2{print $4}')
  livre_gb=$((livre_kb / 1024 / 1024))
  if   [[ $livre_gb -lt 10 ]]; then erro "só $livre_gb GB livres em $data" "apague filmes/séries que já viu (no Radarr/Sonarr, para não baixar de novo)"
  elif [[ $livre_gb -lt 50 ]]; then aviso "$livre_gb GB livres em $data (um filme 1080p ocupa 2 a 15 GB)" "considere liberar espaço"
  else ok "$livre_gb GB livres em $data"; fi
  dev() { stat -c %d "$1" 2>/dev/null || stat -f %d "$1" 2>/dev/null; }
  if [[ -d $data/torrents && -d $data/media && "$(dev "$data/torrents")" != "$(dev "$data/media")" ]]; then
    aviso "downloads e biblioteca estão em discos diferentes" \
          "cada filme ocupa o dobro do espaço (sem hardlink). Deixe $data/torrents e $data/media no mesmo disco"
  fi
fi

# ---------- APIs ----------
if [[ -z $parados ]]; then
  echo
  out=$(docker compose $CP run --rm --no-deps -T -e FORWARDED_PORT="$FWD" setup \
        python /scripts/configure.py diagnostico 2>&1) || true
  printf '%s\n' "$out" | grep -vE '^@@resumo|^ ?(Container|Network) '
  resumo=$(printf '%s\n' "$out" | grep '^@@resumo' || true)
  if [[ -n $resumo ]]; then
    set -- $resumo
    ERR=$((ERR + $2)); WARN=$((WARN + $3))
  else
    erro "não consegui conferir os serviços por dentro" "rode ./setup.sh e tente de novo"
  fi
else
  echo; aviso "pulei a verificação por dentro dos serviços porque há serviço parado"
fi

fim
