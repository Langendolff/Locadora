# Desenvolvimento

## Estrutura

```
.
├── setup.sh                 # instala/atualiza: .env, containers, VPN, configuração
├── change-password.sh       # troca a senha em todos os serviços
├── diagnostico.sh           # confere VPN, disco e serviços (só lê)
├── pessoas.sh               # pessoas da casa e preferência de áudio/legenda
├── atualizar.sh             # backup + imagens novas + reaplica (e --restaurar)
├── limpeza.sh               # simula/roda a limpeza automática
├── importar.sh              # traz filmes de uma pasta para a biblioteca
├── docker-compose.yml       # todos os serviços + container efêmero "setup"
├── docker-compose.gpu.yml   # aceleração de vídeo no Jellyfin (incluído se houver /dev/dri)
├── .env.example             # modelo do .env
├── scripts/
│   ├── configure.py         # ponto de entrada da configuração automática
│   ├── tarefas.py           # serviço "tarefas": bot do Telegram + limpeza diária
│   ├── tarefas.Dockerfile   # imagem do "tarefas": Python + yt-dlp, ffmpeg e deno
│   ├── painel.py            # serviço "painel": interface web
│   ├── painel/              # HTML, CSS e JS do painel (sem dependências)
│   ├── operador.py          # serviço "operador": o que o painel faz no Docker e no .env
│   ├── operador.Dockerfile  # imagem do operador e das tarefas: Python + bash, docker, git
│   ├── tailscale-serve.json # o que o Tailscale publica (Jellyfin :443, Seerr :8443)
│   ├── deluge-portforward.sh# serviço no container do Deluge: aplica a porta da VPN
│   ├── jellyfin-branding.sh # inicialização do Jellyfin: logo e ícones da Locadora
│   ├── release.sh           # gera os pacotes Linux/macOS/Windows e publica o release
│   └── stack/               # um módulo por serviço
│       ├── common.py        #   credenciais, endereços, cliente HTTP
│       ├── deluge.py
│       ├── arr.py           #   Radarr e Sonarr
│       ├── language.py      #   formatos e perfil PT-BR
│       ├── bazarr.py
│       ├── prowlarr.py
│       ├── jellyfin.py      #   + avisos do Radarr/Sonarr ao Jellyfin
│       ├── seerr.py
│       ├── diagnostico.py   #   verificações por API do ./diagnostico.sh e do painel
│       ├── pessoas.py       #   usado por pessoas.sh e pelo painel
│       ├── telegram.py      #   bot de pedidos
│       ├── youtube.py       #   /youtube do bot: escolhe episódios, baixa e importa no Sonarr
│       ├── limpeza.py       #   regra e remoção da limpeza automática
│       ├── importar.py      #   usado por importar.sh
│       ├── passwd.py        #   usado por change-password.sh
│       └── envfile.py       #   campos do .env que o painel pode mudar, validação e gravação
├── tests/                   # testes sem a stack (python3 -m unittest discover -s tests)
├── install/                 # instaladores de cada sistema (entram nos pacotes de release)
├── indexers/                # seus indexadores (fora do git; modelo: public.example.txt)
├── vpn/                     # wg0.conf (fora do git)
├── assets/                  # logo, ícones e tema do Jellyfin
└── docs/
```

Fora do git: `.env`, `vpn/wg0.conf`, `config/` (bancos de dados) e `data/` (mídia).

## Como a configuração funciona

O `scripts/configure.py` roda no container `setup` (`python:3.13-alpine`, só biblioteca padrão),
dentro da rede do compose, e fala com cada serviço pela API HTTP dele. Regras que todo módulo segue:

1. **Idempotente:** lê o estado atual e só altera o que estiver diferente.
2. **Só loga o que muda.** Uma segunda execução sem mudanças fica quase silenciosa.
3. **Usa o esquema da API** (`/schema`) para montar objetos, em vez de JSON fixo, para
   acompanhar atualizações dos serviços.

Para testar uma alteração:

```bash
docker compose run --rm setup    # aplica
docker compose run --rm setup    # deve sair sem mudanças
```

## Testes

```bash
python3 -m unittest discover -s tests -v
```

Rodam sem Docker e sem a stack, só com a biblioteca padrão. Rodam também no GitHub Actions a cada
push e antes de cada release (`scripts/release.sh` recusa gerar pacotes se falharem).

- `tests/test_idioma.py`: títulos que devem (ou não) contar como áudio em português. Ao mexer nas
  regex de `scripts/stack/language.py`, acrescente ali o título que motivou a mudança.
  Para conferir no Radarr de verdade: `GET /api/v3/parse?title=<título>` lista os formatos que casam.

## Painel

Dois serviços, para o que fica exposto na rede não ter acesso ao Docker:

```
navegador ──▶ painel (8585, login) ──▶ operador (8586, só rede interna, OPERADOR_TOKEN)
                 │                        │  socket do Docker, pasta da Locadora no mesmo caminho do host
                 ▼                        ▼
         APIs dos serviços         docker inspect/exec · .env · container avulso "locadora-tarefa"
         (pessoas, diagnóstico)       que roda setup.sh / atualizar.sh / change-password.sh
```

- **`painel`** (`scripts/painel.py`): servidor HTTP da biblioteca padrão. Pessoas e o diagnóstico
  "por dentro" chamam `scripts/stack/` como os scripts de terminal; o resto ele repassa ao operador.
  Tela nova = função em `stack/` que devolve dados (em vez de só imprimir) + uma rota.
- **`operador`** (`scripts/operador.py`): o único com o socket do Docker. Faz uma lista fixa de
  coisas (veja o topo do arquivo); campos do `.env` só os de `stack/envfile.py`. Começa como root
  só para descobrir o grupo do socket e roda como `PUID:PGID` + esse grupo (no Docker Desktop, onde
  o grupo não escreve no socket, fica root). Liga pelo perfil `painel` do compose, que o `setup.sh`
  põe em `COMPOSE_PROFILES` (a não ser com `PAINEL_MANUTENCAO=off`).
- **Tarefas** rodam num container avulso (`docker run`, fora do compose) com a imagem do operador,
  a pasta no mesmo caminho e `LOCADORA_PELO_PAINEL=1`. Fora do compose porque o `atualizar.sh` para
  e recria os serviços do projeto. A saída fica no container (`docker logs locadora-tarefa`) até a
  próxima tarefa. Com `LOCADORA_PELO_PAINEL=1`, o `setup.sh` não confere `/dev/net/tun` nem a GPU
  (mantém o que está no `.env`) e o `atualizar.sh` segue sem o `git pull` se ele falhar.
- **Login:** `STACK_USER`/`STACK_PASSWORD`. A sessão é um cookie assinado (`HttpOnly`,
  `SameSite=Strict`) com chave derivada de `PAINEL_SEGREDO` + senha: sobrevive ao painel ser
  recriado e cai quando a senha muda.
- **Pedidos que mudam algo** são `POST` com JSON e o cabeçalho `X-Locadora: 1` (contra CSRF).
- **No front:** todo texto vindo da API entra por `textContent`; a CSP não permite script inline.

Testar sem a stack: `python3 -m unittest tests.test_painel tests.test_operador`.
Com a stack: `docker compose up -d --build painel operador`.

## Adicionar um serviço

1. Acrescente o serviço no `docker-compose.yml` (porta via variável `*_PORT` no `.env.example`).
2. Crie `scripts/stack/<serviço>.py` com uma função que configura via API, seguindo as regras acima.
3. Chame a função em `scripts/configure.py`.
4. Inclua a porta na verificação de portas e no resumo final do `setup.sh`.
5. Documente em `docs/` e na tabela de serviços do README.

## Publicar uma versão

```bash
git tag v1.1.0 && git push origin v1.1.0     # o GitHub Actions gera e publica os pacotes
# ou, localmente:
scripts/release.sh v1.1.0                    # --local para só gerar em dist/
```

Os pacotes saem do conteúdo commitado (`git archive`), então `.env`, `vpn/`, `config/` e `data/`
nunca entram.
