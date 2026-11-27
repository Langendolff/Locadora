"""O .env visto pelo painel: quais campos podem ser mudados, como validar e como gravar.

Só a parte "você preenche" do .env.example entra aqui. Ficam de fora, de propósito:
  STACK_USER         trocar o usuário não é suportado pelo setup.sh
  STACK_PASSWORD     tem fluxo próprio (./change-password.sh troca em todos os serviços)
  o resto            chaves e valores que o setup.sh gera sozinho

DATA_ROOT (onde ficam filmes e séries) entra, mas mudar não move nada: o operador confere que a pasta
nova existe no servidor e o painel avisa para mover media/ e torrents/ antes de aplicar.

Gravação igual ao set_env do setup.sh: KEY='valor', no lugar da linha existente ou no fim.
"""
import re

GRUPOS = [
    ("conta", "Conta"),
    ("disco", "Filmes e séries"),
    ("legendas", "Legendas"),
    ("telegram", "Telegram"),
    ("remoto", "Fora de casa (Tailscale)"),
    ("limpeza", "Limpeza automática"),
    ("portas", "Portas"),
]

# chave, grupo, rótulo, tipo (texto|segredo|numero|porta|chat|email|pasta), ajuda
CAMPOS = [
    ("STACK_EMAIL", "conta", "E-mail do admin no Seerr", "email", ""),
    ("DATA_ROOT", "disco", "Pasta no servidor", "pasta",
     "Caminho completo no servidor, ex.: /mnt/hd/locadora. Dentro dela ficam media/ (a biblioteca) e "
     "torrents/ (downloads), no mesmo disco. Mudar não move nada: mova as duas pastas antes de aplicar"),
    ("OPENSUBTITLES_USER", "legendas", "OpenSubtitles: usuário", "texto", "Conta grátis em opensubtitles.com (recomendado)"),
    ("OPENSUBTITLES_PASSWORD", "legendas", "OpenSubtitles: senha", "segredo", ""),
    ("SUBDL_API_KEY", "legendas", "SubDL: chave da API", "segredo", "Conta grátis em subdl.com, chave no painel deles"),
    ("LEGENDASNET_USER", "legendas", "Legendas.net: usuário", "texto", "Conta grátis em legendas.net"),
    ("LEGENDASNET_PASSWORD", "legendas", "Legendas.net: senha", "segredo", ""),
    ("TELEGRAM_BOT_TOKEN", "telegram", "Token do bot", "segredo", "No Telegram: @BotFather → /newbot → copie o token"),
    ("TELEGRAM_CHAT_ID", "telegram", "Chat dos avisos gerais", "chat",
     "Opcional. Número do chat (ou grupo da família) que recebe tudo que fica pronto, falhas e a limpeza"),
    ("TS_AUTHKEY", "remoto", "Chave de autenticação", "segredo",
     "tailscale.com → Settings → Keys → Generate auth key (deixe Reusable desligado). Vazio = desligado"),
    ("LIMPEZA_DIAS", "limpeza", "Dias depois de todo mundo ver", "numero",
     "Filmes que todo mundo viu há este tanto de dias saem sozinhos (favoritos ficam). Vazio = desligada"),
    ("JELLYFIN_PORT", "portas", "Jellyfin", "porta", ""),
    ("SEERR_PORT", "portas", "Seerr", "porta", ""),
    ("RADARR_PORT", "portas", "Radarr", "porta", ""),
    ("SONARR_PORT", "portas", "Sonarr", "porta", ""),
    ("PROWLARR_PORT", "portas", "Prowlarr", "porta", ""),
    ("DELUGE_PORT", "portas", "Deluge", "porta", ""),
    ("BAZARR_PORT", "portas", "Bazarr", "porta", ""),
    ("PAINEL_PORT", "portas", "Painel", "porta", "Mudou? O endereço deste painel muda junto"),
]
TIPO = {c[0]: c[3] for c in CAMPOS}
# O que o docker-compose.yml usa quando a porta não está no .env (instalação de antes da variável)
PORTA_PADRAO = {"JELLYFIN_PORT": "8096", "SEERR_PORT": "5055", "RADARR_PORT": "7878", "SONARR_PORT": "8989",
                "PROWLARR_PORT": "9696", "DELUGE_PORT": "8112", "BAZARR_PORT": "6767", "PAINEL_PORT": "8585"}
_LINHA = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")


def ler(caminho):
    """{CHAVE: valor} como o get_env do setup.sh: a última linha vale, sem as aspas das pontas."""
    vals = {}
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            m = _LINHA.match(linha.rstrip("\n"))
            if m:
                v = m.group(2)
                if v[:1] in ("'", '"'):
                    v = v[1:]
                if v[-1:] in ("'", '"'):
                    v = v[:-1]
                vals[m.group(1)] = v
    return vals


def para_painel(vals):
    """Campos para o formulário. Segredos não saem daqui: só se estão preenchidos ou não."""
    out = []
    for chave, grupo, rotulo, tipo, ajuda in CAMPOS:
        v = vals.get(chave, "") or PORTA_PADRAO.get(chave, "")
        item = {"chave": chave, "grupo": grupo, "rotulo": rotulo, "tipo": tipo, "ajuda": ajuda}
        if tipo == "segredo":
            item["definido"] = bool(v)
        else:
            item["valor"] = v
        out.append(item)
    return {"grupos": [{"id": g, "nome": n} for g, n in GRUPOS], "campos": out}


def validar(novos, atuais):
    """Confere {CHAVE: valor} vindo do painel. Devolve o dicionário limpo ou levanta ValueError."""
    if not isinstance(novos, dict):
        raise ValueError("formato inválido")
    limpo = {}
    for chave, v in novos.items():
        if chave not in TIPO:
            raise ValueError(f"{chave} não pode ser mudado pelo painel")
        if not isinstance(v, str):
            raise ValueError(f"{chave}: valor inválido")
        v = v.strip()
        if "'" in v or any(ord(c) < 32 for c in v):
            raise ValueError(f"{chave}: não use aspas simples (') nem quebras de linha")
        if len(v) > 500:
            raise ValueError(f"{chave}: longo demais")
        tipo = TIPO[chave]
        if tipo == "porta":
            if not v.isdigit() or not 1024 <= int(v) <= 65535:
                raise ValueError(f"{chave}: porta entre 1024 e 65535")
        elif tipo == "numero" and v:
            if not v.isdigit() or not 1 <= int(v) <= 3650:
                raise ValueError(f"{chave}: número de dias entre 1 e 3650 (ou vazio)")
        elif tipo == "chat" and v and not re.fullmatch(r"-?\d{1,20}", v):
            raise ValueError(f"{chave}: só números (grupos começam com -)")
        elif tipo == "pasta":
            if not v.startswith(("/", "./")):
                raise ValueError(f"{chave}: use o caminho completo, começando com / (ex.: /mnt/hd/locadora)")
            if ":" in v or "\\" in v or ".." in v.split("/"):
                raise ValueError(f"{chave}: caminho inválido (sem :, \\ nem ..)")
            if v.rstrip("/") in ("", "."):
                raise ValueError(f"{chave}: escolha uma pasta, não a raiz")
            v = v.rstrip("/")
        elif tipo == "email" and v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError(f"{chave}: e-mail inválido")
        limpo[chave] = v
    portas = {}
    for chave, tipo in TIPO.items():
        if tipo == "porta":
            p = limpo.get(chave, atuais.get(chave) or PORTA_PADRAO[chave])
            if p and p in portas:
                raise ValueError(f"{chave} e {portas[p]} usam a mesma porta ({p})")
            portas[p] = chave
    return limpo


def gravar(caminho, mudancas):
    """Aplica {CHAVE: valor} no .env. Devolve as chaves que de fato mudaram."""
    atuais = ler(caminho)
    mudou = [k for k, v in mudancas.items() if atuais.get(k, "") != v]
    if not mudou:
        return []
    with open(caminho, encoding="utf-8") as f:
        linhas = f.read().splitlines()
    faltando = set(mudou)
    for i, linha in enumerate(linhas):
        m = _LINHA.match(linha)
        if m and m.group(1) in faltando:
            linhas[i] = f"{m.group(1)}='{mudancas[m.group(1)]}'"
    presentes = {m.group(1) for m in map(_LINHA.match, linhas) if m}
    linhas += [f"{k}='{mudancas[k]}'" for k in mudou if k not in presentes]
    # Escreve no mesmo arquivo (não troca por outro): mantém dono e permissão 600
    with open(caminho, "r+", encoding="utf-8") as f:
        f.seek(0)
        f.write("\n".join(linhas) + "\n")
        f.truncate()
    return mudou


def remover(caminho, chave):
    """Tira uma linha CHAVE=... do .env (usado para a senha temporária do change-password.sh)."""
    with open(caminho, encoding="utf-8") as f:
        linhas = [l for l in f.read().splitlines() if not l.startswith(chave + "=")]
    with open(caminho, "r+", encoding="utf-8") as f:
        f.seek(0)
        f.write("\n".join(linhas) + "\n")
        f.truncate()

