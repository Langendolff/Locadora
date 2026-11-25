# Importar filmes, Telegram, acesso de fora de casa e limpeza

## Importar os filmes que você já tem

```bash
./importar.sh ~/Videos/Movies --simular    # mostra como cada filme foi reconhecido
./importar.sh ~/Videos/Movies              # importa
```

- Um filme por pasta ou arquivo, de preferência com o nome **`Título (Ano)`**, em português ou no
  original (`Terra Fria (2005)`, `North.Country.2005.1080p.mkv`). "- Dublado" e "- Legendado" no
  nome são ignorados.
- Os originais **não são movidos nem apagados**. No mesmo disco da Locadora, a biblioteca usa
  hardlinks: não ocupa espaço extra. Em outro disco, os arquivos são copiados (ele pergunta antes).
- Filmes que já estão na Locadora ficam como estão; rodar de novo não duplica nada.
- Os importados entram **sem monitoramento**: o Radarr não sai baixando outra versão. Para ele
  trocar por uma dublada quando aparecer, no Radarr: abra o filme → ícone de marcador (monitorar).
- Não reconheceu algum? Renomeie a pasta para o título original e o ano e rode de novo.

Os três são opcionais e ligados pelo `.env`. Depois de mudar o `.env`, rode `./setup.sh`.

## Bot do Telegram

Cada pessoa da casa pede filmes e séries conversando com o bot, e recebe no Telegram o aviso
de quando o pedido fica pronto.

1. No Telegram, fale com **@BotFather** → `/newbot` → escolha um nome → copie o token.
2. No `.env`: `TELEGRAM_BOT_TOKEN='…'`. Opcional: `TELEGRAM_CHAT_ID` (o seu chat ou um grupo da
   família) para receber os avisos gerais: tudo que fica pronto, falha, e o que a limpeza vai tirar.
   Para descobrir o número: mande uma mensagem ao bot e abra
   `https://api.telegram.org/bot<TOKEN>/getUpdates`. É o `"chat":{"id": …}`.
3. `./setup.sh`

Cada pessoa abre a conversa com o bot e manda, uma vez:

```
/entrar usuario senha
```

com o mesmo login do Jellyfin (o bot apaga a mensagem na hora, para a senha não ficar no chat).
Depois é só mandar o nome do filme ou série e tocar no resultado.

| Comando | O que faz |
|---|---|
| nome de um filme/série | procura e mostra botões para pedir (✅ já tem, ⏳ já foi pedido) |
| `/pedidos` | os últimos pedidos da pessoa e como estão |
| `/sair` | desliga o Telegram da conta |

Os pedidos são feitos **em nome da pessoa**: valem a preferência de áudio do `./pessoas.sh`
(dublado ou original) e os avisos de "pronto" chegam só para ela. Quem nunca entrou no Seerr
entra pelo `/entrar` já podendo pedir, com aprovação automática.

O bot roda no serviço `tarefas` (`docker compose logs tarefas`).

## Assistir de fora de casa (Tailscale)

O Tailscale cria uma rede privada entre os seus aparelhos. Nada da Locadora fica aberto para a
internet: só celulares, TVs e notebooks logados na sua conta Tailscale enxergam o servidor.

1. Crie a conta em [tailscale.com](https://tailscale.com) (grátis para uso pessoal) e instale o
   app nos aparelhos que vão assistir.
2. No painel, em **DNS**: ligue **MagicDNS** e **HTTPS Certificates**.
3. Em **Settings → Keys → Generate auth key** (pode deixar "Reusable" desligado). Cole no
   `.env`: `TS_AUTHKEY='tskey-auth-…'`.
4. `./setup.sh`. No fim, ele mostra os endereços:

| | Endereço |
|---|---|
| Jellyfin | `https://locadora.<sua-rede>.ts.net` |
| Seerr | `https://locadora.<sua-rede>.ts.net:8443` |

No app do Jellyfin (celular/TV), use o endereço do Jellyfin como servidor. O primeiro acesso
pode demorar alguns segundos enquanto o certificado HTTPS é emitido.

A chave só é usada na primeira conexão; depois o login fica guardado em `config/tailscale/`.
Se apagar essa pasta, gere uma chave nova. Para desligar: apague `TS_AUTHKEY` do `.env`,
rode `docker compose rm -sf tailscale` e `./setup.sh`.

## Limpeza automática

Com `LIMPEZA_DIAS=30` no `.env`, todo dia às 4h saem os **filmes que todo mundo já viu há 30
dias ou mais**. A regra é feita para, na dúvida, manter:

- "todo mundo" = quem assistiu alguma coisa nos últimos 90 dias (contas paradas não seguram filme);
- **nunca sai**: favorito (❤️) de alguém no Jellyfin, filme que alguém começou e não terminou,
  filme que chegou há menos de 30 dias;
- séries não entram (episódios novos continuam chegando);
- com o Telegram ligado, avisa em `TELEGRAM_CHAT_ID` **3 dias antes** e depois de tirar.

Tirar = o Radarr apaga o arquivo e o torrent sai do Deluge (é isso que libera o espaço, por
causa dos hardlinks). O filme continua no catálogo do Seerr: para ver de novo, é só pedir.

```bash
./limpeza.sh          # mostra o que sairia hoje e o que sai em breve (não apaga nada)
./limpeza.sh agora    # roda agora
```
