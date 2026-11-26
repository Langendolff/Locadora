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
│       ├── diagnostico.py   #   verificações por API do ./diagnostico.sh
│       ├── pessoas.py       #   usado por pessoas.sh
│       ├── telegram.py      #   bot de pedidos
│       ├── youtube.py       #   /youtube do bot: escolhe episódios, baixa e importa no Sonarr
│       ├── limpeza.py       #   regra e remoção da limpeza automática
│       ├── importar.py      #   usado por importar.sh
│       └── passwd.py        #   usado por change-password.sh
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
