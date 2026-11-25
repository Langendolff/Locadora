# Solução de problemas

**Comece pelo diagnóstico:**

```bash
./diagnostico.sh        # Windows: Diagnostico.bat · macOS: Diagnostico.command
```

Ele só lê, não muda nada. Confere Docker, serviços, VPN (inclusive se o tráfego está vazando),
porta redirecionada, espaço em disco, hardlinks, indexadores, fila de downloads, a senha que
o Radarr/Sonarr usam no Deluge e o login do Jellyfin. Para cada problema, diz o que fazer.

## Download parado em 0%

Quase sempre o lançamento escolhido ficou sem fontes. A contagem de seeds dos sites é desatualizada.

No Radarr (ou Sonarr): **Activity → Queue → ❌ → marque "Blocklist Release"**. Ele descarta esse
lançamento e busca outro.

Se **todos** os downloads param, verifique a VPN:

```bash
docker exec deluge curl -s ipinfo.io/ip     # deve mostrar o IP da VPN
docker compose logs gluetun | tail -20
cat config/gluetun/forwarded_port           # porta redirecionada (Proton pago)
```

Servidores gratuitos da Proton **não permitem P2P**. Use um servidor P2P de um plano pago.

## "Erro fatal do player" no Jellyfin

O Jellyfin está apontando para um arquivo que não existe mais, geralmente porque o Radarr
trocou por uma versão melhor. Os avisos do Radarr/Sonarr para o Jellyfin já evitam isso. Se
acontecer: **Painel → Bibliotecas → Escanear todas as bibliotecas** e recarregue a página.

## Áudio em outro idioma

Lançamentos com várias faixas (ex.: italiano + inglês) às vezes têm o idioma errado como padrão.
O perfil atual recusa esse tipo de lançamento. Para um item já baixado, no Radarr: abra o filme →
**Search** (ícone de lupa) e escolha uma versão no idioma original.

## Legenda fora de sincronia

O Bazarr já sincroniza toda legenda. Se ainda estiver errada, a legenda foi feita para outro
corte do filme. No Bazarr: abra o filme → **Search** → escolha outra legenda (de preferência uma
com o nome do lançamento parecido com o do seu arquivo). Ter OpenSubtitles configurado ajuda muito.

## Porta ocupada

O `setup.sh` avisa qual porta está em uso. Mude a variável `*_PORT` correspondente no `.env` e
rode `./setup.sh` de novo.

## Uma atualização quebrou algo

O `./atualizar.sh` faz backup das configurações antes de atualizar. Para voltar:

```bash
./atualizar.sh --restaurar          # lista os backups
./atualizar.sh --restaurar backups/locadora-AAAAMMDD-HHMMSS.tar.gz
```

As configurações de antes da restauração ficam em `config.antes-…/`, por segurança.
Filmes e séries não entram no backup nem são tocados.

## Disco cheio

Com menos de 10 GB livres, o Radarr/Sonarr param de importar (para o disco não encher até
travar os bancos de dados), e o `./diagnostico.sh` avisa a partir de 50 GB. Para liberar espaço,
apague pelo **Radarr/Sonarr** (filme → 🗑 → "Excluir arquivos"), não direto na pasta, para ele
não baixar de novo. Por causa dos hardlinks, o espaço só volta quando o arquivo sai também do
Deluge: remova o torrent lá ("Remove Torrent" → com os dados), se ele ainda estiver semeando.

## Recomeçar do zero

Apaga configurações e bancos de dados (mantém downloads e biblioteca):

```bash
docker compose down
rm -rf config .env
./setup.sh
```

## Comandos úteis

```bash
docker compose ps                              # status de cada serviço
docker compose logs -f <serviço>               # logs
./atualizar.sh                                 # atualizar (com backup antes)
./atualizar.sh --restaurar ARQUIVO             # voltar a um backup
docker compose down                            # parar tudo
./setup.sh                                     # reaplicar a configuração (idempotente)
./diagnostico.sh                               # conferir se está tudo funcionando
```
