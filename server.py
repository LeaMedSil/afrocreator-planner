#!/usr/bin/env python3
"""AfroCreator Planner: servidor local de roteiros, posts e métricas.

Usa só a biblioteca padrão do Python (nenhum pacote externo). Funciona no
Linux e no Windows. As escolhas de cada pessoa (redes, etapas, cores...)
ficam no config.json, criado pelo instalador.
"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
import traceback
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import configuracao

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
try:
    CONF = configuracao.carregar()
except configuracao.ConfigInvalida as e:
    sys.exit(f"config.json inválido: {e}\nRode o instalador de novo com --reconfigurar.")
DB_PATH = Path(os.environ.get("PLANNER_DB", BASE / "data" / "planner.db"))
HOST = os.environ.get("PLANNER_HOST", CONF["servidor"]["host"])
PORT = int(os.environ.get("PLANNER_PORT", CONF["servidor"]["porta"]))
BACKUP_KEEP = 14
MAX_BODY = 64 * 1024
MAX_RANGE_DAYS = 100

SCHEMA_VERSAO = 4
STATUS_LEGENDA = ("pendente", "gerando", "pronta", "erro")
REDES = ("instagram", "facebook", "youtube", "tiktok", "kwai")
NOMES_REDES = {"instagram": "Instagram", "facebook": "Facebook", "youtube": "YouTube", "tiktok": "TikTok", "kwai": "Kwai"}
REDES_POR_TIPO = configuracao.REDES_POR_TIPO_BASE  # onde cada tipo PODE sair (regra do banco)
REDES_ATIVAS = tuple(CONF["redes"])  # redes que esta pessoa usa
ETAPAS_ATIVAS = configuracao.COLUNAS_ETAPA[:len(CONF["etapas"])]

POSTS_V2 = """
CREATE TABLE posts (
  id INTEGER PRIMARY KEY,
  tipo TEXT NOT NULL CHECK (tipo IN ('reel', 'longo', 'carrossel', 'animacao')),
  data TEXT NOT NULL,
  hora TEXT,
  faixa INTEGER CHECK (faixa IS NULL OR faixa IN (1, 2, 3)),
  titulo TEXT NOT NULL CHECK (length(titulo) BETWEEN 1 AND 200),
  legenda TEXT NOT NULL DEFAULT '',
  drive_link TEXT NOT NULL DEFAULT '',
  roteiro_id INTEGER REFERENCES roteiros (id) ON DELETE SET NULL,
  instagram INTEGER NOT NULL DEFAULT 0 CHECK (instagram IN (0, 1)),
  facebook INTEGER NOT NULL DEFAULT 0 CHECK (facebook IN (0, 1)),
  youtube INTEGER NOT NULL DEFAULT 0 CHECK (youtube IN (0, 1)),
  tiktok INTEGER NOT NULL DEFAULT 0 CHECK (tiktok IN (0, 1)),
  origem TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('manual', 'agente')),
  ref_externa TEXT,
  criado_em TEXT NOT NULL,
  atualizado_em TEXT NOT NULL,
  CHECK (tipo = 'reel' OR faixa IS NULL),
  CHECK (instagram = 0 OR tipo IN ('reel', 'carrossel')),
  CHECK (facebook = 0 OR tipo IN ('reel', 'longo')),
  CHECK (youtube = 0 OR tipo IN ('reel', 'longo', 'animacao')),
  CHECK (tiktok = 0 OR tipo IN ('reel', 'animacao'))
);
CREATE INDEX ix_posts_data ON posts (data);
CREATE UNIQUE INDEX ux_posts_ref ON posts (ref_externa);
"""

METRICAS = """
CREATE TABLE IF NOT EXISTS metricas (
  data TEXT NOT NULL,
  rede TEXT NOT NULL CHECK (rede IN ('instagram', 'youtube', 'tiktok')),
  seguidores INTEGER NOT NULL CHECK (seguidores >= 0),
  origem TEXT NOT NULL CHECK (origem IN ('manual', 'api')),
  registrado_em TEXT NOT NULL,
  PRIMARY KEY (data, rede)
);
"""

POSTS_V4_LEGENDA = """
ALTER TABLE posts ADD COLUMN legenda_status TEXT
  CHECK (legenda_status IS NULL OR legenda_status IN ('pendente', 'gerando', 'pronta', 'erro'));
ALTER TABLE posts ADD COLUMN legenda_tentativas INTEGER NOT NULL DEFAULT 0 CHECK (legenda_tentativas >= 0);
"""

POSTS_V3_KWAI = """
ALTER TABLE posts ADD COLUMN kwai INTEGER NOT NULL DEFAULT 0
  CHECK (kwai IN (0, 1) AND (kwai = 0 OR tipo IN ('reel', 'animacao')));
"""

ROTEIROS_V2_COLS = """
ALTER TABLE roteiros ADD COLUMN origem TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('manual', 'agente'));
ALTER TABLE roteiros ADD COLUMN ref_externa TEXT;
CREATE UNIQUE INDEX ux_roteiros_ref ON roteiros (ref_externa);
"""

POSTS_V1_COLS = ("id, tipo, data, hora, faixa, titulo, legenda, drive_link, roteiro_id, "
                 "instagram, facebook, youtube, tiktok, criado_em, atualizado_em")

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS roteiros (
  id INTEGER PRIMARY KEY,
  tipo TEXT NOT NULL CHECK (tipo IN ('reel', 'longo')),
  data TEXT NOT NULL,
  faixa INTEGER CHECK (faixa IS NULL OR faixa IN (1, 2, 3)),
  titulo TEXT NOT NULL CHECK (length(titulo) BETWEEN 1 AND 200),
  texto TEXT NOT NULL DEFAULT '',
  rosto INTEGER NOT NULL DEFAULT 0 CHECK (rosto IN (0, 1)),
  tela INTEGER NOT NULL DEFAULT 0 CHECK (tela IN (0, 1)),
  edicao INTEGER NOT NULL DEFAULT 0 CHECK (edicao IN (0, 1)),
  criado_em TEXT NOT NULL,
  atualizado_em TEXT NOT NULL,
  CHECK (tipo = 'reel' OR faixa IS NULL)
);
CREATE INDEX IF NOT EXISTS ix_roteiros_data ON roteiros (data);

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY,
  tipo TEXT NOT NULL CHECK (tipo IN ('reel', 'longo')),
  data TEXT NOT NULL,
  hora TEXT,
  faixa INTEGER CHECK (faixa IS NULL OR faixa IN (1, 2, 3)),
  titulo TEXT NOT NULL CHECK (length(titulo) BETWEEN 1 AND 200),
  legenda TEXT NOT NULL DEFAULT '',
  drive_link TEXT NOT NULL DEFAULT '',
  roteiro_id INTEGER REFERENCES roteiros (id) ON DELETE SET NULL,
  instagram INTEGER NOT NULL DEFAULT 0 CHECK (instagram IN (0, 1)),
  facebook INTEGER NOT NULL DEFAULT 0 CHECK (facebook IN (0, 1)),
  youtube INTEGER NOT NULL DEFAULT 0 CHECK (youtube IN (0, 1)),
  tiktok INTEGER NOT NULL DEFAULT 0 CHECK (tiktok IN (0, 1)),
  criado_em TEXT NOT NULL,
  atualizado_em TEXT NOT NULL,
  CHECK (tipo = 'reel' OR (faixa IS NULL AND instagram = 0 AND tiktok = 0))
);
CREATE INDEX IF NOT EXISTS ix_posts_data ON posts (data);
"""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------- validação ----------

def v_tipo(*permitidos):
    def f(v):
        if v not in permitidos:
            raise ApiError(400, "Tipo deve ser: " + ", ".join(permitidos) + ".")
        return v
    return f


def v_status_legenda(v):
    if v is None or v in STATUS_LEGENDA:
        return v
    raise ApiError(400, "Status da legenda inválido.")


def v_tentativas(v):
    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100:
        return v
    raise ApiError(400, "Tentativas inválidas.")


def v_origem(v):
    if v not in ("manual", "agente"):
        raise ApiError(400, "Origem deve ser 'manual' ou 'agente'.")
    return v


def v_ref(v):
    if v is None or v == "":
        return None
    if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", v):
        return v
    raise ApiError(400, "Referência externa inválida (letras, números, ponto, hífen; até 80).")


def v_data(v):
    if isinstance(v, str) and len(v) == 10:
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            pass
    raise ApiError(400, "Data inválida. Use o formato AAAA-MM-DD.")


def v_hora(v):
    if v is None or v == "":
        return None
    if isinstance(v, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        return v
    raise ApiError(400, "Horário inválido. Use HH:MM.")


def v_faixa(v):
    if v is None or v == "":
        return None
    if v in (1, 2, 3) and not isinstance(v, bool):
        return v
    raise ApiError(400, "Faixa deve ser 1, 2, 3 ou vazia.")


def v_titulo(v):
    if not isinstance(v, str) or not v.strip():
        raise ApiError(400, "O título é obrigatório.")
    if len(v.strip()) > 200:
        raise ApiError(400, "O título pode ter no máximo 200 caracteres.")
    return v.strip()


def v_texto(limit):
    def f(v):
        if v is None:
            return ""
        if not isinstance(v, str):
            raise ApiError(400, "Texto inválido.")
        if len(v) > limit:
            raise ApiError(400, f"Texto muito longo (máximo {limit} caracteres).")
        return v
    return f


def v_bool(v):
    if isinstance(v, bool):
        return int(v)
    raise ApiError(400, "Os checks devem ser true ou false.")


DRIVE_ID_RE = re.compile(r"[A-Za-z0-9_-]{10,}")


def drive_id(link):
    if not link:
        return None
    u = urlparse(link)
    m = re.search(r"/(?:d|folders)/([A-Za-z0-9_-]{10,})", u.path)
    if m:
        return m.group(1)
    ids = parse_qs(u.query).get("id")
    if ids and DRIVE_ID_RE.fullmatch(ids[0]):
        return ids[0]
    return None


def v_drive(v):
    if v is None or v == "":
        return ""
    if not isinstance(v, str) or len(v) > 500:
        raise ApiError(400, "Link do Drive inválido.")
    u = urlparse(v.strip())
    if u.scheme != "https" or u.hostname not in ("drive.google.com", "docs.google.com"):
        raise ApiError(400, "Cole um link do Google Drive (https://drive.google.com/...).")
    if not drive_id(v.strip()):
        raise ApiError(400, "Não encontrei o ID do arquivo nesse link do Drive.")
    return v.strip()


def v_roteiro_id(v):
    if v is None or v == "":
        return None
    if isinstance(v, int) and not isinstance(v, bool) and v > 0:
        return v
    raise ApiError(400, "Roteiro vinculado inválido.")


RESOURCES = {
    "roteiros": {
        "fields": {
            "tipo": v_tipo("reel", "longo"), "data": v_data, "faixa": v_faixa, "titulo": v_titulo,
            "texto": v_texto(20000), "rosto": v_bool, "tela": v_bool, "edicao": v_bool,
            "origem": v_origem, "ref_externa": v_ref,
        },
        "required": ("tipo", "data", "titulo"),
        "defaults": {"faixa": None, "texto": "", "rosto": 0, "tela": 0, "edicao": 0,
                     "origem": "manual", "ref_externa": None},
    },
    "posts": {
        "fields": {
            "tipo": v_tipo(*REDES_POR_TIPO), "data": v_data, "hora": v_hora, "faixa": v_faixa,
            "titulo": v_titulo, "legenda": v_texto(5000), "drive_link": v_drive,
            "roteiro_id": v_roteiro_id, "instagram": v_bool, "facebook": v_bool,
            "youtube": v_bool, "tiktok": v_bool, "kwai": v_bool, "origem": v_origem, "ref_externa": v_ref,
            "legenda_status": v_status_legenda, "legenda_tentativas": v_tentativas,
        },
        "required": ("tipo", "data", "titulo"),
        "defaults": {"hora": None, "faixa": None, "legenda": "", "drive_link": "",
                     "roteiro_id": None, "instagram": 0, "facebook": 0, "youtube": 0, "tiktok": 0,
                     "kwai": 0, "origem": "manual", "ref_externa": None,
                     "legenda_status": None, "legenda_tentativas": 0},
    },
}


def validate(resource, body, partial):
    if not isinstance(body, dict):
        raise ApiError(400, "Corpo da requisição deve ser um objeto JSON.")
    spec = RESOURCES[resource]
    unknown = set(body) - set(spec["fields"])
    if unknown:
        raise ApiError(400, "Campos desconhecidos: " + ", ".join(sorted(unknown)))
    if not partial:
        missing = [f for f in spec["required"] if f not in body]
        if missing:
            raise ApiError(400, "Campos obrigatórios: " + ", ".join(missing))
    if partial and not body:
        raise ApiError(400, "Nada para atualizar.")
    return {k: spec["fields"][k](v) for k, v in body.items()}


def apply_rules(resource, row, changed):
    """Regras de negócio aplicadas ao registro já mesclado."""
    if row["tipo"] != "reel":
        if changed.get("faixa") is not None:
            raise ApiError(400, "Só reel usa faixa do dia.")
        row["faixa"] = None
    if resource == "posts":
        possiveis = REDES_POR_TIPO[row["tipo"]]
        permitidas = [r for r in possiveis if r in REDES_ATIVAS]
        for rede in REDES:
            if rede in permitidas:
                continue
            if changed.get(rede):
                n = [NOMES_REDES[r] for r in permitidas]
                nomes = (", ".join(n[:-1]) + " e " + n[-1]) if len(n) > 1 else (n[0] if n else "nenhuma rede ativa")
                raise ApiError(400, f"Esse tipo é publicado só em: {nomes}.")
            if rede not in possiveis:  # mudou de tipo: limpa o que não cabe mais
                row[rede] = 0
    return row


# ---------- banco ----------

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        versao = conn.execute("PRAGMA user_version").fetchone()[0]
        tinha_dados = conn.execute("SELECT count(*) FROM sqlite_master WHERE name = 'posts'").fetchone()[0]
    if versao < SCHEMA_VERSAO and tinha_dados:
        backup_once(sufixo=f"antes-v{SCHEMA_VERSAO}")
    with closing(connect()) as conn:
        if versao < 2:
            conn.execute("PRAGMA foreign_keys = OFF")  # necessário para recriar a tabela posts
            conn.executescript(
                "BEGIN;" + SCHEMA_V1 + ROTEIROS_V2_COLS +
                "ALTER TABLE posts RENAME TO posts_v1; DROP INDEX IF EXISTS ix_posts_data;" + POSTS_V2 +
                f"INSERT INTO posts ({POSTS_V1_COLS}) SELECT {POSTS_V1_COLS} FROM posts_v1;"
                "DROP TABLE posts_v1; PRAGMA user_version = 2; COMMIT;")
            problemas = conn.execute("PRAGMA foreign_key_check").fetchall()
            if problemas:
                raise RuntimeError(f"Migração deixou vínculos inválidos: {problemas[:5]}")
            conn.execute("PRAGMA foreign_keys = ON")
        if versao < 3:
            conn.executescript("BEGIN;" + POSTS_V3_KWAI + "PRAGMA user_version = 3; COMMIT;")
        if versao < 4:
            conn.executescript("BEGIN;" + POSTS_V4_LEGENDA + "PRAGMA user_version = 4; COMMIT;")
        conn.executescript(METRICAS)


# ---------- métricas ----------

REDES_METRICAS = tuple(CONF["metricas"]["redes"]) or configuracao.REDES_METRICAS_SUPORTADAS
PERIODOS = (("30 dias", 30), ("60 dias", 60), ("90 dias", 90), ("6 meses", 182), ("9 meses", 273), ("1 ano", 365))
META = CONF["metricas"]["meta"]  # pode ser None (sem meta)


def registrar_metrica(body):
    if not isinstance(body, dict) or set(body) - {"rede", "data", "seguidores", "origem"}:
        raise ApiError(400, "Envie rede, seguidores e, opcionalmente, data e origem.")
    rede = body.get("rede")
    if rede not in REDES_METRICAS:
        raise ApiError(400, "Rede deve ser: " + ", ".join(REDES_METRICAS) + ".")
    n = body.get("seguidores")
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 10**9:
        raise ApiError(400, "Seguidores deve ser um número inteiro, sem pontos.")
    dia = v_data(body["data"]) if body.get("data") else date.today().isoformat()
    if dia > date.today().isoformat():
        raise ApiError(400, "Não dá para registrar seguidores de uma data futura.")
    origem = body.get("origem", "manual")
    if origem not in ("manual", "api"):
        raise ApiError(400, "Origem deve ser 'manual' ou 'api'.")
    with closing(connect()) as conn:
        with conn:
            conn.execute(
                "INSERT INTO metricas (data, rede, seguidores, origem, registrado_em) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (data, rede) DO UPDATE SET seguidores = excluded.seguidores, "
                "origem = excluded.origem, registrado_em = excluded.registrado_em",
                (dia, rede, n, origem, now()))
    return {"rede": rede, "data": dia, "seguidores": n}


def resumo_metricas(hoje=None):
    hoje = hoje or date.today()
    with closing(connect()) as conn:
        redes = {}
        for rede in REDES_METRICAS:
            atual = conn.execute("SELECT data, seguidores, origem FROM metricas WHERE rede = ? "
                                 "ORDER BY data DESC LIMIT 1", (rede,)).fetchone()
            primeiro = conn.execute("SELECT min(data) FROM metricas WHERE rede = ?", (rede,)).fetchone()[0]
            periodos = []
            for nome, dias in PERIODOS:
                alvo = (hoje - timedelta(days=dias)).isoformat()
                antes = conn.execute("SELECT seguidores FROM metricas WHERE rede = ? AND data <= ? "
                                     "ORDER BY data DESC LIMIT 1", (rede, alvo)).fetchone()
                ganho = atual["seguidores"] - antes[0] if (atual and antes) else None
                periodos.append({"nome": nome, "dias": dias, "ganho": ganho})
            redes[rede] = {"atual": dict(atual) if atual else None, "desde": primeiro, "periodos": periodos}
    return {"redes": redes, "meta": META, "hoje": hoje.isoformat()}


def backup_once(sufixo=None):
    dest_dir = DB_PATH.parent / "backups"
    dest_dir.mkdir(exist_ok=True)
    if sufixo:
        dest = dest_dir / f"migracao-{date.today().isoformat()}-{sufixo}.db"
        with closing(connect()) as src, closing(sqlite3.connect(dest)) as dst:
            src.backup(dst)
        return
    dest = dest_dir / f"planner-{date.today().isoformat()}.db"
    with closing(connect()) as src, closing(sqlite3.connect(dest)) as dst:
        src.backup(dst)
    for old in sorted(dest_dir.glob("planner-*.db"))[:-BACKUP_KEEP]:
        old.unlink()


def backup_loop():
    while True:
        try:
            backup_once()
        except Exception:
            traceback.print_exc(file=sys.stderr)
        time.sleep(6 * 3600)


def row_out(resource, r):
    d = dict(r)
    if resource == "posts":
        d["drive_id"] = drive_id(d["drive_link"])
        d["drive_pasta"] = "/folders/" in d["drive_link"]
    return d


def list_refs():
    with closing(connect()) as conn:
        return {res: [r[0] for r in conn.execute(f"SELECT ref_externa FROM {res} WHERE ref_externa IS NOT NULL")]
                for res in RESOURCES}


def list_range(resource, query):
    de, ate = query.get("de", [None])[0], query.get("ate", [None])[0]
    if not de or not ate:
        raise ApiError(400, "Informe os parâmetros 'de' e 'ate'.")
    d1, d2 = date.fromisoformat(v_data(de)), date.fromisoformat(v_data(ate))
    if d2 < d1 or (d2 - d1) > timedelta(days=MAX_RANGE_DAYS):
        raise ApiError(400, f"Intervalo inválido (máximo {MAX_RANGE_DAYS} dias).")
    if resource == "posts":
        sql = ("SELECT p.*, r.titulo AS roteiro_titulo FROM posts p "
               "LEFT JOIN roteiros r ON r.id = p.roteiro_id "
               "WHERE p.data BETWEEN ? AND ? ORDER BY p.data, p.faixa IS NULL, p.faixa, p.hora, p.id")
    else:
        sql = ("SELECT * FROM roteiros WHERE data BETWEEN ? AND ? "
               "ORDER BY data, faixa IS NULL, faixa, id")
    with closing(connect()) as conn:
        return [row_out(resource, r) for r in conn.execute(sql, (d1.isoformat(), d2.isoformat()))]


def get_one(conn, resource, rid):
    r = conn.execute(f"SELECT * FROM {resource} WHERE id = ?", (rid,)).fetchone()
    if r is None:
        raise ApiError(404, "Registro não encontrado.")
    return r


def create(resource, body):
    vals = validate(resource, body, partial=False)
    row = apply_rules(resource, {**RESOURCES[resource]["defaults"], **vals}, vals)
    row["criado_em"] = row["atualizado_em"] = now()
    cols = list(row)
    with closing(connect()) as conn:
        with conn:
            cur = conn.execute(
                f"INSERT INTO {resource} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [row[c] for c in cols])
            return row_out(resource, get_one(conn, resource, cur.lastrowid))


def update(resource, rid, body):
    vals = validate(resource, body, partial=True)
    with closing(connect()) as conn:
        with conn:  # leitura + escrita na mesma transação
            conn.execute("BEGIN IMMEDIATE")
            current = dict(get_one(conn, resource, rid))
            row = apply_rules(resource, {**current, **vals}, vals)
            row["atualizado_em"] = now()
            cols = [c for c in RESOURCES[resource]["fields"]] + ["atualizado_em"]
            conn.execute(
                f"UPDATE {resource} SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                [row[c] for c in cols] + [rid])
            saida = row_out(resource, get_one(conn, resource, rid))
            if resource == "roteiros" and producao_completa(row) and not producao_completa(current):
                saida["post_criado"] = roteiro_pronto(conn, row, rid)
            return saida


def producao_completa(r):
    return all(r[c] for c in ETAPAS_ATIVAS)


def roteiro_pronto(conn, rot, rid):
    """Roteiro com todas as etapas feitas: garante o post vinculado e, se os agentes
    estiverem ligados, pede a legenda a eles.

    Devolve o id do post criado, ou None quando ele já existia."""
    com_agentes = CONF["agentes"]["ativo"]
    if rot["tipo"] not in CONF["tipos_post"]:
        return None
    existente = conn.execute("SELECT id, legenda_status FROM posts WHERE roteiro_id = ? ORDER BY id LIMIT 1",
                             (rid,)).fetchone()
    if existente:
        if com_agentes and existente["legenda_status"] is None:
            conn.execute("UPDATE posts SET legenda_status = 'pendente', atualizado_em = ? WHERE id = ?",
                         (now(), existente["id"]))
        return None
    agora = now()
    redes = {r: 0 for r in REDES}
    cur = conn.execute(
        "INSERT INTO posts (tipo, data, faixa, titulo, roteiro_id, origem, legenda_status, criado_em, atualizado_em, "
        + ", ".join(redes) + ") VALUES (?, ?, ?, ?, ?, 'manual', ?, ?, ?, " + ", ".join("?" * len(redes)) + ")",
        [rot["tipo"], rot["data"], rot["faixa"], rot["titulo"], rid, "pendente" if com_agentes else None,
         agora, agora, *redes.values()])
    return cur.lastrowid


def legendas_pendentes(limite=3):
    with closing(connect()) as conn:
        linhas = conn.execute(
            "SELECT p.*, r.texto AS roteiro_texto FROM posts p LEFT JOIN roteiros r ON r.id = p.roteiro_id "
            "WHERE p.legenda_status = 'pendente' "
            "   OR (p.legenda_status = 'gerando' AND p.atualizado_em < ?) "  # pedido que travou no meio
            "ORDER BY p.data, p.id LIMIT ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(timespec="seconds"), limite)).fetchall()
        return [row_out("posts", l) | {"roteiro_texto": l["roteiro_texto"]} for l in linhas]


def delete(resource, rid):
    with closing(connect()) as conn:
        with conn:
            cur = conn.execute(f"DELETE FROM {resource} WHERE id = ?", (rid,))
            if cur.rowcount == 0:
                raise ApiError(404, "Registro não encontrado.")


# ---------- HTTP ----------

ROUTE = re.compile(r"^/api/(roteiros|posts)(?:/(\d+))?$")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".jpg": "image/jpeg",
         ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2",
         ".svg": "image/svg+xml", ".png": "image/png"}


class Handler(BaseHTTPRequestHandler):
    server_version = "AfroCreatorPlanner"

    def log_message(self, fmt, *args):  # sem dados pessoais, só método/rota/status
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, status, data, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("application/json"):
            raise ApiError(415, "Envie JSON (Content-Type: application/json).")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Content-Length inválido.")
        if length <= 0 or length > MAX_BODY:
            raise ApiError(413 if length > MAX_BODY else 400, "Corpo vazio ou grande demais.")
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "JSON inválido.")

    def check_origin(self):
        """Bloqueia escrita disparada por outro site aberto no navegador."""
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            raise ApiError(403, "Origem não permitida.")

    def dispatch(self, method):
        url = urlparse(self.path)
        m = ROUTE.match(url.path)
        try:
            if url.path == "/api/config" and method == "GET":
                return self.send_json(200, configuracao.publica(CONF))
            if url.path == "/tema.css" and method == "GET":
                return self.send_bytes(200, configuracao.tema_css(CONF).encode(), "text/css; charset=utf-8")
            if url.path == "/api/refs" and method == "GET":
                return self.send_json(200, list_refs())
            if url.path == "/api/legendas-pendentes" and method == "GET":
                return self.send_json(200, legendas_pendentes())
            if url.path == "/api/metricas":
                if method == "GET":
                    return self.send_json(200, resumo_metricas())
                if method == "POST":
                    self.check_origin()
                    return self.send_json(201, registrar_metrica(self.read_body()))
                raise ApiError(405, "Método não permitido.")
            if not m:
                if method == "GET":
                    return self.serve_static(url.path)
                raise ApiError(404, "Rota não encontrada.")
            resource, rid = m.group(1), m.group(2)
            rid = int(rid) if rid else None
            if method != "GET":
                self.check_origin()
            if method == "GET" and rid is None:
                return self.send_json(200, list_range(resource, parse_qs(url.query)))
            if method == "GET":
                with closing(connect()) as conn:
                    return self.send_json(200, row_out(resource, get_one(conn, resource, rid)))
            if method == "POST" and rid is None:
                return self.send_json(201, create(resource, self.read_body()))
            if method == "PATCH" and rid:
                return self.send_json(200, update(resource, rid, self.read_body()))
            if method == "DELETE" and rid:
                delete(resource, rid)
                return self.send_json(200, {"ok": True})
            raise ApiError(405, "Método não permitido.")
        except ApiError as e:
            self.send_json(e.status, {"erro": e.message})
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e) and "ref_externa" in str(e):
                return self.send_json(409, {"erro": "Já existe um registro com essa referência."})
            msg = "Roteiro vinculado não existe." if "FOREIGN KEY" in str(e) else "Dados inconsistentes."
            self.send_json(400, {"erro": msg})
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self.send_json(500, {"erro": "Erro interno. Veja o log do serviço."})

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC not in target.parents or not target.is_file() or target.suffix not in TYPES:
            raise ApiError(404, "Arquivo não encontrado.")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES[target.suffix])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if target.suffix in (".html", ".js", ".css")
                         else "max-age=604800")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_DELETE(self):
        self.dispatch("DELETE")


def main():
    init_db()
    threading.Thread(target=backup_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    onde = "toda a rede de casa" if HOST == "0.0.0.0" else "só este computador"
    print(f"Planner {CONF['marca']['nome']} rodando em http://127.0.0.1:{PORT} ({onde})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
