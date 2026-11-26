#!/usr/bin/env bash
# Locadora: sobe e configura a stack inteira.
#   ./setup.sh                      (usa vpn/wg0.conf)
#   ./setup.sh ~/Downloads/meu.conf (copia a config WireGuard pra vpn/wg0.conf)
# Pode rodar de novo quantas vezes quiser: o que já está configurado é mantido.
# Funciona em Linux (Docker nativo ou Docker Desktop), macOS (Docker Desktop) e
# Windows (WSL2 + Docker Desktop; use Instalar.bat). Compatível com o bash 3.2 do macOS.
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERRO:\033[0m %s\n' "$*" >&2; exit 1; }

get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]$//"; }
set_env() {
  local key=$1 val=$2
  [[ $val == *"'"* ]] && die "o valor de $key não pode conter aspas simples (')"
  if grep -qE "^$key=" .env; then
    KEY="$key" VAL="'$val'" awk 'BEGIN{FS=OFS="="} $1==ENVIRON["KEY"]{print $1, ENVIRON["VAL"]; next} {print}' .env > .env.tmp
    cat .env.tmp > .env && rm .env.tmp
  else
    printf "%s='%s'\n" "$key" "$val" >> .env
  fi
}
fill() { [[ -n "$(get_env "$1")" ]] || set_env "$1" "$2"; }
gid_of() { getent group "$1" 2>/dev/null | cut -d: -f3; }
random_key() { LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | head -c 32; }
detect_tz() {
  local tz=""
  if command -v timedatectl >/dev/null 2>&1; then tz=$(timedatectl show -p Timezone --value 2>/dev/null || true); fi
  [[ -z $tz && -f /etc/timezone ]] && tz=$(cat /etc/timezone)
  [[ -z $tz && -L /etc/localtime ]] && tz=$(readlink /etc/localtime | sed -E 's|.*/zoneinfo/||')
  echo "${tz:-America/Sao_Paulo}"
}
port_in_use() {
  if command -v ss >/dev/null 2>&1; then ss -Htln "sport = :$1" | grep -q .
  elif command -v lsof >/dev/null 2>&1; then lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else return 1; fi
}

command -v docker >/dev/null || die "Docker não encontrado. Instale o Docker (Linux) ou o Docker Desktop (macOS/Windows)."
docker info >/dev/null 2>&1 || die "o Docker não está rodando. Inicie o Docker (ou abra o Docker Desktop) e tente de novo."
docker compose version >/dev/null 2>&1 || die "Plugin 'docker compose' não encontrado."
# Docker nativo no Linux: /dev/net/tun e GPU vêm do próprio sistema.
# Docker Desktop (macOS/Windows/Linux): roda numa VM que já tem tun e não repassa GPU.
if docker info --format '{{.OperatingSystem}}' 2>/dev/null | grep -qi "docker desktop"; then
  NATIVE=0
else
  NATIVE=1
  [[ -e /dev/net/tun ]] || die "/dev/net/tun não existe (necessário pro Gluetun). Rode: sudo modprobe tun"
fi

# Usa o projeto compose dos containers que já existem (instalações antigas podem ter outro nome)
PROJ=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' gluetun 2>/dev/null || true)
dc() { docker compose ${PROJ:+-p "$PROJ"} "$@"; }

# ---------- VPN ----------
mkdir -p vpn
if [[ $# -ge 1 ]]; then
  [[ -f $1 ]] || die "arquivo não encontrado: $1"
  cp "$1" vpn/wg0.conf
fi
[[ -f vpn/wg0.conf ]] || die "coloque sua config WireGuard em vpn/wg0.conf (ou rode ./setup.sh caminho/do/arquivo.conf)"
chmod 600 vpn/wg0.conf
grep -q '^PrivateKey' vpn/wg0.conf || die "vpn/wg0.conf não parece uma config WireGuard (sem PrivateKey)."

# ---------- .env ----------
if [[ ! -f .env ]]; then cp .env.example .env; fi
chmod 600 .env
# Acrescenta ao .env variáveis novas do .env.example (de atualizações do repositório)
while IFS= read -r line; do
  key=${line%%=*}
  [[ $line =~ ^[A-Z_]+= ]] && ! grep -qE "^$key=" .env && printf '%s\n' "$line" >> .env
done < .env.example

if [[ -z "$(get_env STACK_PASSWORD)" ]]; then
  [[ -t 0 ]] || die "defina STACK_PASSWORD no .env"
  read -rp "Usuário admin [$(get_env STACK_USER)]: " u
  [[ -n $u ]] && set_env STACK_USER "$u"
  while :; do
    read -rsp "Senha admin (mín. 8 caracteres): " p; echo
    read -rsp "Repita a senha: " p2; echo
    [[ $p == "$p2" && ${#p} -ge 8 ]] && break
    echo "Senhas diferentes ou curtas demais, tente de novo."
  done
  set_env STACK_PASSWORD "$p"
fi
pw=$(get_env STACK_PASSWORD)
[[ ${#pw} -ge 8 ]] || die "STACK_PASSWORD precisa ter pelo menos 8 caracteres."
unset pw

# Port forwarding: liga se o .conf foi gerado com NAT-PMP (Proton pago, servidor P2P)
if grep -qiE '^# *NAT-PMP.*= *on' vpn/wg0.conf; then set_env VPN_PORT_FORWARDING on; else set_env VPN_PORT_FORWARDING off; fi

fill TZ "$(detect_tz)"
fill PUID "$(id -u)"
fill PGID "$(id -g)"
fill DATA_ROOT ./data
for k in RADARR_API_KEY SONARR_API_KEY PROWLARR_API_KEY; do
  fill "$k" "$(random_key)"
done

if [[ $NATIVE == 1 && -d /dev/dri ]]; then
  set_env HAS_GPU 1
  set_env COMPOSE_FILE docker-compose.yml:docker-compose.gpu.yml
  fill RENDER_GID "$(gid_of render || true)"
  fill VIDEO_GID "$(gid_of video || true)"
  [[ -n "$(get_env RENDER_GID)" ]] || set_env RENDER_GID "$(stat -c %g /dev/dri/renderD* 2>/dev/null | head -1)"
  [[ -n "$(get_env VIDEO_GID)" ]]  || set_env VIDEO_GID "$(get_env RENDER_GID)"
else
  set_env HAS_GPU 0
  set_env COMPOSE_FILE docker-compose.yml
fi

# Acesso de fora de casa: o container do Tailscale só sobe com a chave no .env
if [[ -n "$(get_env TS_AUTHKEY)" ]]; then set_env COMPOSE_PROFILES remoto; else set_env COMPOSE_PROFILES ""; fi

# ---------- Portas ----------
for svc in JELLYFIN:8096 SEERR:5055 RADARR:7878 SONARR:8989 PROWLARR:9696 DELUGE:8112 BAZARR:6767; do
  fill "${svc%%:*}_PORT" "${svc##*:}"
done
if [[ -z "$(dc ps -q 2>/dev/null)" ]]; then
  for k in JELLYFIN SEERR RADARR SONARR PROWLARR DELUGE BAZARR; do
    port=$(get_env "${k}_PORT")
    if port_in_use "$port"; then
      die "a porta $port (${k}_PORT) já está em uso. Mude ${k}_PORT no .env."
    fi
  done
fi

# ---------- Pastas ----------
data=$(get_env DATA_ROOT)
mkdir -p config/{gluetun,deluge,prowlarr,radarr,sonarr,bazarr,jellyfin,seerr,tarefas,tailscale} \
         "$data"/torrents/{movies,tv,incomplete} "$data"/media/{movies,tv}

# ---------- Subir ----------
say "Baixando imagens e subindo containers..."
dc pull -q --ignore-buildable
dc build -q tarefas
dc up -d --remove-orphans --wait

say "Verificando a VPN..."
vpn_ip=$(docker exec deluge curl -fsS --max-time 15 https://ipinfo.io/ip 2>/dev/null || true)
[[ -n $vpn_ip ]] || die "a VPN não conectou. Veja: docker compose logs gluetun"
echo "    IP público do Deluge (VPN): $vpn_ip"

# Endereço do Tailscale (vira o link dos avisos do Seerr)
remoto=""
if [[ $(get_env COMPOSE_PROFILES) == *remoto* ]]; then
  say "Conectando ao Tailscale..."
  for _ in $(seq 1 30); do
    remoto=$(docker exec tailscale tailscale status --json 2>/dev/null \
             | sed -n 's/.*"DNSName": *"\([^"]*\)\.".*/\1/p' | head -1)
    [[ -n $remoto ]] && break
    sleep 2
  done
  if [[ -n $remoto ]]; then echo "    $remoto"
  else echo "    AVISO: o Tailscale não conectou (chave usada/expirada?). Veja: docker compose logs tailscale"; fi
fi

say "Configurando os serviços..."
dc run --rm -e LOCADORA_URL_REMOTA="${remoto:+https://$remoto}" setup

p() { get_env "$1_PORT"; }
cat <<EOF

Pronto! Acesse:
  Seerr     http://localhost:$(p SEERR)   (pedir filmes/séries)
  Jellyfin  http://localhost:$(p JELLYFIN)   (assistir)
  Radarr    http://localhost:$(p RADARR)
  Sonarr    http://localhost:$(p SONARR)
  Prowlarr  http://localhost:$(p PROWLARR)   <- adicione seus indexadores aqui
  Deluge    http://localhost:$(p DELUGE)
  Bazarr    http://localhost:$(p BAZARR)   (legendas pt-BR)
Login em todos: $(get_env STACK_USER) / (sua senha do .env)
${remoto:+De fora de casa (aparelhos no seu Tailscale):
  Jellyfin  https://$remoto
  Seerr     https://$remoto:8443
}Cadastrar a família: ./pessoas.sh nova NOME   ·   Algo não funciona? ./diagnostico.sh
EOF
