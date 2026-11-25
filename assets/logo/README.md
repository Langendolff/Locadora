# Marca Locadora

<p>
  <img src="locadora-symbol.svg" width="96" alt="Símbolo">
  &nbsp;&nbsp;
  <img src="icons/locadora-app-icon.svg" width="96" alt="Ícone de app">
</p>

**Ideia:** o botão de play formado por três camadas, que são as fitas empilhadas na prateleira
da locadora e também os serviços empilhados da stack. Vários serviços viram um só player.

## Arquivos

| Arquivo | Uso |
|---|---|
| `locadora-horizontal.svg` / `-dark.svg` | Logo principal, para fundo claro / escuro |
| `locadora-stacked.svg` / `-dark.svg` | Versão empilhada (espaços estreitos, capas) |
| `locadora-symbol.svg` | Só o símbolo |
| `locadora-symbol-small.svg` | Símbolo desenhado para **menos de 48 px** (vãos maiores) |
| `*-black.svg` / `*-white.svg` | Uma cor (impressão, carimbo, marca d'água) |
| `locadora-wordmark.svg` | Só o nome |
| `icons/` | favicon (`.ico`, `.svg`, PNGs), ícone de app, `site.webmanifest` e `head-snippet.html` |

Todos os SVGs são formas puras: sem texto vivo nem dependência de fonte.

## Cores

| Nome | HEX | RGB | Uso |
|---|---|---|---|
| Vermelho Locadora | `#E5422B` | 229, 66, 43 | Símbolo |
| Grafite | `#16181D` | 22, 24, 29 | Nome em fundo claro, fundo do ícone |
| Branco | `#FFFFFF` | 255, 255, 255 | Nome em fundo escuro |

## Tipografia

Nome em **Inter Display Bold** (licença SIL OFL), convertida em contornos, com espaçamento
levemente fechado (−1,2%). Para textos de apoio, use Inter.

## Regras

- **Área de respiro:** ao redor do logo, deixe no mínimo a altura de uma camada do símbolo.
- **Tamanho mínimo:** logo horizontal com 100 px de largura; símbolo com 16 px (use a versão `small` abaixo de 48 px).
- **Não faça:** mudar as cores do símbolo, distorcer, girar, adicionar sombra ou degradê, separar
  as camadas de outro jeito, ou recompor o nome com outra fonte.

## Regenerar

`build.py` gera símbolo, nome e lockups a partir da geometria e da fonte Inter:

```bash
docker run --rm -v /caminho/para/fontes/inter:/fonts:ro -v "$PWD/build.py:/build.py:ro" \
  -v "$PWD:/out" python:3.13-alpine sh -c 'pip -q install fonttools uharfbuzz && python /build.py'
```
