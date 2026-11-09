"""Configuração do Planner: valores padrão, leitura e validação do config.json.

O config.json é criado pelo instalador (configurar.py). Tudo o que faltar nele
usa o padrão abaixo, que é o setup original da AfroCreator Tech.
"""
import copy
import json
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("PLANNER_CONFIG", BASE / "config.json"))

# Redes que o banco conhece (uma coluna de check por rede).
REDES_SUPORTADAS = {
    "instagram": ("Instagram", "IG"),
    "facebook": ("Facebook", "FB"),
    "youtube": ("YouTube", "YT"),
    "tiktok": ("TikTok", "TT"),
    "kwai": ("Kwai", "KW"),
}
# Onde cada tipo de post pode ser publicado (antes de filtrar pelas redes escolhidas).
REDES_POR_TIPO_BASE = {
    "reel": ("instagram", "facebook", "youtube", "tiktok", "kwai"),
    "longo": ("youtube", "facebook"),
    "carrossel": ("instagram",),
    "animacao": ("tiktok", "youtube", "kwai"),
}
NOMES_TIPO = {"reel": "Reel", "longo": "Vídeo longo", "carrossel": "Carrossel", "animacao": "Animação"}
TIPOS_ROTEIRO = ("reel", "longo")
REDES_METRICAS_SUPORTADAS = ("instagram", "youtube", "tiktok")
VISOES = ("roteiros", "posts", "metricas")
COLUNAS_ETAPA = ("rosto", "tela", "edicao")  # até 3 etapas, guardadas nessas colunas

TEMAS = {
    "afrocreator": {"principal": "#0DF6FE", "secundaria": "#3068F8", "destaque": "#E39A22",
                    "fundo": "#0E2237", "fundo_escuro": "#0F111C", "texto": "#E4FEFF", "sucesso": "#2EE59D"},
    "roxo-neon": {"principal": "#B66DFF", "secundaria": "#5B3BFF", "destaque": "#FF4FA3",
                  "fundo": "#1A1030", "fundo_escuro": "#0D0818", "texto": "#F3EAFF", "sucesso": "#3DF5A8"},
    "verde-gamer": {"principal": "#39FF88", "secundaria": "#00B3FF", "destaque": "#FFC83D",
                    "fundo": "#0F1F17", "fundo_escuro": "#08110C", "texto": "#E8FFF1", "sucesso": "#39FF88"},
    "vermelho-live": {"principal": "#FF4D5E", "secundaria": "#FF8A3D", "destaque": "#FFD23F",
                      "fundo": "#24121A", "fundo_escuro": "#12080C", "texto": "#FFEFF1", "sucesso": "#3DF5A8"},
}

PADRAO = {
    "versao": 1,
    "marca": {"nome": "AfroCreator Tech", "subtitulo": "planner"},
    "tema": "afrocreator",
    "cores": TEMAS["afrocreator"],
    "fontes": "marca",
    "redes": list(REDES_SUPORTADAS),
    "tipos_roteiro": ["reel", "longo"],
    "tipos_post": ["reel", "longo", "carrossel", "animacao"],
    "etapas": ["Gravação rosto", "Gravação tela", "Edição"],
    "faixas": ["Reel 1: atração", "Reel 2: educação", "Reel 3: autoridade"],
    "visao_inicial": "roteiros",
    "metricas": {
        "ativo": True,
        "redes": ["instagram", "youtube", "tiktok"],
        "meta": {"rede": "instagram", "seguidores": 100000, "data": "2027-12-31"},
        "youtube_handle": "",
    },
    "agentes": {
        "ativo": False,
        "registro_aprovacoes": "~/AfroCreator Tech/00-Painel/aprovacoes.json",
        "agente_legenda": "diretor",
        "comando": ["openclaw"],
    },
    "servidor": {"host": "127.0.0.1", "porta": 8765},
}

HEX = re.compile(r"#[0-9A-Fa-f]{6}")


class ConfigInvalida(Exception):
    pass


def _mesclar(base, novo):
    saida = copy.deepcopy(base)
    for k, v in (novo or {}).items():
        if isinstance(v, dict) and isinstance(saida.get(k), dict) and k != "cores":
            saida[k] = _mesclar(saida[k], v)
        else:
            saida[k] = copy.deepcopy(v)
    return saida


def validar(c):
    """Confere a configuração e devolve uma versão normalizada. Erros viram ConfigInvalida."""
    erros = []

    def lista(chave, permitidos, minimo=1):
        v = c.get(chave)
        if not isinstance(v, list) or any(x not in permitidos for x in v) or len(v) < minimo:
            erros.append(f"'{chave}' deve ser uma lista com itens de: {', '.join(permitidos)}")
            return list(PADRAO[chave])
        return [x for x in permitidos if x in v]  # ordem estável, sem repetidos

    nome = c["marca"].get("nome")
    if not isinstance(nome, str) or not nome.strip() or len(nome) > 40:
        erros.append("'marca.nome' deve ter de 1 a 40 caracteres")
    sub = c["marca"].get("subtitulo", "")
    if not isinstance(sub, str) or len(sub) > 30:
        erros.append("'marca.subtitulo' deve ter até 30 caracteres")

    cores = c.get("cores") or {}
    base = TEMAS.get(c.get("tema"), TEMAS["afrocreator"])
    cores = {k: cores.get(k, base[k]) for k in base}
    for k, v in cores.items():
        if not isinstance(v, str) or not HEX.fullmatch(v):
            erros.append(f"cor '{k}' deve estar no formato #RRGGBB")
    c["cores"] = cores
    if c.get("fontes") not in ("marca", "sistema"):
        erros.append("'fontes' deve ser 'marca' ou 'sistema'")

    c["redes"] = lista("redes", tuple(REDES_SUPORTADAS))
    c["tipos_roteiro"] = lista("tipos_roteiro", TIPOS_ROTEIRO)
    c["tipos_post"] = [t for t in lista("tipos_post", tuple(REDES_POR_TIPO_BASE))
                       if any(r in c["redes"] for r in REDES_POR_TIPO_BASE[t])]
    if not c["tipos_post"]:
        erros.append("nenhum tipo de post combina com as redes escolhidas")

    etapas = c.get("etapas")
    if not isinstance(etapas, list) or not 1 <= len(etapas) <= 3 or \
            any(not isinstance(e, str) or not e.strip() or len(e) > 30 for e in etapas):
        erros.append("'etapas' deve ter de 1 a 3 nomes (até 30 caracteres cada)")
    faixas = c.get("faixas")
    if not isinstance(faixas, list) or len(faixas) > 3 or \
            any(not isinstance(f, str) or not f.strip() or len(f) > 40 for f in faixas):
        erros.append("'faixas' deve ter de 0 a 3 nomes (até 40 caracteres cada)")

    if c.get("visao_inicial") not in VISOES:
        erros.append(f"'visao_inicial' deve ser: {', '.join(VISOES)}")

    m = c["metricas"]
    if not isinstance(m.get("ativo"), bool):
        erros.append("'metricas.ativo' deve ser true ou false")
    if not isinstance(m.get("redes"), list) or any(r not in REDES_METRICAS_SUPORTADAS for r in m["redes"]):
        erros.append("'metricas.redes' aceita: instagram, youtube, tiktok")
    else:
        m["redes"] = [r for r in REDES_METRICAS_SUPORTADAS if r in m["redes"]]
        if m["ativo"] and not m["redes"]:
            erros.append("métricas ligadas precisam de pelo menos uma rede")
    meta = m.get("meta")
    if meta is not None:
        if not isinstance(meta, dict) or meta.get("rede") not in m.get("redes", []) \
                or not isinstance(meta.get("seguidores"), int) or meta["seguidores"] < 1 \
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta.get("data", ""))):
            erros.append("'metricas.meta' precisa de rede (uma das redes de métricas), seguidores (> 0) e data AAAA-MM-DD; ou null")

    a = c["agentes"]
    if not isinstance(a.get("ativo"), bool):
        erros.append("'agentes.ativo' deve ser true ou false")
    if not isinstance(a.get("comando"), list) or not a["comando"] or any(not isinstance(x, str) for x in a["comando"]):
        erros.append("'agentes.comando' deve ser uma lista, ex.: [\"openclaw\"]")
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", str(a.get("agente_legenda", ""))):
        erros.append("'agentes.agente_legenda' inválido")

    s = c["servidor"]
    if s.get("host") not in ("127.0.0.1", "0.0.0.0"):
        erros.append("'servidor.host' deve ser 127.0.0.1 (só este computador) ou 0.0.0.0 (rede de casa)")
    if not isinstance(s.get("porta"), int) or not 1024 <= s["porta"] <= 65535:
        erros.append("'servidor.porta' deve ser um número entre 1024 e 65535")

    if erros:
        raise ConfigInvalida("; ".join(erros))
    return c


def carregar(caminho=None):
    caminho = Path(caminho) if caminho else CONFIG_PATH
    bruto = {}
    if caminho.exists():
        try:
            bruto = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigInvalida(f"não consegui ler {caminho}: {e}")
        if not isinstance(bruto, dict):
            raise ConfigInvalida(f"{caminho} deve conter um objeto JSON")
    c = _mesclar(PADRAO, bruto)
    if "cores" not in bruto:
        c["cores"] = dict(TEMAS.get(c.get("tema"), TEMAS["afrocreator"]))
    return validar(c)


def redes_por_tipo(c):
    """Redes de cada tipo de post, já filtradas pelas redes que a pessoa usa."""
    return {t: [r for r in REDES_POR_TIPO_BASE[t] if r in c["redes"]] for t in c["tipos_post"]}


def publica(c):
    """O que o navegador precisa saber (sem caminhos nem comandos)."""
    return {
        "marca": c["marca"],
        "fontes": c["fontes"],
        "redes": {r: list(REDES_SUPORTADAS[r]) for r in c["redes"]},
        "redes_por_tipo": redes_por_tipo(c),
        "tipos": {"roteiros": [[t, NOMES_TIPO[t]] for t in c["tipos_roteiro"]],
                  "posts": [[t, NOMES_TIPO[t]] for t in c["tipos_post"]]},
        "etapas": [[COLUNAS_ETAPA[i], nome] for i, nome in enumerate(c["etapas"])],
        "faixas": {str(i + 1): nome for i, nome in enumerate(c["faixas"])},
        "visao_inicial": c["visao_inicial"],
        "metricas": {"ativo": c["metricas"]["ativo"], "redes": c["metricas"]["redes"]},
        "agentes": c["agentes"]["ativo"],
    }


def _mistura(hex1, hex2, peso):
    """Mistura duas cores (peso = quanto da primeira). Usado para derivar tons do tema."""
    a = [int(hex1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * peso + y * (1 - peso)):02X}" for x, y in zip(a, b))


def tema_css(c):
    k = c["cores"]
    linhas = [
        f"--ciano:{k['principal']}", f"--eletrico:{k['secundaria']}", f"--laranja:{k['destaque']}",
        f"--noite:{k['fundo']}", f"--profundo:{k['fundo_escuro']}", f"--gelo:{k['texto']}",
        f"--no-ar:{k['sucesso']}",
        f"--celula:{_mistura(k['fundo'], k['texto'], 0.94)}80",
        f"--linha:{_mistura(k['fundo'], k['texto'], 0.82)}",
        f"--apagado:{_mistura(k['fundo'], k['texto'], 0.74)}",
        f"--texto-2:{_mistura(k['texto'], k['fundo'], 0.62)}",
        f"--brilho-fundo:{_mistura(k['secundaria'], k['fundo'], 0.35)}",
    ]
    if c["fontes"] == "sistema":
        linhas += ['--f-titulo:system-ui,"Segoe UI",Roboto,sans-serif',
                   '--f-num:ui-monospace,"Cascadia Mono",Consolas,monospace',
                   '--f-texto:system-ui,"Segoe UI",Roboto,sans-serif']
    return ":root{" + ";".join(linhas) + "}\n"


if __name__ == "__main__":
    try:
        cfg = carregar(sys.argv[1] if len(sys.argv) > 1 else None)
    except ConfigInvalida as e:
        print(f"Configuração inválida: {e}")
        sys.exit(1)
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
