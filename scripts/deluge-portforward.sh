#!/usr/bin/with-contenv bash
# Serviço dentro do container do Deluge (linuxserver custom-services.d).
# O Gluetun grava em /gluetun/forwarded_port a porta que a Proton abriu pra gente;
# este loop aplica essa porta no Deluge sempre que ela muda.
FILE=/gluetun/forwarded_port
current=""
while true; do
  port=$(tr -dc '0-9' < "$FILE" 2>/dev/null)
  if [[ -n $port && $port != "$current" ]]; then
    if s6-setuidgid abc deluge-console -c /config "config -s listen_ports ($port, $port)" >/dev/null 2>&1 &&
       s6-setuidgid abc deluge-console -c /config "config -s random_port false" >/dev/null 2>&1; then
      echo "[portforward] Deluge escutando na porta $port"
      current=$port
    fi
  fi
  sleep 30
done
