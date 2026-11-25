#!/usr/bin/with-contenv bash
# Inicialização do container do Jellyfin (linuxserver custom-cont-init.d).
# Troca logo, favicon e ícones da interface web pelos da Locadora. Roda a cada partida,
# então sobrevive a atualizações do Jellyfin (que mudam os nomes com hash dos arquivos).
WEB=/usr/share/jellyfin/web
IMG=$WEB/locadora/img
[[ -d $WEB && -d $IMG ]] || exit 0

swap() {  # swap <arquivo-da-locadora> <padrão-dos-arquivos-originais>
  local src=$IMG/$1 f
  for f in $WEB/$2; do [[ -f $f ]] && cp -f "$src" "$f"; done
}
swap banner-light.png     'banner-light.*.png'
swap banner-dark.png      'banner-dark.*.png'
swap icon-transparent.png 'icon-transparent.*.png'
swap touchicon180.png     'touchicon.*.png'
swap favicon.ico          'favicon.*.ico'
for s in 72 114 144 512; do swap touchicon$s.png "favicons/touchicon$s.png"; done
swap touchicon180.png     'favicons/touchicon.png'

# Nome na aba do navegador e no app instalado
sed -i 's|<title>Jellyfin</title>|<title>Locadora</title>|' $WEB/index.html
sed -i -E 's/"(short_)?name": *"Jellyfin"/"\1name": "Locadora"/; s/"(theme|background)_color": *"#101010"/"\1_color": "#0F1014"/' $WEB/manifest.json

echo "[locadora] marca aplicada na interface web"
