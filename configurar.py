#!/usr/bin/env python3
"""Perguntas de personalização do AfroCreator Planner.

  python3 configurar.py                  → perguntas (Enter aceita o valor entre colchetes)
  python3 configurar.py --padrao         → sem perguntas: usa o setup da AfroCreator Tech
  python3 configurar.py --respostas X    → sem perguntas: usa um config.json pronto (X)

Grava o resultado em config.json. Se ele já existir, as respostas atuais viram o padrão,
então dá para rodar de novo só para mudar uma coisa.
"""
import argparse
import copy
import json
import os
import platform
import re
import sys
from datetime import date
from pathlib import Path

import configuracao as cf

AQUI = Path(__file__).resolve().parent
WINDOWS = platform.system() == "Windows"

if WINDOWS:
    os.system("")  # liga as cores ANSI no terminal do Windows
for fluxo in (sys.stdout, sys.stdin):
    try:
        fluxo.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

COR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
def _c(cod, t): return f"\033[{cod}m{t}\033[0m" if COR else t
ciano = lambda t: _c("96", t)
laranja = lambda t: _c("33", t)
verde = lambda t: _c("92", t)
cinza = lambda t: _c("90", t)
negrito = lambda t: _c("1", t)


def titulo(n, total, texto):
    print()
    print(ciano(f"━━ {n}/{total} · {texto} " + "━" * max(0, 46 - len(texto))))


def perguntar(texto, padrao=""):
    sufixo = f" [{padrao}]" if padrao != "" else ""
    try:
        r = input(f"{texto}{cinza(sufixo)}: ").strip()
    except EOFError:
        r = ""
    return r or str(padrao)


def sim_nao(texto, padrao=True):
    while True:
        r = perguntar(texto + " (s/n)", "s" if padrao else "n").lower()
        if r in ("s", "sim", "y", "yes"):
            return True
        if r in ("n", "nao", "não", "no"):
            return False
        print(laranja("  Responda s ou n."))


def escolher(texto, opcoes, padrao):
    """opcoes: lista de (valor, rótulo). Devolve o valor escolhido."""
    print(texto)
    for i, (v, rot) in enumerate(opcoes, 1):
        marca = verde("●") if v == padrao else " "
        print(f"  {marca} {i}) {rot}")
    idx_padrao = next((i for i, (v, _) in enumerate(opcoes, 1) if v == padrao), 1)
    while True:
        r = perguntar("Número", idx_padrao)
        if r.isdigit() and 1 <= int(r) <= len(opcoes):
            return opcoes[int(r) - 1][0]
        print(laranja(f"  Digite um número de 1 a {len(opcoes)}."))


def varios(texto, opcoes, marcados, minimo=1):
    """Múltipla escolha: a pessoa digita os números separados por vírgula."""
    print(texto)
    for i, (v, rot) in enumerate(opcoes, 1):
        print(f"  [{verde('x') if v in marcados else ' '}] {i}) {rot}")
    padrao = ",".join(str(i) for i, (v, _) in enumerate(opcoes, 1) if v in marcados)
    while True:
        r = perguntar("Números separados por vírgula", padrao)
        partes = [p.strip() for p in r.replace(" ", ",").split(",") if p.strip()]
        if all(p.isdigit() and 1 <= int(p) <= len(opcoes) for p in partes) and len(set(partes)) >= minimo:
            escolhidos = {opcoes[int(p) - 1][0] for p in partes}
            return [v for v, _ in opcoes if v in escolhidos]
        print(laranja(f"  Escolha pelo menos {minimo}, usando os números da lista (ex.: 1,3)."))


def cor(texto, padrao):
    while True:
        r = perguntar(texto, padrao)
        if not r.startswith("#"):
            r = "#" + r
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", r):
            return r.upper()
        print(laranja("  Use o formato #RRGGBB, por exemplo #0DF6FE."))


def lista_nomes(texto, atuais, minimo, maximo, limite):
    print(texto)
    print(cinza(f"  De {minimo} a {maximo} itens. Enter mantém o nome atual; digite - para remover."))
    nomes = []
    for i in range(maximo):
        atual = atuais[i] if i < len(atuais) else ""
        r = perguntar(f"  Item {i + 1}", atual if atual else "-")
        if r == "-":
            if len(nomes) >= minimo:
                break
            print(laranja(f"  Precisa de pelo menos {minimo}."))
            r = perguntar(f"  Item {i + 1}", atual or "Etapa")
        nomes.append(r[:limite].strip())
    return nomes


def ip_local():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "IP-DO-COMPUTADOR"


def perguntas(c):
    TOTAL = 9
    print(negrito("\nVamos personalizar o seu Planner."))
    print(cinza("Enter aceita o que está entre colchetes. Dá para mudar tudo depois rodando o instalador com --reconfigurar."))

    titulo(1, TOTAL, "Sua marca")
    c["marca"]["nome"] = perguntar("Nome da marca ou do canal", c["marca"]["nome"])[:40]
    c["marca"]["subtitulo"] = perguntar("Texto ao lado do nome", c["marca"]["subtitulo"])[:30]

    titulo(2, TOTAL, "Visual")
    temas = [("afrocreator", "AfroCreator Tech (ciano neon e laranja)"), ("roxo-neon", "Roxo neon e rosa"),
             ("verde-gamer", "Verde gamer e amarelo"), ("vermelho-live", "Vermelho live e laranja"),
             ("personalizado", "Minhas cores")]
    tema = escolher("Tema de cores (todos são escuros, para descansar a vista):", temas, c["tema"])
    c["tema"] = tema
    if tema == "personalizado":
        base = c["cores"]
        print(cinza("  Dica: pegue os códigos no site da sua marca ou em um seletor de cores (#RRGGBB)."))
        c["cores"] = {
            "principal": cor("  Cor principal (botões, destaques)", base["principal"]),
            "destaque": cor("  Cor de destaque (alertas, etiquetas)", base["destaque"]),
            "secundaria": cor("  Cor secundária (brilhos)", base["secundaria"]),
            "fundo": cor("  Fundo (escuro)", base["fundo"]),
            "fundo_escuro": cor("  Fundo mais escuro", base["fundo_escuro"]),
            "texto": cor("  Texto (claro)", base["texto"]),
            "sucesso": cor("  Cor de 'pronto' (checks)", base["sucesso"]),
        }
    else:
        c["cores"] = dict(cf.TEMAS[tema])
    c["fontes"] = escolher("Fontes:", [("marca", "Fontes tech (Audiowide, Chakra Petch e Exo 2)"),
                                       ("sistema", "Fontes do sistema (mais simples)")], c["fontes"])

    titulo(3, TOTAL, "Redes sociais")
    c["redes"] = varios("Em quais redes você publica?",
                        [(r, nome) for r, (nome, _) in cf.REDES_SUPORTADAS.items()], c["redes"])

    titulo(4, TOTAL, "Tipos de conteúdo")
    c["tipos_roteiro"] = varios("Você escreve roteiros de quê?",
                                [("reel", "Vídeos curtos (Reels, Shorts, TikTok)"), ("longo", "Vídeos longos (YouTube)")],
                                c["tipos_roteiro"])
    possiveis = [t for t in cf.REDES_POR_TIPO_BASE if any(r in c["redes"] for r in cf.REDES_POR_TIPO_BASE[t])]
    rot_tipo = {"reel": "Vídeos curtos", "longo": "Vídeos longos", "carrossel": "Carrosséis",
                "animacao": "Animações (vídeos curtos animados)"}
    if not possiveis:
        print(laranja("  Nenhum tipo de post combina com essas redes; voltando às redes padrão."))
        c["redes"] = list(cf.REDES_SUPORTADAS)
        possiveis = list(cf.REDES_POR_TIPO_BASE)
    opcoes = []
    for t in possiveis:
        onde = ", ".join(cf.REDES_SUPORTADAS[r][0] for r in cf.REDES_POR_TIPO_BASE[t] if r in c["redes"])
        opcoes.append((t, f"{rot_tipo[t]} {cinza('(' + onde + ')')}"))
    c["tipos_post"] = varios("Que tipos de post você quer acompanhar?", opcoes,
                             [t for t in c["tipos_post"] if t in possiveis] or possiveis)

    titulo(5, TOTAL, "Etapas de produção")
    print("Cada roteiro tem checks de produção. Quando todos ficam marcados, o roteiro fica verde")
    print("e o post é criado sozinho na aba Posts.")
    if sim_nao(f"Usar as etapas atuais ({', '.join(c['etapas'])})?", True):
        pass
    else:
        c["etapas"] = lista_nomes("Nomes das etapas, na ordem:", c["etapas"], 1, 3, 30)

    titulo(6, TOTAL, "Reels por dia")
    if "reel" in c["tipos_roteiro"] or "reel" in c["tipos_post"]:
        print("Se você posta mais de um vídeo curto por dia, cada um pode ter uma 'faixa' com função própria")
        print(cinza("(ex.: Reel 1 atrai, Reel 2 ensina, Reel 3 gera autoridade). 0 = sem faixas."))
        n = escolher("Quantas faixas por dia?", [(0, "Nenhuma"), (1, "1"), (2, "2"), (3, "3")],
                     len(c["faixas"]))
        atuais = (c["faixas"] + cf.PADRAO["faixas"])[:n]
        if n and not sim_nao(f"Usar os nomes {', '.join(atuais)}?", True):
            atuais = lista_nomes("Nomes das faixas:", atuais, n, n, 40)
        c["faixas"] = atuais
    else:
        c["faixas"] = []
        print(cinza("Sem vídeos curtos: pulando."))

    titulo(7, TOTAL, "Métricas de seguidores")
    c["metricas"]["ativo"] = sim_nao("Quer acompanhar o crescimento de seguidores?", c["metricas"]["ativo"])
    if c["metricas"]["ativo"]:
        opc = [(r, cf.REDES_SUPORTADAS[r][0]) for r in cf.REDES_METRICAS_SUPORTADAS]
        c["metricas"]["redes"] = varios("De quais redes?", opc,
                                        [r for r in c["metricas"]["redes"]] or ["instagram"])
        if "youtube" in c["metricas"]["redes"]:
            h = perguntar("@ do seu canal no YouTube (para a coleta automática; Enter pula)",
                          c["metricas"].get("youtube_handle", ""))
            c["metricas"]["youtube_handle"] = ("@" + h.lstrip("@")) if h else ""
        meta = c["metricas"].get("meta") or {}
        if sim_nao("Quer ter uma meta de seguidores com barra de progresso?", bool(meta)):
            rede = escolher("Meta de qual rede?", [(r, cf.REDES_SUPORTADAS[r][0]) for r in c["metricas"]["redes"]],
                            meta.get("rede") if meta.get("rede") in c["metricas"]["redes"] else c["metricas"]["redes"][0])
            while True:
                n = perguntar("Quantos seguidores?", meta.get("seguidores", 10000)).replace(".", "").replace(" ", "")
                if n.isdigit() and int(n) > 0:
                    break
                print(laranja("  Digite só números, ex.: 10000."))
            while True:
                d = perguntar("Até quando? (AAAA-MM-DD)", meta.get("data", f"{date.today().year + 1}-12-31"))
                try:
                    if date.fromisoformat(d) > date.today():
                        break
                except ValueError:
                    pass
                print(laranja("  Use uma data futura no formato AAAA-MM-DD, ex.: 2027-12-31."))
            c["metricas"]["meta"] = {"rede": rede, "seguidores": int(n), "data": d}
        else:
            c["metricas"]["meta"] = None

    titulo(8, TOTAL, "Agentes de IA (opcional)")
    print("Se você também instalou o kit de agentes (repositório afrocreator-agentes), o Planner pode")
    print("receber sozinho o que você aprovar no Discord e pedir as legendas dos posts aos agentes.")
    c["agentes"]["ativo"] = sim_nao("Ligar a integração com os agentes?", c["agentes"]["ativo"])
    if c["agentes"]["ativo"]:
        if WINDOWS:
            print(cinza("  No Windows, os agentes rodam dentro do Ubuntu (WSL). Caminho do cofre visto pelo Windows,"))
            print(cinza("  ex.: \\\\wsl.localhost\\Ubuntu-24.04\\home\\SEU_USUARIO\\Minha Marca\\00-Painel\\aprovacoes.json"))
            if c["agentes"]["comando"] == ["openclaw"]:
                c["agentes"]["comando"] = ["wsl", "-e", "bash", "-lc", 'openclaw "$@"', "openclaw"]
        c["agentes"]["registro_aprovacoes"] = perguntar("Arquivo de aprovações (aprovacoes.json no cofre dos agentes)",
                                                        c["agentes"]["registro_aprovacoes"])
        c["agentes"]["agente_legenda"] = perguntar("Agente que recebe os pedidos de legenda",
                                                   c["agentes"]["agente_legenda"]).lower()

    titulo(9, TOTAL, "Acesso e tela inicial")
    visoes = [("roteiros", "Calendário de roteiros"), ("posts", "Calendário de posts")]
    if c["metricas"]["ativo"]:
        visoes.append(("metricas", "Métricas"))
    c["visao_inicial"] = escolher("O que aparece ao abrir o Planner?", visoes,
                                  c["visao_inicial"] if any(v == c["visao_inicial"] for v, _ in visoes) else "roteiros")
    c["servidor"]["host"] = escolher(
        "Quem pode abrir o Planner?",
        [("127.0.0.1", "Só este computador (mais seguro)"),
         ("0.0.0.0", "Qualquer aparelho da minha rede de casa (celular, outro PC)")],
        c["servidor"]["host"])
    if c["servidor"]["host"] == "0.0.0.0":
        print(laranja("  Atenção: o Planner não tem senha. Use só em rede de casa, nunca em Wi-Fi público,"))
        print(laranja("  e não libere essa porta no roteador."))
    while True:
        p = perguntar("Porta", c["servidor"]["porta"])
        if p.isdigit() and 1024 <= int(p) <= 65535:
            c["servidor"]["porta"] = int(p)
            break
        print(laranja("  Use um número entre 1024 e 65535."))
    return c


def resumo(c):
    rpt = cf.redes_por_tipo(c)
    nome_t = {"reel": "Curtos", "longo": "Longos", "carrossel": "Carrosséis", "animacao": "Animações"}
    print()
    print(ciano("━━ Resumo " + "━" * 50))
    print(f"  Marca:        {negrito(c['marca']['nome'])} · {c['marca']['subtitulo']}")
    print(f"  Tema:         {c['tema']} · fontes {c['fontes']}")
    print(f"  Redes:        {', '.join(cf.REDES_SUPORTADAS[r][0] for r in c['redes'])}")
    print(f"  Roteiros:     {', '.join(nome_t[t] for t in c['tipos_roteiro'])}")
    for t in c["tipos_post"]:
        print(f"  Posts {nome_t[t]:<11}→ {', '.join(cf.REDES_SUPORTADAS[r][0] for r in rpt[t])}")
    print(f"  Etapas:       {' → '.join(c['etapas'])}")
    print(f"  Faixas:       {', '.join(c['faixas']) or 'nenhuma'}")
    m = c["metricas"]
    if m["ativo"]:
        meta = m.get("meta")
        txt_meta = f" · meta {meta['seguidores']:,} no {cf.REDES_SUPORTADAS[meta['rede']][0]} até {meta['data']}".replace(",", ".") if meta else ""
        print(f"  Métricas:     {', '.join(cf.REDES_SUPORTADAS[r][0] for r in m['redes'])}{txt_meta}")
    else:
        print("  Métricas:     desligadas")
    print(f"  Agentes:      {'ligados' if c['agentes']['ativo'] else 'desligados'}")
    onde = "só este computador" if c["servidor"]["host"] == "127.0.0.1" else f"rede de casa (ex.: http://{ip_local()}:{c['servidor']['porta']})"
    print(f"  Endereço:     http://127.0.0.1:{c['servidor']['porta']} · {onde}")


def main():
    ap = argparse.ArgumentParser(description="Personaliza o AfroCreator Planner.")
    ap.add_argument("--padrao", action="store_true", help="não pergunta nada: usa o setup padrão (ou o atual)")
    ap.add_argument("--respostas", help="usa um arquivo JSON pronto, no formato do config.exemplo.json")
    ap.add_argument("--saida", default=str(cf.CONFIG_PATH), help="onde gravar (padrão: config.json)")
    args = ap.parse_args()
    saida = Path(args.saida)

    try:
        if args.respostas:
            c = cf.carregar(args.respostas)
        else:
            c = copy.deepcopy(cf.carregar(saida))  # sem arquivo: valores padrão
            if saida.exists():
                print(cinza(f"Usando as respostas atuais de {saida.name} como padrão."))
            if not args.padrao:
                c = cf.validar(perguntas(c))
    except cf.ConfigInvalida as e:
        print(laranja(f"Configuração inválida: {e}"))
        return 1
    except KeyboardInterrupt:
        print(laranja("\nCancelado. Nada foi gravado."))
        return 130

    resumo(c)
    if not args.padrao and not args.respostas and sys.stdin.isatty():
        if not sim_nao("\nGravar essa configuração?", True):
            print(laranja("Nada foi gravado. Rode de novo quando quiser."))
            return 1
    tmp = saida.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(saida)
    print(verde(f"✔ Configuração gravada em {saida}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
