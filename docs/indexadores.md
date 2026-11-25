# Indexadores

Indexadores são os sites onde o Prowlarr procura os lançamentos. A Locadora **não vem com
indexadores**: cada instalação escolhe os seus. O que você escolher é sincronizado sozinho com o
Radarr e o Sonarr.

> Use só fontes que você tem o direito de usar. A responsabilidade pelo que é baixado é de quem usa.

## Pela interface (mais fácil)

1. Abra o Prowlarr (http://localhost:9696) → **Indexers** → **Add Indexer**.
2. Filtre por **idioma** (ex.: `pt-BR`) e por **tipo** (público ou privado) e escolha.
3. Se o site estiver atrás do Cloudflare, coloque a tag **`flare`** no indexador: o acesso passa
   pelo FlareSolverr, que a Locadora já configura.
4. **Test** → **Save**. Em poucos minutos ele aparece no Radarr e no Sonarr.

Para conteúdo dublado, prefira indexadores com foco em lançamentos brasileiros: a preferência por
PT-BR só funciona se as versões dubladas aparecerem nas buscas.

## Pelo arquivo (para reinstalar igual)

Indexadores listados em `indexers/public.txt` são adicionados pelo `./setup.sh` em toda instalação:

```bash
cp indexers/public.example.txt indexers/public.txt
```

Um por linha, com o `definitionName` do Prowlarr (o nome que aparece na URL ao abrir a definição
do indexador, ou em `Definitions` dentro de `config/prowlarr/`), e `flare` se precisar:

```
nome-do-indexador            # comentário
outro-indexador      flare
```

Depois: `./setup.sh`. O `indexers/public.txt` fica fora do git.

**Definição customizada (`.yml` do Cardigann):** coloque o arquivo em `indexers/` e rode:

```bash
docker compose restart prowlarr && ./setup.sh
```

## Contagem de seeds

A contagem de seeds mostrada pelos sites costuma estar desatualizada. Um lançamento com
"24 seeds" pode estar morto. Veja [Download parado em 0%](solucao-de-problemas.md#download-parado-em-0).
