# Idioma e legendas

O padrão da casa: **dublado em português; se não houver, idioma original com legenda pt-BR.**
Cada pessoa pode escolher diferente (veja [Preferência de cada pessoa](#preferência-de-cada-pessoa)).

## Preferência de cada pessoa

```bash
./pessoas.sh                                  # lista as pessoas e o que cada uma prefere
./pessoas.sh nova Ana                         # cadastra (pergunta senha, áudio e legenda)
./pessoas.sh preferencia Ana original en      # muda: áudio original, legenda em inglês
```

| Escolha | Opções |
|---|---|
| Áudio | `dublado` (PT-BR quando existir, padrão) ou `original` |
| Legenda | `pt-br` (padrão), `en` ou `nenhuma` |

A escolha vale em três lugares:

- **Pedidos (Seerr):** quem escolheu `original` pede no perfil **Original + legenda 1080p**, que
  aceita só versões com o áudio original (DUAL serve; "Dublado" sem o original é recusado). A
  Locadora cria uma regra do Seerr para essa pessoa (Configurações → Serviços → Radarr/Sonarr →
  Regras de substituição).
- **Reprodução (Jellyfin):** `dublado` escolhe a faixa em português e liga a legenda só quando o
  áudio não é português. `original` toca a faixa padrão do arquivo e deixa a legenda sempre ligada.
  `nenhuma` mostra só legendas forçadas (falas em outra língua).
- **Legendas baixadas (Bazarr):** pt-BR sempre; inglês também, se alguém escolheu `en`.

Quem é cadastrado pelo `./pessoas.sh` já entra no Seerr podendo pedir, com aprovação automática.
Pessoas criadas direto no Jellyfin seguem o padrão da casa até alguém rodar `./pessoas.sh preferencia`.

> Um filme é baixado uma vez para a casa toda: vale o perfil de quem pediu. Se outra pessoa
> quiser a outra versão, no Radarr: abra o filme → editar → troque o perfil.
> Num DUAL, quem prefere o original pode precisar trocar a faixa de áudio no player, se o
> arquivo vier com o português como faixa padrão.

## Escolha do áudio (Radarr/Sonarr)

Os pedidos usam o perfil **PT-BR 1080p**. Nele, 720p e 1080p ficam no mesmo grupo de qualidade,
então quem decide é a pontuação de idioma:

| Versão | Pontos |
|---|---|
| PT-BR (DUBLADO, DUAL, NACIONAL, Dub PT-BR, `[audio-[EN+PT]]`) em 1080p | 110 |
| PT-BR em 720p | 100 |
| Idioma original em 1080p | 10 |
| Idioma original em 720p | 0 |
| Dublagem estrangeira (ex.: "Ita Eng" num filme americano) | −50 → **recusada** |

- Sem versão em PT-BR, baixa no idioma original e **troca sozinho** quando a dublada aparecer.
- "DUAL" com outro idioma no nome (hindi, latino, turco…) não conta como português.
- **Legendado não conta como dublado.** "PT-BR", "Brazilian" ou "Portuguese" sozinhos no nome
  (ex.: "Legendado PT-BR", "PT-BR.SUBS") indicam legenda, não áudio, e ficam no idioma original.
- "Dub" sozinho conta como português, menos em "English Dub" / "Japanese Dub" (comum em anime).
- REPACK/PROPER **não** passam na frente do idioma (`downloadPropersAndRepacks = doNotPrefer`).
- REMUX e 4K ficam de fora (arquivos de 40–80 GB).

Os formatos são criados por `scripts/stack/language.py`:

| Formato | Regra |
|---|---|
| `Português (BR)` | título com marca de **áudio** em português: `dublado`, `dublagem`, `nacional`, `dub`, `pt-br dub`, `audio pt-br`, `brazilian dubbed`… (`PT_TITLE`); `dual` sem outro idioma (`DUAL_TITLE`); ou etiqueta de faixa `[audio-[…PT…]]` (`AUDIO_TAG`) |
| `Dublagem estrangeira` | tem idioma além do original **e** não é português |
| `1080p` | resolução 1080p (desempate) |
| `Só dublado` | "dublado" sem "dual" nem etiqueta de faixas: recusado no perfil Original (−50) |

## Legendas (Bazarr)

- Baixa legenda **pt-BR só quando o áudio não é português** (`audio_exclude` no perfil).
- Legenda em **inglês** também, se alguma pessoa escolheu `en` (e só quando o áudio não é inglês).
- **Sincroniza** toda legenda baixada com o áudio do arquivo (ffsubsync), o que corrige
  atrasos de dezenas de segundos entre versões diferentes do mesmo filme.
- Provedores sem conta: legendas embutidas no arquivo, YIFY Subtitles, Subf2m.
- Provedores com conta grátis (configure no `.env`): **OpenSubtitles** (o maior acervo), SubDL e
  Legendas.net. Com eles, a chance de achar uma legenda feita para o arquivo exato sobe muito.

> A sincronização corrige deslocamento fixo. Se a legenda foi feita para um corte diferente do
> filme (cenas a mais ou a menos), algum trecho ainda pode ficar fora. Nesse caso, no Bazarr,
> abra o filme e escolha outra legenda na busca manual.

## Reprodução (Jellyfin)

O usuário admin vem configurado com o padrão da casa:

- **Áudio preferido:** português
- **Legenda preferida:** português, no modo **Inteligente**: liga sozinha quando o áudio não é português

Outras pessoas: `./pessoas.sh` (acima). Também dá para ajustar à mão em **Configurações →
Reprodução** e **Legendas** no Jellyfin, mas isso não muda os pedidos nem as legendas baixadas.

## Tema

O Jellyfin vem com o tema **Locadora** (grafite, vermelho e a faixa de "fita" no topo), o logo
no lugar do original, favicon e nome "Locadora" na aba do navegador.

- Cores e estilos: `assets/jellyfin/locadora.css`, aplicado como "CSS personalizado" pelo `./setup.sh`.
  Depois de editar o arquivo, rode `./setup.sh` (ou `docker compose run --rm setup`).
- Logo e ícones: trocados a cada partida do container por `scripts/jellyfin-branding.sh`.
