"""Preferência por PT-BR: formatos personalizados e perfil 'PT-BR 1080p'."""
import json

from .common import Client, KEYS, RADARR, log, set_field


CF_NAME = "Português (BR)"
CF_SCORE = 100
# Só marcas de ÁUDIO em português. "PT-BR", "Brazilian" e "Portuguese" soltos ficam de fora:
# aparecem em versões legendadas ("Legendado PT-BR", "PT-BR.SUBS"), que têm o áudio original.
_SEP = r"[ ._-]?"
_DUB = r"dub(s|bed)?"
PT_TITLE = (r"\b(dublado|dublagem|nacional"
            rf"|brasil{_SEP}{_DUB}|br[ ._-]({_DUB}|audio)"
            rf"|pt{_SEP}br{_SEP}({_DUB}|audio)|({_DUB}|audio){_SEP}pt{_SEP}br"
            rf"|(brazilian|portuguese|portugu[eê]s){_SEP}({_DUB}|audio)"
            # "Dub" sozinho conta, menos quando é dublagem em inglês/japonês ("English Dub", anime)
            rf"|(?<!english[ ._-])(?<!eng[ ._-])(?<!japanese[ ._-]){_DUB}(?![ ._-]?(english|eng|japanese|jap)\b)"
            r")\b")
# Etiqueta de faixas de áudio de alguns indexadores: "[audio-[EN+PT]]"
AUDIO_TAG = r"\[audio-\[[^\]]*\bPT(-?BR)?\b"
DUAL_TITLE = (r"^(?!.*\b(hindi|tamil|telugu|kannada|malayalam|latino|spanish|espa[nñ]ol|castellano|"
              r"russian|rus|ita|italian|french|vff|vostfr|ger|german|korean|kor|chinese|chi|japanese|jap|"
              r"turko?|turkish|tur|pol|polish|cze|czech|hun|ukr|arabic|ara|nordic|swe|nor|dan|fin)\b)"
              r".*\bdual\b")


RES_CF = "1080p"
FOREIGN_CF = "Dublagem estrangeira"
FOREIGN_SCORE = -50
DUB_ONLY_CF = "Só dublado"
# "Dublado" sem "Dual" nem etiqueta de faixas: só o áudio em português, sem o original.
# "Nacional" fica de fora: num filme brasileiro, é o próprio áudio original.
DUB_ONLY = r"\b(dublado|dublagem)\b"
PROFILE = "PT-BR 1080p"
ORIG_PROFILE = "Original + legenda 1080p"
OUR_PROFILES = (PROFILE, ORIG_PROFILE)
HD_GROUP = {"HDTV-720p", "WEBDL-720p", "WEBRip-720p", "Bluray-720p",
            "HDTV-1080p", "WEBDL-1080p", "WEBRip-1080p", "Bluray-1080p"}


def ensure_profile(c, v, langs, name, scores, cutoff_score):
    """720p+1080p num grupo só: a qualidade empata e os formatos decidem. Sem REMUX/4K.
    Mínimo 0: formato com pontuação negativa (dublagem estrangeira...) é recusado."""
    schema = c.get(f"{v}/qualityprofile/schema")
    flat = []
    for it in schema["items"]:
        flat += [x["quality"] for x in it["items"]] if it.get("items") else [it["quality"]]
    items, group = [], {"id": 1001, "name": "HD (720p/1080p)", "allowed": True, "items": []}
    for q in flat:
        if q["name"] in HD_GROUP:
            if not group["items"]:
                items.append(group)
            group["items"].append({"quality": q, "items": [], "allowed": True})
        else:
            items.append({"quality": q, "items": [], "allowed": False})
    body = {**schema, "name": name, "upgradeAllowed": True, "cutoff": 1001,
            "minFormatScore": 0, "cutoffFormatScore": cutoff_score, "minUpgradeFormatScore": 1,
            "items": items,
            "formatItems": [{**f, "score": scores.get(f["format"], 0)} for f in schema["formatItems"]]}
    if "language" in schema:
        body["language"] = {"id": langs.get("Any", -1), "name": "Any"}
    existing = next((p for p in c.get(f"{v}/qualityprofile") if p["name"] == name), None)
    if existing:
        c.put(f"{v}/qualityprofile/{existing['id']}", {**body, "id": existing["id"]})
        return existing["id"]
    log(f"perfil '{name}' criado")
    return c.post(f"{v}/qualityprofile", body)["id"]


def ensure_cf(c, v, name, specs):
    """Cria o formato ou atualiza se as regras mudaram."""
    def key(specs):
        return sorted((s["name"], json.dumps(s["fields"][0]["value"]), s["negate"], s["required"])
                      for s in specs)
    cf = next((f for f in c.get(f"{v}/customformat") if f["name"] == name), None)
    body = {"name": name, "includeCustomFormatWhenRenaming": False, "specifications": specs}
    if not cf:
        log(f"formato '{name}' criado")
        return c.post(f"{v}/customformat", body)
    if key(cf["specifications"]) != key(specs):
        log(f"formato '{name}' atualizado")
        return c.put(f"{v}/customformat/{cf['id']}", {**body, "id": cf["id"]})
    return cf


def prefer_ptbr(name, base):
    c = Client(base, {"X-Api-Key": KEYS[name]})
    v = "/api/v3"
    langs = {l["name"]: l["id"] for l in c.get(f"{v}/language")}

    # Só regras de título: o Radarr/Sonarr exige que um item de CADA tipo combine,
    # e a detecção de idioma deles falha em PT-BR/NACIONAL/DUAL.
    schema = {s["implementation"]: s for s in c.get(f"{v}/customformat/schema")}

    def spec(label, value, negate=False, required=False, kind="ReleaseTitleSpecification", **extra):
        s = json.loads(json.dumps(schema[kind]))
        s.update(name=label, negate=negate, required=required)
        set_field(s["fields"], "value", value)
        for k, val in extra.items():
            set_field(s["fields"], k, val)
        return s

    cf = ensure_cf(c, v, CF_NAME, [spec("Título dublado/PT-BR", PT_TITLE), spec("Título DUAL", DUAL_TITLE),
                                   spec("Faixa de áudio PT", AUDIO_TAG)])
    # Bônus pequeno pra 1080p: desempata dentro do grupo HD sem superar o idioma
    res = ensure_cf(c, v, RES_CF, [spec("1080p", 1080, required=True, kind="ResolutionSpecification")])
    # Penaliza áudio que não é nem o idioma original nem português (ex.: "Ita Eng" num filme americano)
    lang = "LanguageSpecification"
    foreign = ensure_cf(c, v, FOREIGN_CF, [
        spec("Tem idioma além do original", -2, required=True, kind=lang, exceptLanguage=True),
        spec("Não é PT-BR", langs["Portuguese (Brazil)"], negate=True, required=True, kind=lang,
             exceptLanguage=False),
        spec("Não é PT", langs["Portuguese"], negate=True, required=True, kind=lang, exceptLanguage=False),
    ])
    # Só áudio em português (sem o original): o perfil "Original + legenda" recusa
    dub_only = ensure_cf(c, v, DUB_ONLY_CF, [
        spec("Título dublado", DUB_ONLY, required=True),
        spec("Não é DUAL", r"\bdual\b", negate=True, required=True),
        spec("Sem etiqueta de faixas", AUDIO_TAG, negate=True, required=True),
    ])

    # PT-BR 1080p (110) > PT-BR 720p (100) > original 1080p (10) > original 720p (0)
    pid = ensure_profile(c, v, langs, PROFILE,
                         {cf["id"]: CF_SCORE, res["id"]: 10, foreign["id"]: FOREIGN_SCORE},
                         CF_SCORE + 10)
    # Original 1080p (10) > original 720p (0); dublado sem o original e dublagem estrangeira: recusados
    ensure_profile(c, v, langs, ORIG_PROFILE,
                   {res["id"]: 10, foreign["id"]: FOREIGN_SCORE, dub_only["id"]: FOREIGN_SCORE}, 10)

    # Itens em perfis que não são da Locadora passam pro PT-BR; quem escolheu um dos nossos fica
    ours = {p["id"] for p in c.get(f"{v}/qualityprofile") if p["name"] in OUR_PROFILES}
    kind = "movie" if c.base == RADARR else "series"
    ids = [m["id"] for m in c.get(f"{v}/{kind}") if m["qualityProfileId"] not in ours]
    if ids:
        c.put(f"{v}/{kind}/editor", {f"{kind}Ids": ids, "qualityProfileId": pid})
        log(f"{len(ids)} item(ns) já pedidos movidos pro perfil '{PROFILE}'")

    changed = 0
    for p in c.get(f"{v}/qualityprofile"):
        if p["name"] in OUR_PROFILES:
            continue
        before = json.dumps(p, sort_keys=True)
        for item in p["formatItems"]:
            if item["format"] == cf["id"]:
                item["score"] = CF_SCORE
        p.update(upgradeAllowed=True, minFormatScore=0, cutoffFormatScore=CF_SCORE)
        if "language" in p:  # Radarr: "Original" recusaria versões dubladas
            p["language"] = {"id": langs.get("Any", -1), "name": "Any"}
        if json.dumps(p, sort_keys=True) != before:
            c.put(f"{v}/qualityprofile/{p['id']}", p)
            changed += 1
    if changed:
        log(f"{changed} perfis de qualidade preferem PT-BR (+{CF_SCORE}) e fazem upgrade pra ele")
