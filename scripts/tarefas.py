"""Serviço "tarefas": fica rodando e cuida do que precisa acontecer sozinho.

  - bot do Telegram (se TELEGRAM_BOT_TOKEN estiver no .env)
  - limpeza automática todo dia às 4h (se LIMPEZA_DIAS estiver no .env)

  python /scripts/tarefas.py                serviço (docker-compose: tarefas)
  python /scripts/tarefas.py limpeza        mostra o que a limpeza tiraria hoje (não apaga)
  python /scripts/tarefas.py limpeza agora  roda a limpeza agora
"""
import datetime as dt
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stack import limpeza, telegram  # noqa: E402

HORA_LIMPEZA = 4


def avisar_admin(texto):
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if telegram.TOKEN and chat:
        try:
            telegram.enviar(chat, texto)
        except Exception as e:
            print(f"[limpeza] não consegui avisar no Telegram: {e}", flush=True)


def laco_limpeza():
    dias = int(os.environ.get("LIMPEZA_DIAS") or 0)
    print(f"[limpeza] filmes que todo mundo viu há {dias}+ dias saem todo dia às {HORA_LIMPEZA}h", flush=True)
    while True:
        agora = dt.datetime.now()
        prox = agora.replace(hour=HORA_LIMPEZA, minute=0, second=0, microsecond=0)
        if prox <= agora:
            prox += dt.timedelta(days=1)
        time.sleep((prox - agora).total_seconds())
        try:
            limpeza.limpeza(avisar=avisar_admin)
        except Exception as e:
            print(f"[limpeza] erro: {e}; tento de novo amanhã", flush=True)


def main():
    if sys.argv[1:2] == ["limpeza"]:
        if sys.argv[2:3] == ["agora"]:
            if not int(os.environ.get("LIMPEZA_DIAS") or 0):
                sys.exit("A limpeza está desligada: defina LIMPEZA_DIAS no .env (ex.: 30)")
            r = limpeza.limpeza(avisar=avisar_admin)
            print("Removidos:", ", ".join(r) if r else "nenhum")
        else:
            limpeza.limpeza(simular=True)
        return

    tarefas = []
    if telegram.TOKEN:
        tarefas.append(threading.Thread(target=telegram.rodar, daemon=True, name="bot"))
    if int(os.environ.get("LIMPEZA_DIAS") or 0) > 0:
        tarefas.append(threading.Thread(target=laco_limpeza, daemon=True, name="limpeza"))
    if not tarefas:
        print("[tarefas] nada ligado (TELEGRAM_BOT_TOKEN e LIMPEZA_DIAS vazios no .env); esperando", flush=True)
    for t in tarefas:
        t.start()
    while True:  # se uma tarefa morrer, o container reinicia (restart: unless-stopped)
        time.sleep(60)
        if any(not t.is_alive() for t in tarefas):
            sys.exit("[tarefas] uma tarefa parou; reiniciando")


if __name__ == "__main__":
    main()
