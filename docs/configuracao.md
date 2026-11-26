# Configuração

Tudo o que é pessoal fica em dois arquivos, **ambos fora do git**:

| Arquivo | Conteúdo |
|---|---|
| `.env` | login, portas, pastas, contas de legenda e chaves internas geradas |
| `vpn/wg0.conf` | configuração WireGuard do seu provedor de VPN |

O `.env` é criado pelo `./setup.sh` a partir do `.env.example`. Quando o repositório ganha
variáveis novas, o `./setup.sh` as acrescenta ao seu `.env` (vazias) sem mexer no resto.

## Variáveis do `.env`

### Você preenche

| Variável | Padrão | Descrição |
|---|---|---|
| `STACK_USER` | `admin` | Usuário de todos os serviços |
| `STACK_PASSWORD` | — | Senha de todos os serviços (o `setup.sh` pergunta). Para trocar depois: `./change-password.sh` |
| `STACK_EMAIL` | `admin@example.com` | E-mail do admin no Seerr |
| `DATA_ROOT` | `./data` | Onde ficam downloads e biblioteca. Defina **antes** do primeiro `setup.sh` |
| `OPENSUBTITLES_USER` / `OPENSUBTITLES_PASSWORD` | — | Conta grátis em opensubtitles.com (recomendado) |
| `SUBDL_API_KEY` | — | Chave grátis em subdl.com |
| `LEGENDASNET_USER` / `LEGENDASNET_PASSWORD` | — | Conta grátis em legendas.net |
| `TELEGRAM_BOT_TOKEN` | — | Bot de pedidos e avisos no Telegram ([extras](extras.md#bot-do-telegram)) |
| `TELEGRAM_CHAT_ID` | — | Opcional: chat que recebe os avisos gerais (tudo que fica pronto, falhas, limpeza) |
| `TS_AUTHKEY` | — | Acesso de fora de casa pelo Tailscale ([extras](extras.md#assistir-de-fora-de-casa-tailscale)) |
| `LIMPEZA_DIAS` | — | Tira filmes que todo mundo viu há este tanto de dias, ex.: `30` ([extras](extras.md#limpeza-automática)) |
| `PAINEL_MANUTENCAO` | — | `off` deixa o Painel só com pessoas e diagnóstico: sem o serviço `operador`, que tem acesso ao Docker |

Pelo Painel (aba Configurações) dá para mudar o e-mail, as contas de legenda, o Telegram, o
Tailscale, a limpeza e as portas. Ficam só no arquivo: `STACK_USER`, `DATA_ROOT` e os que o
`setup.sh` preenche. A senha tem botão próprio, que troca em todos os serviços.

### Portas no host

| Variável | Padrão | Serviço |
|---|---|---|
| `SEERR_PORT` | 5055 | Seerr |
| `JELLYFIN_PORT` | 8096 | Jellyfin |
| `RADARR_PORT` | 7878 | Radarr |
| `SONARR_PORT` | 8989 | Sonarr |
| `PROWLARR_PORT` | 9696 | Prowlarr |
| `DELUGE_PORT` | 8112 | Deluge |
| `BAZARR_PORT` | 6767 | Bazarr |
| `PAINEL_PORT` | 8585 | Painel (pessoas e diagnóstico) |

O FlareSolverr (8191) só escuta em `127.0.0.1`. Se uma porta estiver ocupada, o `setup.sh` avisa.

### Preenchidas pelo `setup.sh`

`TZ`, `PUID`, `PGID`, `RENDER_GID`, `VIDEO_GID`, `HAS_GPU`, `COMPOSE_FILE`, `COMPOSE_PROFILES`, `VPN_PORT_FORWARDING`
e as chaves `RADARR_API_KEY`, `SONARR_API_KEY`, `PROWLARR_API_KEY` (geradas aleatoriamente).

## VPN

Qualquer provedor com WireGuard funciona (`VPN_SERVICE_PROVIDER=custom` no Gluetun). Para
torrent, o provedor precisa **permitir P2P**: os servidores gratuitos da Proton, por exemplo, não permitem.

### ProtonVPN (recomendado: plano pago)

Em **account.protonvpn.com → Downloads → WireGuard configuration**:

| Opção | Valor |
|---|---|
| Plataforma | GNU/Linux |
| NetShield | Desligado |
| Moderate NAT | Desligado |
| **NAT-PMP (Port Forwarding)** | **Ligado** |
| VPN Accelerator | Ligado |
| Servidor | um com o ícone **P2P**, perto de você; **Standard**, não Secure Core |

Depois:

```bash
./setup.sh ~/Downloads/arquivo-baixado.conf
```

O script copia para `vpn/wg0.conf`, detecta o NAT-PMP e liga o redirecionamento de porta sozinho.

## GPU

Se existir `/dev/dri`, o `setup.sh` inclui `docker-compose.gpu.yml` e o Jellyfin passa a converter
vídeo pela GPU (VAAPI, Intel/AMD). Sem GPU, a conversão é feita pelo processador.

## Disco

Para guardar a mídia em outro HD, aponte `DATA_ROOT` para ele **antes** do primeiro `./setup.sh`,
por exemplo `DATA_ROOT=/mnt/hd/locadora`. `torrents/` e `media/` precisam ficar no mesmo disco.
