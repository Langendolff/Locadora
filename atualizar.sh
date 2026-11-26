#!/usr/bin/env bash
# Atualiza a Locadora com segurança: backup das configurações antes, diagnóstico depois.
#   ./atualizar.sh                       backup + imagens novas + reaplica a configuração
#   ./atualizar.sh --backup              só o backup
#   ./atualizar.sh --restaurar ARQUIVO   volta as configurações de um backup
# Backups em backups/ (os 5 mais recentes). Guardam config/ (bancos de dados dos serviços),
# .env e vpn/wg0.conf; filmes e séries (DATA_ROOT) NÃO entram. Compatível com o bash 3.2 do macOS.
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERRO:\033[0m %s\n' "$*" >&2; exit 1; }
MANTER=5

[[ -f .env ]] || die "rode ./setup.sh primeiro"
docker info >/dev/null 2>&1 || die "o Docker não está rodando"
# Mesmo projeto compose dos containers atuais (a pasta pode ter sido renomeada)
proj=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' gluetun 2>/dev/null || true)
dc() { docker compose ${proj:+-p "$proj"} "$@"; }

backup() {
  mkdir -p backups && chmod 700 backups
  local f="backups/locadora-$(date +%Y%m%d-%H%M%S).tar.gz"
  say "Parando os serviços para copiar os bancos de dados com segurança..."
  dc stop >/dev/null 2>&1 || true
  say "Fazendo backup em $f..."
  local extra=""; [[ -f vpn/wg0.conf ]] && extra="vpn/wg0.conf"
  # Fica de fora o que se recria sozinho: logs, capas, cache e conversões do Jellyfin
  if ! tar -czf "$f" --exclude='config/*/logs' --exclude='config/*/log' --exclude='*.log' \
        --exclude='config/*/logs.db*' --exclude='config/*/MediaCover' --exclude='config/*/Sentry' \
        --exclude='config/jellyfin/cache' --exclude='config/jellyfin/data/transcodes' \
        --exclude='config/jellyfin/log' --exclude='config/bazarr/cache' \
        config .env $extra; then
    rm -f "$f"; dc up -d >/dev/null 2>&1 || true
    die "o backup falhou (disco cheio?). Nada foi alterado; os serviços voltaram."
  fi
  chmod 600 "$f"
  # Remove os mais antigos
  ls -1t backups/locadora-*.tar.gz 2>/dev/null | tail -n +$((MANTER + 1)) | while read -r old; do rm -f "$old"; done
  echo "    $(du -h "$f" | cut -f1)  $f   (contém senhas: não compartilhe)"
}

case ${1:-} in
  --backup)
    backup
    say "Religando os serviços..."
    # up (não start): recria containers cuja configuração mudou, como quando a pasta foi
    # renomeada ou movida e os caminhos antigos não existem mais
    dc up -d --wait >/dev/null 2>&1 || dc up -d --wait   # mostra as mensagens só se der erro
    exit 0 ;;

  --restaurar)
    f=${2:-}
    [[ -n $f ]] || { echo "Backups disponíveis:"; ls -1t backups/locadora-*.tar.gz 2>/dev/null || echo "  (nenhum)"
                     echo "uso: ./atualizar.sh --restaurar backups/locadora-....tar.gz"; exit 1; }
    [[ -f $f ]] || die "arquivo não encontrado: $f"
    tar -tzf "$f" | grep -q '^config/' || die "$f não parece um backup da Locadora"
    if [[ -t 0 ]]; then
      read -rp "Isso troca as configurações atuais pelas de $f (filmes e séries não são tocados). Continuar? [s/N] " r
      [[ $r == [sS]* ]] || exit 1
    fi
    say "Parando os serviços..."
    dc stop >/dev/null 2>&1 || true
    antes="config.antes-$(date +%Y%m%d-%H%M%S)"
    mv config "$antes"
    cp .env "$antes/.env"
    [[ -f vpn/wg0.conf ]] && cp vpn/wg0.conf "$antes/wg0.conf"
    say "Restaurando $f (as configurações de agora ficam em $antes/)..."
    if ! tar -xzf "$f"; then
      rm -rf config; mv "$antes" config; die "não consegui extrair o backup; nada mudou"
    fi
    say "Subindo os serviços..."
    dc up -d --wait >/dev/null 2>&1 || dc up -d --wait   # mostra as mensagens só se der erro
    echo "Pronto. Se tudo estiver certo, pode apagar $antes/."
    exit 0 ;;

  "") ;;
  *) die "opção desconhecida: $1 (use --backup ou --restaurar)" ;;
esac

# ---------- Atualização completa ----------
# Instalação pelo git: traz a versão nova do código primeiro e recomeça com ela
if [[ -d .git && -z ${LOCADORA_ATUALIZADO:-} ]] && command -v git >/dev/null 2>&1; then
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "    (código com mudanças locais: não vou puxar a versão nova do git)"
  elif git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    say "Buscando a versão nova da Locadora..."
    antes=$(git rev-parse HEAD)
    git pull --ff-only -q || die "não consegui atualizar o código (git pull). Nada foi alterado."
    if [[ $(git rev-parse HEAD) != "$antes" ]]; then
      git log --oneline "$antes..HEAD" | sed 's/^/    /'
      LOCADORA_ATUALIZADO=1 exec ./atualizar.sh
    fi
  fi
fi

say "Baixando as imagens novas (os serviços continuam no ar)..."
dc pull -q --ignore-buildable
dc build -q --pull tarefas     # imagem local do serviço "tarefas" (yt-dlp, ffmpeg)
backup
say "Subindo a versão nova..."
dc up -d --remove-orphans --wait >/dev/null 2>&1 || dc up -d --remove-orphans --wait
say "Reaplicando a configuração..."
dc run --rm setup
echo
./diagnostico.sh || true
echo
echo "Deu errado? Volte ao estado de antes: ./atualizar.sh --restaurar $(ls -1t backups/locadora-*.tar.gz | head -1)"
