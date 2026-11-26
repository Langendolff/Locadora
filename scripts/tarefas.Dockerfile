# Serviço "tarefas" (bot do Telegram, limpeza, downloads do YouTube).
# ffmpeg junta vídeo e áudio; deno resolve os desafios de JavaScript do YouTube para o yt-dlp.
# O yt-dlp se atualiza sozinho a cada início do container (scripts/stack/youtube.py).
FROM python:3.13-alpine
RUN apk add --no-cache ffmpeg deno \
 && pip install --no-cache-dir --disable-pip-version-check "yt-dlp[default]"
