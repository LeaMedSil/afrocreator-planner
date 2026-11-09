#!/usr/bin/env python3
"""Coleta o número de seguidores do Instagram e do YouTube e grava no planner.

  python3 coletar_metricas.py configurar   → pede as credenciais (uma vez) e testa
  python3 coletar_metricas.py              → coleta de hoje (o agendador roda isso todo dia)

TikTok: lançado à mão na aba Métricas (a API dele exige aprovação do app).
As credenciais ficam só em data/credenciais.json, neste computador.
"""
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import configuracao

BASE = Path(__file__).resolve().parent
CONF = configuracao.carregar()
CRED = Path(os.environ.get("CREDENCIAIS_METRICAS", BASE / "data" / "credenciais.json"))
API = os.environ.get("PLANNER_API", f"http://127.0.0.1:{CONF['servidor']['porta']}/api")
RENOVAR_APOS_DIAS = 7  # token do Instagram vale 60 dias; renovamos com folga


class Falha(Exception):
    pass


def buscar_json(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {})
            msg = msg.get("message", msg) if isinstance(msg, dict) else msg
        except ValueError:
            msg = ""
        raise Falha(f"HTTP {e.code} {msg}".strip())  # nunca inclui a URL, que leva o token
    except urllib.error.URLError as e:
        raise Falha(f"sem conexão ({e.reason})")


def ler_cred():
    return json.loads(CRED.read_text()) if CRED.exists() else {}


def salvar_cred(c):
    CRED.parent.mkdir(parents=True, exist_ok=True)
    tmp = CRED.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=2))
    try:
        os.chmod(tmp, 0o600)
    except OSError:  # Windows: a pasta do usuário já é privada
        pass
    tmp.replace(CRED)


def instagram(c, hoje):
    tok = c["instagram_token"]
    renovado = date.fromisoformat(c.get("instagram_renovado_em", hoje.isoformat()))
    if hoje - renovado >= timedelta(days=RENOVAR_APOS_DIAS):
        r = buscar_json("https://graph.instagram.com/refresh_access_token?" +
                        urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": tok}))
        c["instagram_token"] = tok = r["access_token"]
        c["instagram_renovado_em"] = hoje.isoformat()
        salvar_cred(c)
        print("Instagram: token renovado.")
    r = buscar_json("https://graph.instagram.com/me?" +
                    urllib.parse.urlencode({"fields": "followers_count,username", "access_token": tok}))
    if "followers_count" not in r:
        raise Falha("a resposta não trouxe followers_count (a conta é profissional?)")
    return int(r["followers_count"]), r.get("username", "")


def youtube(c, _hoje):
    r = buscar_json("https://www.googleapis.com/youtube/v3/channels?" +
                    urllib.parse.urlencode({"part": "statistics,snippet", "id": c["youtube_canal_id"], "key": c["youtube_api_key"]}))
    if not r.get("items"):
        raise Falha("canal não encontrado")
    est = r["items"][0]["statistics"]
    if est.get("hiddenSubscriberCount"):
        raise Falha("o canal está com o número de inscritos oculto")
    return int(est["subscriberCount"]), r["items"][0]["snippet"]["title"]


COLETORES = {r: v for r, v in {"instagram": (instagram, "instagram_token"), "youtube": (youtube, "youtube_api_key")}.items()
             if r in CONF["metricas"]["redes"]}


def gravar(rede, n, hoje):
    req = urllib.request.Request(API + "/metricas", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"rede": rede, "seguidores": n, "data": hoje.isoformat(), "origem": "api"}).encode())
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.URLError as e:
        raise Falha(f"o planner não aceitou o registro ({e})")


def coletar(hoje=None):
    hoje = hoje or date.today()
    c = ler_cred()
    if not CONF["metricas"]["ativo"]:
        print("Métricas desligadas no config.json. Nada a coletar.")
        return 0
    if not c:
        print("Coleta automática ainda não configurada. Rode: python3 coletar_metricas.py configurar")
        return 0
    falhas = 0
    for rede, (fn, chave) in COLETORES.items():
        if not c.get(chave):
            continue
        try:
            n, nome = fn(c, hoje)
            gravar(rede, n, hoje)
            print(f"{rede}: {n} seguidores ({nome})")
        except (Falha, KeyError, ValueError) as e:
            print(f"{rede}: falhou: {e}")
            falhas += 1
    return 1 if falhas else 0


def configurar():
    c = ler_cred()
    print("Cole as credenciais (o que você digitar não aparece na tela). Enter vazio mantém o que já existe.\n")
    if "instagram" in COLETORES:
        tok = getpass.getpass("Token do Instagram (conta profissional; Enter pula): ").strip()
        if tok:
            c["instagram_token"] = tok
            c["instagram_renovado_em"] = (date.today() - timedelta(days=RENOVAR_APOS_DIAS - 1)).isoformat()  # renova amanhã
    if "youtube" in COLETORES:
        key = getpass.getpass("Chave de API do YouTube (Enter pula): ").strip()
        if key:
            c["youtube_api_key"] = key
    if "youtube" in COLETORES and c.get("youtube_api_key"):
        padrao = CONF["metricas"].get("youtube_handle") or ""
        handle = input(f"@ do canal no YouTube{f' [{padrao}]' if padrao else ''}: ").strip() or padrao
        if not handle:
            print("YouTube: informe o @ do canal.")
            return 1
        if not handle.startswith("@"):
            handle = "@" + handle
        try:
            r = buscar_json("https://www.googleapis.com/youtube/v3/channels?" +
                            urllib.parse.urlencode({"part": "id", "forHandle": handle, "key": c["youtube_api_key"]}))
            if not r.get("items"):
                raise Falha(f"não achei o canal {handle}")
            c["youtube_canal_id"] = r["items"][0]["id"]
        except Falha as e:
            print(f"YouTube: {e}")
            return 1
    salvar_cred(c)
    print("\nCredenciais salvas. Testando a coleta de hoje...\n")
    return coletar()


if __name__ == "__main__":
    sys.exit(configurar() if sys.argv[1:] == ["configurar"] else coletar())
