#!/usr/bin/env bash
# Gera os pacotes da Locadora para Linux, macOS e Windows e publica um release no GitHub.
#   scripts/release.sh v1.0.0            gera em dist/ e publica (precisa do gh autenticado)
#   scripts/release.sh v1.0.0 --local    só gera em dist/
# Usa o conteúdo commitado (git archive), então segredos e dados locais nunca entram.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=${1:?uso: scripts/release.sh vX.Y.Z [--local]}
[[ $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "versão deve ser vX.Y.Z" >&2; exit 1; }
LOCAL=${2:-}
[[ -z "$(git status --porcelain)" ]] || { echo "há mudanças não commitadas; faça commit antes" >&2; exit 1; }
python3 -m unittest discover -s tests -q || { echo "testes falharam; nada foi gerado" >&2; exit 1; }

DIST=dist; NAME=Locadora
rm -rf "$DIST"; mkdir -p "$DIST/work"

base() {  # base <destino>: árvore commitada, sem a pasta install/
  mkdir -p "$1"
  git archive --format=tar HEAD | tar -x -C "$1"
  rm -rf "$1/install"
  echo "$VERSION" > "$1/VERSION"
}

# ---------- Linux (.tar.gz preserva permissões) ----------
L="$DIST/work/linux/$NAME"; base "$L"
cp install/linux/LEIA-ME.txt "$L/"
tar -C "$DIST/work/linux" -czf "$DIST/$NAME-$VERSION-linux.tar.gz" "$NAME"

# ---------- macOS (.zip com bit de execução) ----------
M="$DIST/work/macos/$NAME"; base "$M"
cp install/macos/LEIA-ME.txt install/macos/Instalar.command install/macos/Diagnostico.command "$M/"

# ---------- Windows (.zip; .bat em CRLF, .ps1 em UTF-8 com BOM) ----------
W="$DIST/work/windows/$NAME"; base "$W"
sed 's/$/\r/' install/windows/Instalar.bat > "$W/Instalar.bat"
sed 's/$/\r/' install/windows/Diagnostico.bat > "$W/Diagnostico.bat"
sed 's/$/\r/' install/windows/LEIA-ME.txt > "$W/LEIA-ME.txt"
{ printf '\xEF\xBB\xBF'; sed 's/$/\r/' install/windows/instalar.ps1; } > "$W/instalar.ps1"

python3 - "$DIST" "$NAME" "$VERSION" <<'PY'
import os, stat, sys, zipfile
dist, name, ver = sys.argv[1:4]
for osname in ("macos", "windows"):
    root = os.path.join(dist, "work", osname)
    out = os.path.join(dist, f"{name}-{ver}-{osname}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d, _, files in os.walk(root):
            for f in sorted(files):
                p = os.path.join(d, f); arc = os.path.relpath(p, root)
                info = zipfile.ZipInfo.from_file(p, arc)
                mode = os.stat(p).st_mode
                exe = bool(mode & stat.S_IXUSR) or f.endswith((".sh", ".command"))
                info.external_attr = ((0o100755 if exe else 0o100644) << 16)
                info.create_system = 3          # Unix: o macOS respeita as permissões
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(p, "rb") as fh:
                    z.writestr(info, fh.read())
PY

rm -rf "$DIST/work"
( cd "$DIST" && sha256sum Locadora-* > SHA256SUMS.txt )
ls -lh "$DIST"

[[ $LOCAL == --local ]] && exit 0

# ---------- Publica ----------
NOTES=$(mktemp)
cat > "$NOTES" <<EOF
## Locadora $VERSION

Seu serviço de streaming, no seu servidor: peça um filme ou série, ele é encontrado, baixado
pela VPN, organizado com legenda pt-BR e aparece pronto no Jellyfin.

### Downloads

| Sistema | Arquivo | Como instalar |
|---|---|---|
| **Windows 10/11** | \`$NAME-$VERSION-windows.zip\` | Requer WSL2 + Docker Desktop. Extraia e clique duas vezes em **Instalar.bat** |
| **macOS** | \`$NAME-$VERSION-macos.zip\` | Requer Docker Desktop. Extraia e clique duas vezes em **Instalar.command** (1ª vez: botão direito > Abrir) |
| **Linux** | \`$NAME-$VERSION-linux.tar.gz\` | Requer Docker. Extraia e rode \`./setup.sh ~/Downloads/sua-vpn.conf\` |

Em todos: tenha à mão o arquivo **WireGuard (.conf)** de uma VPN que permita P2P.
Cada pacote traz um **LEIA-ME.txt** com o passo a passo. Verificação: \`SHA256SUMS.txt\`.

Documentação completa: [README](https://github.com/Langendolff/Locadora#readme)
EOF
if gh release view "$VERSION" >/dev/null 2>&1; then
  gh release upload "$VERSION" "$DIST"/* --clobber
else
  gh release create "$VERSION" "$DIST"/* --title "Locadora $VERSION" --notes-file "$NOTES"
fi
rm -f "$NOTES"
