#!/usr/bin/env python3
"""Integração com os agentes de IA (opcional; repositório afrocreator-agentes).

Leva para o planner tudo o que você aprovou no #aprovacao do Discord: lê o
registro da esteira de aprovação (aprovacoes.json), escolhe a data de cada item
pelo calendário dos agentes e insere pela API do planner. O código APR-... vira
a referência externa, então rodar de novo nunca duplica. Também pede aos
agentes as legendas dos posts que ficaram prontos.

Só faz algo quando "agentes.ativo" está ligado no config.json.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import configuracao

BASE = Path(__file__).resolve().parent
CONF = configuracao.carregar()
REGISTRO = Path(os.environ.get("APROVACOES", os.path.expanduser(CONF["agentes"]["registro_aprovacoes"])))
API = os.environ.get("PLANNER_API", f"http://127.0.0.1:{CONF['servidor']['porta']}/api")
CALENDARIO = Path(os.environ.get("CALENDARIO_AGENTES", BASE / "data" / "calendario_agentes.json"))
JANELA_DIAS = 365
PUBLICAR_A_PARTIR_DE = None  # agentes seguem o próprio cronograma; use AAAA-MM-DD para segurar o início

# Segunda = 0 ... Domingo = 6
CALENDARIO_PADRAO = {
    "carrossel": {"dias_semana": [0, 1, 2, 3, 4], "hora": "12:00", "por_dia": 1, "antecedencia_dias": 1},
    "animacao": {"dias_semana": [0, 1, 2, 3, 4], "hora": "15:00", "por_dia": 1, "antecedencia_dias": 1},
    "roteiro-curto": {"dias_semana": [0, 1, 2, 3, 4, 5, 6], "por_dia": 1, "antecedencia_dias": 7},
    "roteiro-longo": {"dias_semana": [6], "por_dia": 2, "antecedencia_dias": 7},
}

# tipo da esteira -> (aba do planner, tipo no planner)
MAPA = {
    "carrossel": ("posts", "carrossel"),
    "animacao": ("posts", "animacao"),
    "roteiro-curto": ("roteiros", "reel"),
    "roteiro-longo": ("roteiros", "longo"),
}


def api(metodo, caminho, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(API + caminho, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"} if dados else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def carregar_calendario():
    """Devolve (regras por tipo, data a partir da qual os agentes publicam ou None)."""
    if not CALENDARIO.exists():
        CALENDARIO.parent.mkdir(parents=True, exist_ok=True)
        padrao = {"publicar_a_partir_de": PUBLICAR_A_PARTIR_DE, **CALENDARIO_PADRAO}
        CALENDARIO.write_text(json.dumps(padrao, ensure_ascii=False, indent=2))
    cal = json.loads(CALENDARIO.read_text())
    inicio = cal.pop("publicar_a_partir_de", PUBLICAR_A_PARTIR_DE)
    try:
        inicio = date.fromisoformat(inicio) if inicio else None
    except (TypeError, ValueError):
        raise SystemExit(f"'publicar_a_partir_de' inválido em {CALENDARIO}. Use AAAA-MM-DD ou null.")
    for tipo, regra in cal.items():
        dias = regra.get("dias_semana")
        if tipo not in MAPA or not dias or any(d not in range(7) for d in dias) \
                or not isinstance(regra.get("por_dia"), int) or regra["por_dia"] < 1:
            raise SystemExit(f"Calendário inválido em {CALENDARIO}, regra '{tipo}'.")
    return {**CALENDARIO_PADRAO, **cal}, inicio


def aprovado(item):
    """'arquivado' = aprovado e já limpo do notebook; reprovados guardam um motivo."""
    st = item.get("status")
    return st == "aprovado" or (st == "arquivado" and not item.get("motivo"))


def ocupa(existente, tipo_esteira, aba, tipo):
    if existente["tipo"] != tipo:
        return False
    if tipo_esteira == "roteiro-curto":  # só disputa vaga com outros roteiros dos agentes
        return existente.get("origem") == "agente"
    return True


def escolher_data(regra, existentes, tipo_esteira, aba, tipo, hoje, a_partir_de=None):
    inicio = hoje + timedelta(days=regra.get("antecedencia_dias", 1))
    if a_partir_de and a_partir_de > inicio:
        inicio = a_partir_de
    for n in range(JANELA_DIAS):
        d = inicio + timedelta(days=n)
        if d.weekday() not in regra["dias_semana"]:
            continue
        no_dia = sum(1 for e in existentes[aba] if e["data"] == d.isoformat() and ocupa(e, tipo_esteira, aba, tipo))
        if no_dia < regra["por_dia"]:
            return d
    return None


# "Animação (Reels/Shorts/TikTok, seg 09/11) — 2 novidades" / "Carrossel — Live travando?" → só o nome
PREFIXO_TIPO = re.compile(r"^\s*(anima[çc][ãa]o|carrossel)\b\s*(\([^)]*\))?\s*[—–:|\-]*\s*", re.I)


def nome_limpo(titulo):
    t = titulo.strip()
    while True:
        m = PREFIXO_TIPO.match(t)
        if not m or not t[m.end():].strip():
            return t
        t = t[m.end():].strip()


def titulo_planner(item, tipo):
    t = nome_limpo(item.get("titulo") or item["codigo"])
    if tipo == "animacao":
        t = "Animação: " + t
    return t[:200]


# ---------- legenda e descrição: escritas pelos agentes (Diretor → Social Media) ----------

CACHE_DESC = Path(os.environ.get("CACHE_DESCRICOES", BASE / "data" / "descricoes.json"))  # versão antiga (Discord)
AGENTE_LEGENDA = os.environ.get("AGENTE_LEGENDA", CONF["agentes"]["agente_legenda"])
COMANDO_AGENTE = CONF["agentes"]["comando"]  # ["openclaw"] no Linux; no Windows, o openclaw roda dentro do WSL
TIMEOUT_AGENTE = int(os.environ.get("TIMEOUT_AGENTE", "900"))
MAX_TENTATIVAS = 3
POR_EXECUCAO = 2
def _nomes_redes(tipo):
    nomes = [configuracao.REDES_SUPORTADAS[r][0] for r in configuracao.redes_por_tipo(CONF).get(tipo, [])]
    if tipo in ("reel", "animacao"):
        nomes = ["YouTube Shorts" if n == "YouTube" else n for n in nomes]
    return ", ".join(nomes[:-1]) + (" e " if len(nomes) > 1 else "") + (nomes[-1] if nomes else "")


REDES_POR_TIPO = {t: _nomes_redes(t) for t in configuracao.REDES_POR_TIPO_BASE}
NOMES_TIPO = {"reel": "Reel", "longo": "Vídeo longo", "carrossel": "Carrossel", "animacao": "Animação"}
BLOCO = re.compile(r"<<<(LEGENDA|DESCRICAO)\s*\n(.*?)\n\s*\1>>>", re.S)


def pedido_legenda(post):
    contexto = ""
    if post.get("roteiro_texto"):
        contexto = f"\nRoteiro do vídeo:\n{post['roteiro_texto'][:4000]}\n"
    if post.get("ref_externa"):
        contexto += (f"\nEsta peça foi aprovada no #aprovacao com o código {post['ref_externa']}. Se o Social Media já "
                     "escreveu o texto de publicação dela em cofre/05-Social-Media, use esse texto.\n")
    return (
        "Pedido automático do AfroCreator Planner. Peça ao Social Media para escrever o texto de publicação deste post, "
        "seguindo o Manual da Marca, e me devolva SÓ o resultado final, sem comentários, exatamente neste formato:\n"
        "<<<LEGENDA\n(legenda para as redes abaixo: gancho na 1ª linha, valor, CTA, hashtags)\nLEGENDA>>>\n"
        "<<<DESCRICAO\n(título curto + descrição para o YouTube, com hashtags)\nDESCRICAO>>>\n\n"
        f"Tipo: {NOMES_TIPO.get(post['tipo'], post['tipo'])}\nRedes: {REDES_POR_TIPO.get(post['tipo'], '')}\n"
        f"Título: {post['titulo']}\nData de publicação: {post['data']}\n{contexto}"
        "Não publique nada e não poste no Discord: só devolva o texto.")


def pedir_ao_agente(texto):
    try:
        res = subprocess.run([*COMANDO_AGENTE, "agent", "--agent", AGENTE_LEGENDA, "--message", texto],
                             capture_output=True, text=True, timeout=TIMEOUT_AGENTE)
    except FileNotFoundError:
        raise RuntimeError("openclaw não encontrado")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"o agente não respondeu em {TIMEOUT_AGENTE // 60} min")
    if res.returncode != 0:
        raise RuntimeError(f"openclaw saiu com código {res.returncode}: {res.stderr[-300:]}")
    return res.stdout


def montar_legenda(saida):
    blocos = {k: v.strip() for k, v in BLOCO.findall(saida)}
    if not blocos.get("LEGENDA"):
        raise RuntimeError("a resposta não veio no formato combinado (<<<LEGENDA ... LEGENDA>>>)")
    texto = blocos["LEGENDA"]
    if blocos.get("DESCRICAO"):
        texto += "\n\n— Descrição (YouTube) —\n" + blocos["DESCRICAO"]
    return texto


def gerar_legendas():
    """Pede aos agentes as legendas pendentes (no máximo 2 por execução, para não travar o time)."""
    st, pendentes = api("GET", "/legendas-pendentes")
    if st != 200:
        raise SystemExit(f"Falha ao ler legendas pendentes: {pendentes}")
    falhas = 0
    for post in pendentes[:POR_EXECUCAO]:
        api("PATCH", f"/posts/{post['id']}", {"legenda_status": "gerando"})
        try:
            nova = montar_legenda(pedir_ao_agente(pedido_legenda(post)))
        except RuntimeError as e:
            tent = post["legenda_tentativas"] + 1
            status = "pendente" if tent < MAX_TENTATIVAS else "erro"
            api("PATCH", f"/posts/{post['id']}", {"legenda_status": status, "legenda_tentativas": tent})
            print(f"Legenda de '{post['titulo']}': falhou ({e}). Tentativa {tent} de {MAX_TENTATIVAS}.")
            falhas += 1
            continue
        antiga = post["legenda"].strip()
        if antiga and antiga not in nova:  # nunca perde o que já estava escrito
            nova += "\n\n— Texto anterior —\n" + antiga
        st, r = api("PATCH", f"/posts/{post['id']}", {"legenda": nova[:5000], "legenda_status": "pronta"})
        if st == 200:
            print(f"Legenda de '{post['titulo']}' escrita pelos agentes.")
        else:
            print(f"Legenda de '{post['titulo']}': o planner recusou ({st}) {r.get('erro')}")
            falhas += 1
    return falhas


def completar_antigos(itens, hoje):
    """Itens dos agentes já no planner: título limpo e legenda pedida aos agentes quando falta."""
    por_cod = {i["codigo"]: i for i in itens if i.get("codigo")}
    posts = ler_existentes(hoje - timedelta(days=JANELA_DIAS), 2 * JANELA_DIAS + 14)["posts"]
    alvos = [p for p in posts if p.get("origem") == "agente" and p.get("ref_externa") in por_cod
             and p["tipo"] in ("carrossel", "animacao")]
    # a versão anterior copiava o resumo de revisão do Discord para a legenda: isso não é legenda, então refaz
    antigos_discord = json.loads(CACHE_DESC.read_text()).get("textos", {}) if CACHE_DESC.exists() else {}
    falhas = 0
    for p in alvos:
        mudar = {}
        titulo = titulo_planner({"titulo": p["titulo"], "codigo": p["ref_externa"]}, p["tipo"])
        if titulo != p["titulo"]:
            mudar["titulo"] = titulo
        veio_do_discord = p["legenda"].strip() and p["legenda"].strip() == antigos_discord.get(p["ref_externa"], "").strip()
        if veio_do_discord:
            mudar["legenda"] = ""
        if (not p["legenda"].strip() or veio_do_discord) and p.get("legenda_status") is None:
            mudar["legenda_status"] = "pendente"
        if mudar:
            st, r = api("PATCH", f"/posts/{p['id']}", mudar)
            if st == 200:
                print(f"{p['ref_externa']}: atualizado ({', '.join(mudar)})")
            else:
                print(f"{p['ref_externa']}: o planner recusou a atualização ({st}) {r.get('erro')}")
                falhas += 1
    return falhas


def montar(item, aba, tipo, dia, regra):
    corpo = {"tipo": tipo, "data": dia.isoformat(), "titulo": titulo_planner(item, tipo),
             "origem": "agente", "ref_externa": item["codigo"]}
    link = item.get("link") or ""
    if aba == "posts":
        corpo["legenda_status"] = "pendente"  # os agentes escrevem a legenda na próxima rodada
        if regra.get("hora"):
            corpo["hora"] = regra["hora"]
        if link.startswith("https://drive.google.com/") or link.startswith("https://docs.google.com/"):
            corpo["drive_link"] = link
    else:
        corpo["texto"] = f"Roteiro aprovado no #aprovacao ({item['codigo']}).\n" + (f"Documento: {link}" if link else "")
    return corpo


def sincronizar(hoje=None):
    hoje = hoje or date.today()
    if not REGISTRO.exists():
        print(f"Registro de aprovações não encontrado: {REGISTRO}. Só as legendas pendentes serão feitas.")
        return 1 if gerar_legendas() else 0
    itens = json.loads(REGISTRO.read_text()).get("itens", [])
    calendario, a_partir = carregar_calendario()

    status, refs = api("GET", "/refs")
    if status != 200:
        raise SystemExit(f"Planner não respondeu ({status}). O serviço está ativo?")
    ja = set(refs["posts"]) | set(refs["roteiros"])

    novos = [i for i in itens if i.get("tipo") in MAPA and aprovado(i) and i.get("codigo") not in ja]
    novos.sort(key=lambda i: i.get("decidido_em") or i.get("enviado_em") or "")
    falhas = 0
    if novos:
        falhas += inserir(novos, calendario, a_partir, hoje)
    falhas += completar_antigos([i for i in itens if aprovado(i)], hoje)
    falhas += gerar_legendas()
    return 1 if falhas else 0


def inserir(novos, calendario, a_partir, hoje):
    existentes = ler_existentes(max(hoje, a_partir or hoje))
    falhas = 0
    for item in novos:
        aba, tipo = MAPA[item["tipo"]]
        regra = calendario[item["tipo"]]
        dia = escolher_data(regra, existentes, item["tipo"], aba, tipo, hoje, a_partir)
        if dia is None:
            print(f"{item['codigo']}: sem vaga nos próximos {JANELA_DIAS} dias no calendário de {item['tipo']}.")
            falhas += 1
            continue
        st, r = api("POST", f"/{aba}", montar(item, aba, tipo, dia, regra))
        if st == 201:
            existentes[aba].append(r)
            print(f"{item['codigo']} → {aba} em {dia.strftime('%d/%m')}: {r['titulo']}")
        elif st == 409:
            continue  # já inserido por outra execução
        else:
            print(f"{item['codigo']}: o planner recusou ({st}) {r.get('erro')}")
            falhas += 1
    return falhas


def ler_existentes(de, dias=JANELA_DIAS + 14):
    """Lê posts e roteiros da janela inteira, em blocos (a API aceita até 100 dias por consulta)."""
    existentes = {"posts": [], "roteiros": []}
    fim = de + timedelta(days=dias)
    while de <= fim:
        ate = min(de + timedelta(days=99), fim)
        for aba in existentes:
            st, lista = api("GET", f"/{aba}?de={de.isoformat()}&ate={ate.isoformat()}")
            if st != 200:
                raise SystemExit(f"Falha ao ler {aba}: {lista}")
            existentes[aba] += lista
        de = ate + timedelta(days=1)
    return existentes


INVERSO = {v: k for k, v in MAPA.items()}  # (aba, tipo) -> tipo da esteira


def reagendar(hoje=None):
    """Move itens dos agentes que ficaram antes da data de início da publicação."""
    hoje = hoje or date.today()
    calendario, a_partir = carregar_calendario()
    if not a_partir or a_partir <= hoje:
        print("A publicação já começou (ou não tem data de início); nada a reagendar.")
        return 0
    antigos = ler_existentes(hoje - timedelta(days=JANELA_DIAS), 2 * JANELA_DIAS + 14)  # passado e futuro
    mover = [(aba, i) for aba in antigos for i in antigos[aba]
             if i.get("origem") == "agente" and i["data"] < a_partir.isoformat()]
    if not mover:
        print("Nenhum item dos agentes antes de " + a_partir.strftime("%d/%m/%Y") + ".")
        return 0
    existentes = ler_existentes(max(hoje, a_partir))
    falhas = 0
    for aba, i in sorted(mover, key=lambda x: (x[1]["data"], x[1]["id"])):
        esteira = INVERSO[(aba, i["tipo"])]
        dia = escolher_data(calendario[esteira], existentes, esteira, aba, i["tipo"], hoje, a_partir)
        if dia is None:
            print(f"{i['ref_externa'] or i['id']}: sem vaga para reagendar.")
            falhas += 1
            continue
        st, r = api("PATCH", f"/{aba}/{i['id']}", {"data": dia.isoformat()})
        if st != 200:
            print(f"{i['ref_externa'] or i['id']}: o planner recusou ({st}) {r.get('erro')}")
            falhas += 1
            continue
        existentes[aba].append(r)
        print(f"{i['ref_externa'] or i['id']}: {i['data']} → {dia.isoformat()}")
    return 1 if falhas else 0


if __name__ == "__main__":
    if not CONF["agentes"]["ativo"]:
        print("Integração com os agentes desligada no config.json (agentes.ativo = false). Nada a fazer.")
        sys.exit(0)
    sys.exit(reagendar() if "--reagendar" in sys.argv else sincronizar())
