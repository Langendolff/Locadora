"""Configura a stack via API. Roda dentro da rede do compose (./setup.sh chama).

Idempotente: pode rodar várias vezes; o que já existe é mantido.
  python /scripts/configure.py          configura tudo
  python /scripts/configure.py passwd   troca a senha (usado por ./change-password.sh)
  python /scripts/configure.py diagnostico   só confere, não muda nada (usado por ./diagnostico.sh)
"""
import os
import sys

from stack.arr import arr
from stack.bazarr import bazarr
from stack.common import PASSWORD, RADARR, SONARR
from stack.deluge import deluge
from stack.jellyfin import jellyfin, notify_jellyfin
from stack.language import prefer_ptbr
from stack.passwd import change_password
from stack.prowlarr import prowlarr
from stack.seerr import seerr

if __name__ == "__main__":
    if sys.argv[1:] == ["diagnostico"]:
        from stack.diagnostico import diagnostico
        r = diagnostico()
        print(f"@@resumo {r.erros} {r.avisos}")  # lido pelo ./diagnostico.sh
        sys.exit(0)
    if sys.argv[1:2] == ["importar"] and len(sys.argv) >= 3:
        from stack.importar import importar
        importar(sys.argv[2], simular="--simular" in sys.argv[3:])
        sys.exit(0)
    if sys.argv[1:2] == ["pessoas"]:
        from stack import pessoas
        cmd, args = (sys.argv[2:3] or ["listar"])[0], sys.argv[3:]

        def opt(i, ok):  # argumento opcional i, validado contra as opções
            if len(args) <= i:
                return None
            if args[i].lower() not in ok:
                sys.exit(f"'{args[i]}': use {' ou '.join(ok)}")
            return args[i].lower()

        if cmd == "listar":
            pessoas.listar()
        elif cmd in ("nova", "preferencia") and args:
            a, l = opt(1, pessoas.AUDIO), opt(2, pessoas.LEGENDA)
            if cmd == "nova":
                pessoas.nova(args[0], os.environ.get("PESSOA_SENHA", ""), a, l)
            else:
                pessoas.preferencia(args[0], a, l)
            bazarr()  # legenda em inglês entra/sai do Bazarr conforme as escolhas
        else:
            sys.exit("uso: pessoas [listar | nova NOME | preferencia NOME] [dublado|original] [pt-br|en|nenhuma]")
        sys.exit(0)
    if sys.argv[1:] == ["passwd"]:
        change_password(PASSWORD, os.environ["NEW_STACK_PASSWORD"])
        print("\nSenha trocada em todos os serviços.")
        sys.exit(0)
    deluge()
    arr("radarr", RADARR, "/data/media/movies", "movieCategory", "movies")
    arr("sonarr", SONARR, "/data/media/tv", "tvCategory", "tv")
    print("Preferência PT-BR")
    prefer_ptbr("radarr", RADARR)
    prefer_ptbr("sonarr", SONARR)
    bazarr()
    prowlarr()
    jellyfin()
    notify_jellyfin()
    seerr()
    print("\nTudo configurado.")
