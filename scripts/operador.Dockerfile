# Serviço "operador" e as tarefas que ele dispara (setup.sh, atualizar.sh, change-password.sh).
# Precisa do que esses scripts usam no host: bash, docker + compose, git, curl, tar.
FROM python:3.13-alpine
RUN apk add --no-cache bash docker-cli docker-cli-compose docker-cli-buildx git curl tar coreutils
