"use strict";

const MESES = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"];
const SEM = ["Dom","Seg","Ter","Qua","Qui","Sex","Sáb"];
// Tudo o que muda de pessoa para pessoa vem de /api/config (config.json, criado pelo instalador).
let CONFIG = null;
let FAIXAS = {};     // {"1": "Reel 1: atração", ...} (pode ser vazio)
let ETAPAS = [];     // [["rosto", "Gravação rosto"], ...] (1 a 3)
let REDES = {};      // {instagram: ["Instagram", "IG"], ...} só as redes ativas
let REDES_POR_TIPO = {};
let TIPOS = {roteiros: [], posts: []};
const NOMES_TIPO = {reel: "Reel", longo: "Vídeo longo", carrossel: "Carrossel", animacao: "Animação"};

const $ = (s) => document.querySelector(s);
const estado = {visao: "roteiros", mes: inicioMes(new Date()), rede: "", itens: [], carregando: false};
let ultimoFoco = null;

// ---------- utilitários ----------
function inicioMes(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function deIso(s) { const [a, m, d] = s.split("-").map(Number); return new Date(a, m - 1, d); }
function somaDias(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function ddmm(s) { return s.slice(8, 10) + "/" + s.slice(5, 7); }

function h(tag, attrs = {}, ...filhos) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) if (f != null && f !== false) el.append(f);
  return el;
}

async function api(metodo, caminho, corpo) {
  const opts = {method: metodo, headers: {}};
  if (corpo !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(corpo);
  }
  let r;
  try { r = await fetch(caminho, opts); }
  catch { throw new Error("Sem conexão com o servidor do planner. Verifique se o computador do planner está ligado."); }
  const dados = await r.json().catch(() => null);
  if (!r.ok) throw new Error((dados && dados.erro) || `Erro ${r.status}.`);
  return dados;
}

let avisoTimer;
function aviso(msg, erro = false) {
  const el = $("#aviso");
  el.textContent = msg;
  el.classList.toggle("erro", erro);
  el.hidden = false;
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => { el.hidden = true; }, erro ? 6000 : 2500);
}

function driveId(link) {
  if (!link) return null;
  let u;
  try { u = new URL(link.trim()); } catch { return null; }
  if (u.protocol !== "https:" || !["drive.google.com", "docs.google.com"].includes(u.hostname)) return null;
  const m = u.pathname.match(/\/(d|folders)\/([A-Za-z0-9_-]{10,})/);
  if (m) return {id: m[2], pasta: m[1] === "folders"};
  const id = u.searchParams.get("id");
  return id && /^[A-Za-z0-9_-]{10,}$/.test(id) ? {id, pasta: false} : null;
}

// ---------- status ----------
function redesDoItem(p) {
  const todas = REDES_POR_TIPO[p.tipo] || [];
  return estado.rede ? todas.filter((r) => r === estado.rede) : todas;
}
function progresso(item) {
  if (estado.visao === "roteiros") {
    return {feitos: ETAPAS.filter(([k]) => item[k]).length, total: ETAPAS.length};
  }
  const redes = redesDoItem(item);
  return {feitos: redes.filter((r) => item[r]).length, total: redes.length};
}
function classeStatus({feitos, total}) {
  return feitos === 0 ? "" : feitos === total ? "pronto" : "parcial";
}
function rotuloTipo(item) {
  if (item.tipo === "reel") return FAIXAS[item.faixa] || (Object.keys(FAIXAS).length ? "Reel extra" : "Reel");
  return NOMES_TIPO[item.tipo] || item.tipo;
}

// ---------- calendário ----------
function intervaloGrade() {
  const ini = estado.mes;
  const inicio = somaDias(ini, -((ini.getDay() + 6) % 7));
  const ultimo = new Date(ini.getFullYear(), ini.getMonth() + 1, 0);
  const fim = somaDias(ultimo, (7 - ultimo.getDay()) % 7);
  return {inicio, fim};
}

async function carregar() {
  const {inicio, fim} = intervaloGrade();
  const grade = $("#grade");
  grade.setAttribute("aria-busy", "true");
  $("#erro-grade").hidden = true;
  const pedido = `${estado.visao}|${iso(inicio)}`;
  estado.pedido = pedido;
  try {
    const itens = await api("GET", `/api/${estado.visao}?de=${iso(inicio)}&ate=${iso(fim)}`);
    if (estado.pedido !== pedido) return; // usuário já mudou de mês/visão
    estado.itens = itens;
    desenhar();
  } catch (e) {
    if (estado.pedido !== pedido) return;
    $("#erro-grade").textContent = e.message;
    $("#erro-grade").hidden = false;
  } finally {
    if (estado.pedido === pedido) grade.setAttribute("aria-busy", "false");
  }
}

function itemVisivel(item) {
  return estado.visao === "roteiros" || redesDoItem(item).length > 0;
}

function desenharItem(item) {
  const p = progresso(item);
  const medidor = estado.visao === "roteiros"
    ? h("span", {class: "vu", "aria-hidden": "true"}, ETAPAS.map(([k]) => h("i", {class: item[k] ? "on" : ""})))
    : h("span", {class: "tally", "aria-hidden": "true"}, redesDoItem(item).map((r) => h("i", {class: item[r] ? "on" : "", title: REDES[r][0]}, REDES[r][1])));
  const estadoTxt = `${p.feitos} de ${p.total} ${estado.visao === "roteiros" ? "etapas" : "redes"}`;
  return h("button", {type: "button", class: `item ${classeStatus(p)}`, draggable: "true", "aria-label": `${rotuloTipo(item)}: ${item.titulo}. ${estadoTxt}. Arraste para outro dia para mudar a data.`,
    onclick: () => abrir(item),
    ondragstart: (e) => { estado.arrastando = item; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(item.id)); e.currentTarget.classList.add("arrastando"); },
    ondragend: (e) => { estado.arrastando = null; e.currentTarget.classList.remove("arrastando"); }},
    h("span", {class: "item-linha"},
      h("span", {class: "item-tag"}, rotuloTipo(item)),
      estado.visao === "posts" && item.hora ? h("span", {}, item.hora) : null,
      item.origem === "agente" ? h("span", {class: "ia", title: "Criado pelos agentes de IA"}, "IA") : null),
    h("span", {class: "item-titulo"}, item.titulo),
    medidor);
}

function desenhar() {
  const {inicio, fim} = intervaloGrade();
  const hoje = iso(new Date());
  const porDia = new Map();
  for (const it of estado.itens) {
    if (!itemVisivel(it)) continue;
    if (!porDia.has(it.data)) porDia.set(it.data, []);
    porDia.get(it.data).push(it);
  }
  const grade = $("#grade");
  grade.replaceChildren();
  for (let d = inicio; d <= fim; d = somaDias(d, 1)) {
    const dia = iso(d);
    const fora = d.getMonth() !== estado.mes.getMonth();
    grade.append(h("section", {class: `dia${fora ? " fora" : ""}${dia === hoje ? " hoje" : ""}`, "aria-label": `${SEM[d.getDay()]} ${d.getDate()}`,
      ondragover: (e) => { if (!estado.arrastando) return; e.preventDefault(); e.currentTarget.classList.add("alvo"); },
      ondragleave: (e) => { if (!e.currentTarget.contains(e.relatedTarget)) e.currentTarget.classList.remove("alvo"); },
      ondrop: (e) => { e.preventDefault(); e.currentTarget.classList.remove("alvo"); moverItem(estado.arrastando, dia); }},
      h("div", {class: "dia-topo"},
        h("span", {class: "dia-num"}, h("span", {class: "dia-sem"}, SEM[d.getDay()]), String(d.getDate())),
        h("button", {type: "button", class: "add", "aria-label": `Adicionar em ${ddmm(dia)}`, onclick: () => abrir(null, dia)}, "+")),
      (porDia.get(dia) || []).map(desenharItem)));
  }
  desenharResumo();
}

async function moverItem(item, dia) {
  if (!item || item.data === dia) return;
  const antes = item.data;
  item.data = dia;
  desenhar(); // mostra já no lugar novo
  try {
    const r = await api("PATCH", `/api/${estado.visao}/${item.id}`, {data: dia});
    Object.assign(item, r);
    aviso(`Movido para ${ddmm(dia)}.`);
  } catch (e) {
    item.data = antes; // o servidor não salvou: volta para onde estava
    desenhar();
    aviso(e.message, true);
  }
}

function desenharResumo() {
  const doMes = estado.itens.filter((i) => deIso(i.data).getMonth() === estado.mes.getMonth() && itemVisivel(i));
  const el = $("#resumo");
  el.replaceChildren();
  if (!doMes.length) {
    el.append(estado.visao === "roteiros" ? "Nenhum roteiro neste mês. Use o + de um dia para adicionar." : "Nenhum post neste mês. Use o + de um dia para adicionar.");
    return;
  }
  if (estado.visao === "roteiros") {
    const prontos = doMes.filter((i) => classeStatus(progresso(i)) === "pronto").length;
    el.append(h("b", {}, String(prontos)), ` de ${doMes.length} roteiros prontos para postar`);
  } else {
    let feitos = 0, total = 0;
    for (const i of doMes) { const p = progresso(i); feitos += p.feitos; total += p.total; }
    const onde = estado.rede ? ` no ${REDES[estado.rede][0]}` : "";
    el.append(h("b", {}, String(feitos)), ` de ${total} publicações feitas${onde}`);
  }
}

function trocarMes(n) {
  estado.mes = new Date(estado.mes.getFullYear(), estado.mes.getMonth() + n, 1);
  atualizarTopo();
  carregar();
}

// ---------- métricas ----------
const TODAS_METRICAS = {instagram: "Instagram", youtube: "YouTube", tiktok: "TikTok"};
let NOMES_METRICA = {...TODAS_METRICAS};
const fmt = (n) => n.toLocaleString("pt-BR");
function dataBr(s) { return `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}`; }

async function carregarMetricas() {
  const alvo = $("#metricas");
  alvo.setAttribute("aria-busy", "true");
  try {
    desenharMetricas(await api("GET", "/api/metricas"));
  } catch (e) {
    alvo.replaceChildren(h("p", {class: "erro-grade"}, e.message));
  } finally {
    alvo.setAttribute("aria-busy", "false");
  }
}

function celulaGanho(g) {
  if (g == null) return h("td", {class: "sem", title: "Ainda não há histórico desse período"}, "—");
  return h("td", {class: g > 0 ? "sobe" : g < 0 ? "desce" : ""}, (g > 0 ? "+" : "") + fmt(g));
}

function desenharMeta(d) {
  const {meta, redes, hoje} = d;
  if (!meta || !redes[meta.rede]) return null;
  const atual = redes[meta.rede].atual;
  const n = atual ? atual.seguidores : 0;
  const pct = Math.min(100, (n / meta.seguidores) * 100);
  const diasRestantes = Math.max(1, Math.round((deIso(meta.data) - deIso(hoje)) / 86400000));
  const porDia = Math.ceil(Math.max(0, meta.seguidores - n) / diasRestantes);
  const g30 = redes[meta.rede].periodos[0].ganho;
  const segs = 20;
  return h("div", {class: "meta"},
    h("div", {class: "meta-topo"},
      h("h2", {}, `Meta: ${fmt(meta.seguidores)} no ${NOMES_METRICA[meta.rede]} até ${dataBr(meta.data)}`),
      h("span", {class: "meta-num"}, `${pct.toFixed(1).replace(".", ",")}%`)),
    h("div", {class: "vu vu-meta", role: "img", "aria-label": `${pct.toFixed(1)}% da meta`},
      Array.from({length: segs}, (_, i) => h("i", {class: (i + 1) * (100 / segs) <= pct + 0.0001 ? "on" : ""}))),
    h("p", {class: "meta-texto"},
      atual ? `Faltam ${fmt(Math.max(0, meta.seguidores - n))} seguidores em ${fmt(diasRestantes)} dias: ritmo necessário de ${fmt(porDia)} por dia.`
            : `Registre o número de seguidores do ${NOMES_METRICA[meta.rede]} para acompanhar a meta.`,
      g30 != null ? ` Ritmo dos últimos 30 dias: ${fmt(Math.round(g30 / 30))} por dia.` : ""));
}

function formMetrica() {
  const hoje = iso(new Date());
  const form = h("form", {class: "lancar"},
    h("h2", {}, "Lançar número à mão"),
    h("p", {class: "dica"}, "Use para redes sem coleta automática (no TikTok, 1 vez por semana basta) ou para corrigir um dia."),
    h("div", {class: "lancar-campos"},
      campo("Rede", "m-rede", h("select", {id: "m-rede", name: "rede"},
        Object.entries(NOMES_METRICA).map(([v, t], i, todas) => h("option", {value: v, selected: v === "tiktok" || (i === 0 && !todas.some(([x]) => x === "tiktok"))}, t)))),
      campo("Seguidores", "m-n", h("input", {id: "m-n", name: "seguidores", inputmode: "numeric", autocomplete: "off", placeholder: "ex.: 1520", required: true})),
      campo("Data", "m-data", h("input", {id: "m-data", name: "data", type: "date", value: hoje, max: hoje})),
      h("button", {type: "submit", class: "primario"}, "Salvar número")),
    h("p", {class: "erro-campo", role: "alert", hidden: true}));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const erro = form.querySelector(".erro-campo");
    const bruto = form.seguidores.value.replace(/[.\s]/g, "");
    if (!/^\d+$/.test(bruto)) { erro.textContent = "Digite só números, por exemplo 1520."; erro.hidden = false; return; }
    const btn = form.querySelector("button");
    btn.disabled = true;
    erro.hidden = true;
    try {
      await api("POST", "/api/metricas", {rede: form.rede.value, seguidores: Number(bruto), data: form.data.value});
      aviso("Número salvo.");
      carregarMetricas();
    } catch (e) {
      erro.textContent = e.message;
      erro.hidden = false;
    } finally {
      btn.disabled = false;
    }
  });
  return form;
}

function desenharMetricas(d) {
  const linhas = Object.keys(NOMES_METRICA).map((rede) => {
    const r = d.redes[rede];
    return h("tr", {},
      h("th", {scope: "row"}, NOMES_METRICA[rede]),
      h("td", {class: "agora"}, r.atual ? fmt(r.atual.seguidores) : "—",
        r.atual ? h("small", {}, ` em ${dataBr(r.atual.data)}${r.atual.origem === "manual" ? " (manual)" : ""}`) : null),
      r.periodos.map((p) => celulaGanho(p.ganho)));
  });
  const desde = Object.values(d.redes).map((r) => r.desde).filter(Boolean).sort()[0];
  $("#metricas").replaceChildren(
    desenharMeta(d),
    h("div", {class: "tabela-wrap"},
      h("table", {class: "tabela"},
        h("caption", {}, "Crescimento de seguidores"),
        h("thead", {}, h("tr", {}, h("th", {scope: "col"}, "Rede"), h("th", {scope: "col"}, "Agora"),
          d.redes[Object.keys(NOMES_METRICA)[0]].periodos.map((p) => h("th", {scope: "col"}, p.nome)))),
        h("tbody", {}, linhas))),
    h("p", {class: "dica"}, desde
      ? `Histórico desde ${dataBr(desde)}. Cada período aparece quando o histórico alcança aquela data.${NOMES_METRICA.youtube ? " No YouTube, a API arredonda acima de mil inscritos." : ""}`
      : "Ainda sem histórico. Se a coleta automática estiver configurada, ela roda todo dia; as outras redes você lança abaixo."),
    formMetrica());
}

function atualizarTopo() {
  const metricas = estado.visao === "metricas";
  $("#metricas").hidden = !metricas;
  $("#calendario").hidden = metricas;
  document.querySelector(".mes").hidden = metricas;
  $("#novo").hidden = metricas;
  $("#resumo").hidden = metricas;
  $("#mes-titulo").textContent = `${MESES[estado.mes.getMonth()]} ${estado.mes.getFullYear()}`;
  document.querySelectorAll("[data-visao]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.visao === estado.visao)));
  document.querySelectorAll("[data-rede]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.rede === estado.rede)));
  $("#filtro").hidden = estado.visao !== "posts" || Object.keys(REDES).length < 2;
  $("#novo").textContent = estado.visao === "roteiros" ? "Novo roteiro" : "Novo post";
}

// ---------- painel ----------
function campo(rotulo, id, controle, extra) {
  return h("div", {class: "campo"}, h("label", {for: id}, rotulo), controle, extra);
}
function segmentoTipo(valor) {
  return h("div", {class: "campo"}, h("span", {class: "grupo-titulo"}, "Tipo"),
    h("div", {class: "segmento", role: "radiogroup", "aria-label": "Tipo"},
      TIPOS[estado.visao].map(([v, t]) =>
        h("label", {}, h("input", {type: "radio", name: "tipo", value: v, checked: valor === v}), t))));
}
function seletorFaixa(valor) {
  if (!Object.keys(FAIXAS).length) return h("input", {type: "hidden", name: "faixa", value: ""});
  return campo("Faixa do dia", "f-faixa", h("select", {id: "f-faixa", name: "faixa"},
    Object.entries(FAIXAS).map(([v, t]) => h("option", {value: v, selected: String(valor) === v}, t)),
    h("option", {value: "", selected: valor == null}, "Reel extra")));
}
function linhaCheck(nome, rotulo, marcado, desc) {
  return h("label", {class: "check"}, h("input", {type: "checkbox", name: nome, checked: !!marcado}),
    h("span", {}, rotulo), desc ? h("small", {}, desc) : null);
}

function abrir(item, dataNova) {
  ultimoFoco = document.activeElement;
  const ehRoteiro = estado.visao === "roteiros";
  const novo = !item;
  const base = item || {tipo: "reel", data: dataNova || iso(new Date()), faixa: 1};
  $("#painel-titulo").textContent = novo ? (ehRoteiro ? "Novo roteiro" : "Novo post") : (ehRoteiro ? "Roteiro" : "Post");
  const form = $("#form");
  form.replaceChildren();
  form.dataset.id = item ? item.id : "";

  if (base.origem === "agente") {
    form.append(h("p", {class: "dica"}, `Criado pelos agentes de IA após sua aprovação${base.ref_externa ? ` (${base.ref_externa})` : ""}.`));
  }
  form.append(segmentoTipo(base.tipo));
  const datas = ehRoteiro
    ? campo("Data", "f-data", h("input", {type: "date", id: "f-data", name: "data", value: base.data, required: true}))
    : h("div", {class: "linha2"},
        campo("Data", "f-data", h("input", {type: "date", id: "f-data", name: "data", value: base.data, required: true})),
        campo("Horário", "f-hora", h("input", {type: "time", id: "f-hora", name: "hora", value: base.hora || ""})));
  form.append(datas, h("div", {id: "bloco-faixa"}, seletorFaixa(base.faixa)),
    campo("Título", "f-titulo", h("input", {id: "f-titulo", name: "titulo", maxlength: "200", value: base.titulo || "", required: true, autocomplete: "off"})));

  if (ehRoteiro) {
    form.append(
      campo("Roteiro", "f-texto", h("textarea", {id: "f-texto", name: "texto", class: "roteiro"}, base.texto || "")),
      h("div", {class: "campo"}, h("span", {class: "grupo-titulo"}, "Produção"),
        h("div", {class: "checks"}, ETAPAS.map(([k, t]) => linhaCheck(k, t, base[k])))));
  } else {
    const preview = h("div", {id: "drive-preview"});
    form.append(
      campo("Legenda", "f-legenda", h("textarea", {id: "f-legenda", name: "legenda", class: "legenda"}, base.legenda || ""),
        novo || !CONFIG.agentes ? null : estadoLegenda(base)),
      campo("Link do vídeo no Google Drive", "f-drive",
        h("input", {id: "f-drive", name: "drive_link", type: "url", inputmode: "url", placeholder: "https://drive.google.com/file/d/...", value: base.drive_link || "",
          oninput: () => mostrarDrive(preview)}),
        preview),
      campo("Roteiro de origem", "f-roteiro", h("select", {id: "f-roteiro", name: "roteiro_id"}, h("option", {value: ""}, "Nenhum"))),
      h("div", {class: "campo"}, h("span", {class: "grupo-titulo"}, "Publicado em"),
        h("div", {class: "checks", id: "redes"}, Object.keys(REDES).map((r) => linhaCheck(r, REDES[r][0], base[r])))));
    mostrarDrive(preview);
    carregarOpcoesRoteiro(base);
    form.querySelector("[name=data]").addEventListener("change", () => carregarOpcoesRoteiro(lerForm()));
  }

  form.append(h("p", {class: "erro-campo", id: "erro-form", role: "alert", hidden: true}),
    h("div", {class: "acoes"},
      h("button", {type: "submit", class: "primario", id: "salvar"}, novo ? (ehRoteiro ? "Criar roteiro" : "Criar post") : "Salvar alterações"),
      novo ? null : h("button", {type: "button", class: "excluir", onclick: excluir}, "Excluir")));

  form.querySelectorAll("[name=tipo]").forEach((r) => r.addEventListener("change", ajustarTipo));
  if (!novo) form.querySelectorAll(".checks input").forEach((c) => c.addEventListener("change", salvarCheck));
  ajustarTipo();

  $("#veu").hidden = false;
  $("#painel").hidden = false;
  (novo ? $("#f-titulo") : $("#fechar")).focus();
}

const TEXTO_STATUS = {
  pendente: "Na fila: os agentes vão escrever a legenda em alguns minutos.",
  gerando: "Os agentes estão escrevendo a legenda agora.",
  pronta: "Legenda escrita pelos agentes. Revise antes de publicar.",
  erro: "Os agentes não conseguiram escrever a legenda depois de 3 tentativas.",
};

function estadoLegenda(base) {
  const st = base.legenda_status;
  const pedir = h("button", {type: "button", class: "leve", onclick: async (ev) => {
    ev.currentTarget.disabled = true;
    try {
      await api("PATCH", `/api/posts/${base.id}`, {legenda_status: "pendente", legenda_tentativas: 0});
      aviso("Pedido enviado aos agentes.");
      fechar();
      carregar();
    } catch (e) {
      aviso(e.message, true);
      ev.currentTarget.disabled = false;
    }
  }}, st ? "Pedir de novo aos agentes" : "Pedir legenda aos agentes");
  return h("div", {class: `legenda-status ${st || ""}`},
    st ? h("span", {}, TEXTO_STATUS[st]) : null,
    st === "pendente" || st === "gerando" ? null : pedir);
}

function ajustarTipo() {
  const form = $("#form");
  const tipo = form.querySelector("[name=tipo]:checked").value;
  $("#bloco-faixa").hidden = tipo !== "reel";
  for (const r of Object.keys(REDES)) {
    const el = form.querySelector(`[name=${r}]`);
    if (el) el.closest(".check").hidden = !(REDES_POR_TIPO[tipo] || []).includes(r);
  }
  const prev = $("#drive-preview");
  if (prev) mostrarDrive(prev);
}

function mostrarDrive(alvo) {
  const link = $("#f-drive") ? $("#f-drive").value : "";
  const d = driveId(link);
  const tipo = $("#form").querySelector("[name=tipo]:checked")?.value || "reel";
  const chave = d ? d.id : "";
  if (alvo.dataset.id === chave && alvo.dataset.tipo === tipo) return;
  alvo.dataset.id = chave;
  alvo.dataset.tipo = tipo;
  alvo.replaceChildren();
  if (!link.trim()) return;
  if (!d) { alvo.append(h("p", {class: "erro-campo"}, "Esse não parece um link de arquivo ou pasta do Google Drive.")); return; }
  const src = d.pasta ? `https://drive.google.com/embeddedfolderview?id=${d.id}#grid` : `https://drive.google.com/file/d/${d.id}/preview`;
  const abrir = d.pasta ? `https://drive.google.com/drive/folders/${d.id}` : `https://drive.google.com/file/d/${d.id}/view`;
  alvo.append(
    h("div", {class: `drive ${d.pasta ? "pasta" : tipo}`}, h("iframe", {src, loading: "lazy", allow: "autoplay; fullscreen", title: "Prévia no Drive"})),
    h("p", {class: "dica"}, "A prévia aparece se este navegador tiver acesso ao Drive. ",
      h("a", {href: abrir, target: "_blank", rel: "noopener"}, "Abrir no Drive")));
}

async function carregarOpcoesRoteiro(base) {
  const sel = $("#f-roteiro");
  if (!sel || !base.data) return;
  const d = deIso(base.data);
  const atual = base.roteiro_id ? String(base.roteiro_id) : sel.value;
  try {
    const lista = await api("GET", `/api/roteiros?de=${iso(somaDias(d, -60))}&ate=${iso(somaDias(d, 14))}`);
    if (!document.body.contains(sel)) return;
    sel.replaceChildren(h("option", {value: ""}, "Nenhum"),
      lista.slice().reverse().map((r) => h("option", {value: String(r.id), selected: String(r.id) === atual}, `${ddmm(r.data)}  ${rotuloTipo(r)}: ${r.titulo}`)));
    if (atual && !lista.some((r) => String(r.id) === atual) && base.roteiro_titulo) {
      sel.append(h("option", {value: atual, selected: true}, base.roteiro_titulo));
    }
  } catch (e) {
    aviso(e.message, true);
  }
}

function lerForm() {
  const f = $("#form");
  const val = (n) => f.querySelector(`[name=${n}]`)?.value ?? "";
  const tipo = f.querySelector("[name=tipo]:checked").value;
  const corpo = {tipo, data: val("data"), titulo: val("titulo"), faixa: tipo === "reel" && val("faixa") ? Number(val("faixa")) : null};
  const marcados = Object.fromEntries([...f.querySelectorAll(".checks input")].map((c) => [c.name, c.checked]));
  if (estado.visao === "roteiros") {
    Object.assign(corpo, {texto: val("texto")}, marcados);
  } else {
    Object.assign(corpo, {hora: val("hora") || null, legenda: val("legenda"), drive_link: val("drive_link").trim(),
      roteiro_id: val("roteiro_id") ? Number(val("roteiro_id")) : null}, marcados);
    for (const r of Object.keys(REDES)) if (!(REDES_POR_TIPO[tipo] || []).includes(r)) corpo[r] = false;
  }
  return corpo;
}

function erroForm(msg) {
  const el = $("#erro-form");
  el.textContent = msg || "";
  el.hidden = !msg;
}

async function salvar(ev) {
  ev.preventDefault();
  const f = $("#form");
  const corpo = lerForm();
  if (!corpo.titulo.trim()) { erroForm("O título é obrigatório."); $("#f-titulo").focus(); return; }
  if (!corpo.data) { erroForm("Escolha uma data."); return; }
  if (corpo.drive_link && !driveId(corpo.drive_link)) { erroForm("Cole um link de arquivo do Google Drive."); $("#f-drive").focus(); return; }
  const btn = $("#salvar");
  btn.disabled = true;
  erroForm("");
  try {
    const id = f.dataset.id;
    await api(id ? "PATCH" : "POST", `/api/${estado.visao}${id ? "/" + id : ""}`, corpo);
    fechar();
    aviso(id ? "Alterações salvas." : (estado.visao === "roteiros" ? "Roteiro criado." : "Post criado."));
    const d = deIso(corpo.data);
    if (d.getMonth() !== estado.mes.getMonth() || d.getFullYear() !== estado.mes.getFullYear()) {
      estado.mes = inicioMes(d);
      atualizarTopo();
    }
    carregar();
  } catch (e) {
    erroForm(e.message); // mantém o que foi digitado
  } finally {
    btn.disabled = false;
  }
}

async function salvarCheck(ev) {
  const c = ev.target;
  const id = $("#form").dataset.id;
  c.disabled = true;
  try {
    const atualizado = await api("PATCH", `/api/${estado.visao}/${id}`, {[c.name]: c.checked});
    const i = estado.itens.findIndex((x) => x.id === atualizado.id);
    if (i >= 0) estado.itens[i] = {...estado.itens[i], ...atualizado};
    desenhar();
    if ("post_criado" in atualizado) {
      if (CONFIG.agentes) {
        aviso(atualizado.post_criado
          ? "Roteiro pronto: post criado na aba Posts. Os agentes vão escrever a legenda."
          : "Roteiro pronto: os agentes vão escrever a legenda do post vinculado.");
      } else if (atualizado.post_criado) {
        aviso("Roteiro pronto: post criado na aba Posts.");
      }
    }
  } catch (e) {
    c.checked = !c.checked; // desfaz: o servidor não salvou
    aviso(e.message, true);
  } finally {
    c.disabled = false;
  }
}

async function excluir() {
  const id = $("#form").dataset.id;
  const titulo = $("#f-titulo").value;
  if (!confirm(`Excluir "${titulo}"? Isso não pode ser desfeito.`)) return;
  try {
    await api("DELETE", `/api/${estado.visao}/${id}`);
    fechar();
    aviso("Excluído.");
    carregar();
  } catch (e) {
    erroForm(e.message);
  }
}

function fechar() {
  $("#painel").hidden = true;
  $("#veu").hidden = true;
  $("#form").replaceChildren();
  if (ultimoFoco && document.body.contains(ultimoFoco)) ultimoFoco.focus();
}

// ---------- eventos ----------
$("#mes-ant").addEventListener("click", () => trocarMes(-1));
$("#mes-prox").addEventListener("click", () => trocarMes(1));
$("#hoje").addEventListener("click", () => { estado.mes = inicioMes(new Date()); atualizarTopo(); carregar(); });
$("#novo").addEventListener("click", () => {
  const hoje = new Date();
  const naTela = hoje.getMonth() === estado.mes.getMonth() && hoje.getFullYear() === estado.mes.getFullYear();
  abrir(null, iso(naTela ? hoje : estado.mes));
});
document.querySelectorAll("[data-visao]").forEach((b) => b.addEventListener("click", () => {
  if (estado.visao === b.dataset.visao) return;
  estado.visao = b.dataset.visao;
  estado.itens = [];
  atualizarTopo();
  if (estado.visao === "metricas") carregarMetricas(); else carregar();
}));
$("#form").addEventListener("submit", salvar);
$("#fechar").addEventListener("click", fechar);
$("#veu").addEventListener("click", fechar);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#painel").hidden) fechar(); });

// ---------- início ----------
function aplicarConfig(c) {
  CONFIG = c;
  FAIXAS = c.faixas;
  ETAPAS = c.etapas;
  REDES = c.redes;
  REDES_POR_TIPO = c.redes_por_tipo;
  TIPOS = c.tipos;
  NOMES_METRICA = Object.fromEntries(c.metricas.redes.map((r) => [r, TODAS_METRICAS[r]]));
  $("#marca-nome").textContent = c.marca.nome;
  $("#marca-sub").textContent = c.marca.subtitulo;
  document.title = `Planner ${c.marca.nome}`;
  $("#aba-metricas").hidden = !c.metricas.ativo;
  const filtro = $("#filtro");
  for (const [r, [nome]] of Object.entries(REDES)) {
    filtro.append(h("button", {type: "button", "data-rede": r, "aria-pressed": "false"}, nome));
  }
  estado.visao = c.visao_inicial === "metricas" && !c.metricas.ativo ? "roteiros" : c.visao_inicial;
}

async function iniciar() {
  try {
    aplicarConfig(await api("GET", "/api/config"));
  } catch (e) {
    $("#erro-grade").textContent = e.message;
    $("#erro-grade").hidden = false;
    return;
  }
  document.querySelectorAll("[data-rede]").forEach((b) => b.addEventListener("click", () => {
    estado.rede = b.dataset.rede;
    atualizarTopo();
    desenhar();
  }));
  atualizarTopo();
  if (estado.visao === "metricas") carregarMetricas(); else carregar();
}

iniciar();
