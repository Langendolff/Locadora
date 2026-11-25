#!/usr/bin/env bash
# Traz para a Locadora filmes que você já tem numa pasta (um filme por pasta ou arquivo,
# de preferência com o nome "Título (Ano)"; título em português ou no original).
#   ./importar.sh ~/Videos/Movies              importa
#   ./importar.sh ~/Videos/Movies --simular    só mostra como cada filme foi reconhecido
# Os originais NÃO são movidos nem apagados. No mesmo disco da Locadora não ocupa espaço extra
# (hardlinks); em outro disco os arquivos são copiados (pede confirmação).
# Compatível com o bash 3.2 do macOS.
set -euo pipefail
cd "$(dirname "$0")"
die() { printf '\033[1;31mERRO:\033[0m %s\n' "$*" >&2; exit 1; }
get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]$//"; }

src=${1:-}; shift || true
[[ -n $src && -d $src ]] || die "uso: ./importar.sh PASTA [--simular]"
docker inspect radarr >/dev/null 2>&1 || die "a Locadora não está rodando. Rode ./setup.sh"
data=$(get_env DATA_ROOT); data=${data:-./data}
src=$(cd "$src" && pwd)

dev() { stat -c %d "$1" 2>/dev/null || stat -f %d "$1"; }
mesmo_disco=0; [[ "$(dev "$src")" == "$(dev "$data")" ]] && mesmo_disco=1
if [[ $mesmo_disco == 0 && " $* " != *" --simular "* ]]; then
  tam=$(du -sh "$src" | cut -f1)
  echo "A pasta está em outro disco: os filmes serão COPIADOS para $data ($tam)."
  [[ -t 0 ]] || die "rode num terminal para confirmar"
  read -rp "Continuar? [s/N] " r; [[ $r == [sS]* ]] || exit 1
fi

lote="importar/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$data/$lote"
trap 'rm -rf "$data/$lote"' EXIT   # só apaga os links/cópias temporárias, nunca os originais
n=0
while IFS= read -r -d '' f; do
  rel=${f#"$src"/}
  mkdir -p "$data/$lote/$(dirname "$rel")"
  if [[ $mesmo_disco == 1 ]]; then ln "$f" "$data/$lote/$rel"; else cp "$f" "$data/$lote/$rel"; fi
  n=$((n + 1))
done < <(find "$src" -type f \( -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.avi' -o -iname '*.m4v' \
                                -o -iname '*.mov' -o -iname '*.srt' \) -print0)
[[ $n -gt 0 ]] || die "nenhum vídeo em $src"
echo "$n arquivo(s) encontrados"

proj=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' radarr 2>/dev/null || true)
docker compose ${proj:+-p "$proj"} run --rm --no-deps -T setup \
  python /scripts/configure.py importar "/data/$lote" "$@" 2> >(grep -vE '^ ?(Container|Network) ' >&2)
