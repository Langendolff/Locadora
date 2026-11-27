// Painel da Locadora. Sem dependências; todo texto vindo da API entra por textContent.
"use strict";

const $ = (s) => document.querySelector(s);
const AUDIO = { dublado: "Dublado", original: "Original" };
const LEGENDA = { "pt-br": "Legenda PT-BR", en: "Legenda em inglês", nenhuma: "Sem legenda" };
const MARCA = { ok: "✓", aviso: "!", erro: "✗" };

async function api(metodo, caminho, corpo) {
  const opts = { method: metodo, headers: { "X-Locadora": "1" }, credentials: "same-origin" };
  if (corpo !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(corpo);
  }
  let resp;
  try {
    resp = await fetch(caminho, opts);
  } catch {
    throw new Error("Sem resposta do painel. O servidor está ligado?");
  }
  const dados = await resp.json().catch(() => ({}));
  if (resp.status === 401 && caminho !== "/api/entrar") {
    mostrarLogin();
    throw new Error(dados.erro || "Entre de novo.");
  }
  if (!resp.ok) throw new Error(dados.erro || `Erro ${resp.status}`);
  return dados;
}

function el(tag, attrs = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const f of filhos) if (f) e.append(f);
  return e;
}

let temporizador;
function avisar(msg, erro = false) {
  const a = $("#toast");
  a.textContent = msg;
  a.classList.toggle("erro", erro);
  a.hidden = false;
  clearTimeout(temporizador);
  temporizador = setTimeout(() => (a.hidden = true), erro ? 7000 : 3500);
}

function ocupado(botao, sim, texto) {
  if (sim) {
    botao.dataset.texto = botao.textContent;
    botao.disabled = true;
    botao.replaceChildren(el("span", { class: "girando", "aria-hidden": "true" }), " " + texto);
  } else {
    botao.disabled = false;
    botao.textContent = botao.dataset.texto;
  }
}

// ---------- login
function mostrarLogin() {
  $("#tela-painel").hidden = true;
  $("#tela-login").hidden = false;
  $("#form-login [name=usuario]").focus();
}

function mostrarPainel() {
  $("#tela-login").hidden = true;
  $("#tela-painel").hidden = false;
  carregarPessoas();
}

$("#form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, botao = f.querySelector("button");
  $("#erro-login").textContent = "";
  ocupado(botao, true, "Entrando…");
  try {
    await api("POST", "/api/entrar", { usuario: f.usuario.value.trim(), senha: f.senha.value });
    f.senha.value = "";
    mostrarPainel();
  } catch (e) {
    $("#erro-login").textContent = e.message;
  } finally {
    ocupado(botao, false);
  }
});

$("#sair").addEventListener("click", async () => {
  await api("POST", "/api/sair", {}).catch(() => {});
  mostrarLogin();
});

// ---------- abas
const AO_ABRIR = { config: () => carregarConfig(), manutencao: () => carregarManutencao() };
function abrirAba(nome) {
  document.querySelectorAll(".abas button").forEach((o) => o.setAttribute("aria-selected", o.dataset.aba === nome));
  document.querySelectorAll("[role=tabpanel]").forEach((p) => (p.hidden = p.id !== "aba-" + nome));
  AO_ABRIR[nome]?.();
}
document.querySelectorAll(".abas button").forEach((b) => b.addEventListener("click", () => abrirAba(b.dataset.aba)));

// ---------- pessoas
function seletor(opcoes, atual, rotulo) {
  const s = el("select", { "aria-label": rotulo });
  for (const [v, t] of Object.entries(opcoes)) {
    const o = el("option", { value: v, text: t });
    if (v === atual) o.selected = true;
    s.append(o);
  }
  return s;
}

function linhaPessoa(p) {
  const audio = seletor(AUDIO, p.audio, `Áudio de ${p.nome}`);
  const legenda = seletor(LEGENDA, p.legenda, `Legenda de ${p.nome}`);
  const nome = el("div", { class: "nome" }, el("span", { text: p.nome }));
  if (p.admin) nome.append(el("span", { class: "selo admin", text: "admin" }));
  if (!p.no_seerr) nome.append(el("span", { class: "selo", text: "ainda não entrou no Seerr", title: "A conta no Seerr é criada no primeiro login da pessoa ou quando a preferência é mudada aqui" }));
  const linha = el("div", { class: "pessoa" }, nome, audio, legenda);

  let anterior = { audio: p.audio, legenda: p.legenda };
  const salvar = async () => {
    linha.classList.add("salvando");
    audio.disabled = legenda.disabled = true;
    try {
      const r = await api("POST", "/api/pessoas/preferencia", { nome: p.nome, audio: audio.value, legenda: legenda.value });
      anterior = { audio: audio.value, legenda: legenda.value };
      avisar(r.ok);
    } catch (e) {
      audio.value = anterior.audio;
      legenda.value = anterior.legenda;
      avisar(e.message, true);
    } finally {
      linha.classList.remove("salvando");
      audio.disabled = legenda.disabled = false;
    }
  };
  audio.addEventListener("change", salvar);
  legenda.addEventListener("change", salvar);
  return linha;
}

async function carregarPessoas() {
  const lista = $("#lista-pessoas");
  lista.replaceChildren(el("p", { class: "carregando" }, el("span", { class: "girando" }), " Carregando…"));
  try {
    const { pessoas } = await api("GET", "/api/pessoas");
    lista.replaceChildren(...(pessoas.length ? pessoas.map(linhaPessoa)
      : [el("p", { class: "vazio", text: "Ninguém cadastrado ainda." })]));
  } catch (e) {
    lista.replaceChildren(el("p", { class: "vazio", text: e.message }));
  }
}

const formNova = $("#form-nova");
$("#abrir-nova").addEventListener("click", () => {
  formNova.hidden = false;
  formNova.nome.focus();
});
$("#cancelar-nova").addEventListener("click", () => {
  formNova.reset();
  formNova.hidden = true;
  $("#erro-nova").textContent = "";
});
formNova.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = formNova, botao = f.querySelector("button[type=submit]");
  const erro = $("#erro-nova");
  erro.textContent = "";
  if (f.senha.value !== f.senha2.value) {
    erro.textContent = "As senhas não conferem.";
    return;
  }
  ocupado(botao, true, "Cadastrando…");
  try {
    const r = await api("POST", "/api/pessoas/nova", {
      nome: f.nome.value.trim(), senha: f.senha.value, audio: f.audio.value, legenda: f.legenda.value,
    });
    avisar(r.ok);
    f.reset();
    f.hidden = true;
    carregarPessoas();
  } catch (e) {
    erro.textContent = e.message;
  } finally {
    ocupado(botao, false);
  }
});

// ---------- diagnóstico
$("#rodar-diag").addEventListener("click", async (ev) => {
  const botao = ev.currentTarget, resumo = $("#resumo-diag"), saida = $("#resultado-diag");
  ocupado(botao, true, "Conferindo…");
  resumo.replaceChildren();
  saida.replaceChildren(el("p", { class: "carregando", text: "Conferindo cada serviço. Leva até um minuto." }));
  try {
    const r = await api("POST", "/api/diagnostico", {});
    const secoes = new Map();
    for (const it of r.itens) {
      if (!secoes.has(it.secao)) secoes.set(it.secao, []);
      secoes.get(it.secao).push(it);
    }
    saida.replaceChildren(...[...secoes].map(([nome, itens]) =>
      el("div", { class: "secao cartao" }, el("h3", { text: nome }),
        ...itens.map((it) => el("div", { class: "item " + it.nivel },
          el("span", { class: "marca-item", "aria-label": it.nivel, text: MARCA[it.nivel] }),
          el("div", {}, el("div", { text: it.msg }), it.dica ? el("div", { class: "dica", text: it.dica }) : null))))));
    const [classe, texto] = r.erros ? ["erro", `${r.erros} problema(s) e ${r.avisos} aviso(s). Comece pelo primeiro ✗ da lista.`]
      : r.avisos ? ["aviso", `Funcionando, com ${r.avisos} aviso(s).`] : ["ok", "Tudo certo."];
    resumo.replaceChildren(el("div", { class: "resumo " + classe, text: texto }));
    $("#nota-diag").hidden = r.completo;
  } catch (e) {
    saida.replaceChildren();
    resumo.replaceChildren(el("div", { class: "resumo erro", text: e.message }));
  } finally {
    ocupado(botao, false);
  }
});

// ---------- configurações
let campos = [];
async function carregarConfig() {
  const alvo = $("#campos-config");
  $("#erro-config").textContent = "";
  try {
    const r = await api("GET", "/api/config");
    campos = r.campos;
    alvo.replaceChildren(...r.grupos.map((g) => {
      const doGrupo = campos.filter((c) => c.grupo === g.id);
      return el("fieldset", { class: "cartao grupo" }, el("h3", { text: g.nome }),
        el("div", { class: "grade" }, ...doGrupo.map(campoConfig)));
    }));
    $("#salvar-config").hidden = false;
  } catch (e) {
    alvo.replaceChildren(el("p", { class: "vazio", text: e.message }));
    $("#salvar-config").hidden = true;
  }
}

function campoConfig(c) {
  const segredo = c.tipo === "segredo";
  const input = el("input", {
    name: c.chave, autocomplete: "off", spellcheck: "false",
    type: segredo ? "password" : (c.tipo === "porta" || c.tipo === "numero") ? "number" : c.tipo === "email" ? "email" : "text",
  });
  if (segredo) input.placeholder = c.definido ? "preenchido (em branco = manter)" : "vazio";
  else input.value = c.valor;
  if (c.tipo === "porta") { input.min = 1024; input.max = 65535; input.required = true; }
  if (c.tipo === "numero") { input.min = 1; input.max = 3650; }
  if (c.tipo === "pasta") { input.required = true; input.placeholder = "/mnt/hd/locadora"; }
  const rotulo = el("label", { class: "campo" }, el("span", { text: c.rotulo }), input);
  if (segredo && c.definido) {
    const caixa = el("input", { type: "checkbox", name: c.chave + "__remover" });
    caixa.addEventListener("change", () => { input.disabled = caixa.checked; if (caixa.checked) input.value = ""; });
    rotulo.append(el("label", { class: "remover" }, caixa, "remover"));
  }
  if (c.ajuda) rotulo.append(el("span", { class: "ajuda", text: c.ajuda }));
  return rotulo;
}

$("#form-config").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, botao = $("#salvar-config"), erro = $("#erro-config");
  erro.textContent = "";
  const valores = {};
  for (const c of campos) {
    const v = f.elements[c.chave].value.trim();
    if (c.tipo === "segredo") {
      if (f.elements[c.chave + "__remover"]?.checked) valores[c.chave] = "";
      else if (v) valores[c.chave] = v;
    } else if (v !== c.valor) {
      valores[c.chave] = v;
    }
  }
  if (!Object.keys(valores).length) { avisar("Nada mudou."); return; }
  if ("DATA_ROOT" in valores && !confirm(
    `Mudar a pasta dos filmes e séries para ${valores.DATA_ROOT}?\n\n` +
    "Nada é movido: o que está na pasta de agora fica lá. Para levar a biblioteca, mova as pastas " +
    "media/ e torrents/ para a pasta nova ANTES de aplicar; senão o Jellyfin mostra a biblioteca vazia " +
    "e os downloads em andamento se perdem.")) return;
  ocupado(botao, true, "Salvando…");
  try {
    const r = await api("POST", "/api/config", { valores });
    if (r.mudou.length) {
      $("#faixa-aplicar").hidden = false;
      avisar(`Salvo: ${r.mudou.join(", ")}`);
    } else {
      avisar("Nada mudou.");
    }
    await carregarConfig();
  } catch (e) {
    erro.textContent = e.message;
  } finally {
    ocupado(botao, false);
  }
});

$("#aplicar").addEventListener("click", async (ev) => {
  if (await iniciarTarefa({ acao: "aplicar" }, ev.currentTarget)) $("#faixa-aplicar").hidden = true;
});

$("#form-senha").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, erro = $("#erro-senha");
  erro.textContent = "";
  if (f.senha.value !== f.senha2.value) { erro.textContent = "As senhas não conferem."; return; }
  if (f.senha.value.length < 8) { erro.textContent = "A senha precisa ter pelo menos 8 caracteres."; return; }
  if (!confirm("Trocar a senha do admin em todos os serviços?")) return;
  if (await iniciarTarefa({ acao: "senha", senha: f.senha.value }, f.querySelector("button"))) f.reset();
});

// ---------- manutenção
const ESTADO = { rodando: "rodando…", ok: "concluída", falhou: "falhou" };
let linhasLidas = 0, acompanhando = false, idTarefa = "", rodando = false;

async function iniciarTarefa(corpo, botao) {
  ocupado(botao, true, "Começando…");
  try {
    await api("POST", "/api/tarefa", corpo);
    abrirAba("manutencao");
    return true;
  } catch (e) {
    avisar(e.message, true);
    return false;
  } finally {
    ocupado(botao, false);
  }
}

function tamanho(b) {
  return b > 1e9 ? (b / 1e9).toFixed(1) + " GB" : Math.max(1, Math.round(b / 1e6)) + " MB";
}

async function carregarBackups() {
  const lista = $("#lista-backups");
  try {
    const { backups } = await api("GET", "/api/backups");
    lista.replaceChildren(...(backups.length ? backups.map((b) => {
      const quando = new Date(b.data * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
      const botao = el("button", { class: "botao fantasma", text: "Restaurar", "data-trava": "" });
      if (rodando) botao.disabled = true;
      botao.addEventListener("click", () => {
        if (confirm(`Voltar as configurações para o backup de ${quando}?\n\nAs de agora ficam guardadas numa pasta config.antes-… . Filmes e séries não são tocados.`))
          iniciarTarefa({ acao: "restaurar", arquivo: b.arquivo }, botao);
      });
      return el("div", { class: "backup" },
        el("div", { class: "info" }, el("span", { text: quando }), el("small", { text: `${b.arquivo} · ${tamanho(b.tamanho)}` })),
        botao);
    }) : [el("p", { class: "vazio", text: "Nenhum backup ainda." })]));
  } catch (e) {
    lista.replaceChildren(el("p", { class: "vazio", text: e.message }));
  }
}

async function carregarManutencao() {
  carregarBackups();
  if (!acompanhando) acompanhar();
}

function mostrarTarefa(t) {
  $("#tarefa").hidden = !t;
  if (!t) return;
  $("#tarefa-nome").textContent = t.nome;
  const s = $("#tarefa-estado");
  s.textContent = ESTADO[t.estado] || t.estado;
  s.className = "selo " + t.estado;
  document.querySelectorAll("[data-acao], [data-trava]").forEach((b) => (b.disabled = t.estado === "rodando"));
}

async function acompanhar() {
  acompanhando = true;
  const log = $("#tarefa-log");
  try {
    let r = await api("GET", `/api/tarefa?desde=${linhasLidas}`);
    const id = r.tarefa ? r.tarefa.acao + r.tarefa.inicio : "";
    if (id !== idTarefa) {  // outra tarefa (ou a primeira vez): começa a saída do zero
      idTarefa = id;
      log.textContent = "";
      if (linhasLidas) { linhasLidas = 0; r = await api("GET", "/api/tarefa?desde=0"); }
    }
    if (r.linhas.length) {
      const noFim = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
      log.textContent += (log.textContent ? "\n" : "") + r.linhas.join("\n");
      if (noFim) log.scrollTop = log.scrollHeight;
    }
    linhasLidas = r.total;
    mostrarTarefa(r.tarefa);
    const antes = rodando;
    rodando = r.tarefa?.estado === "rodando";
    if (rodando) return void setTimeout(acompanhar, 2000);
    if (antes && r.tarefa.acao === "senha" && r.tarefa.estado === "ok") avisar("Senha trocada. Entre de novo com a senha nova.");
    if (antes) carregarBackups();
  } catch (e) {
    // Durante a atualização o painel e o operador reiniciam: tenta de novo até voltarem
    if (rodando && !$("#tela-painel").hidden) {
      $("#tarefa-estado").textContent = "reconectando…";
      return void setTimeout(acompanhar, 3000);
    }
    if ($("#tarefa").hidden) avisar(e.message, true);
  }
  acompanhando = false;
}

document.querySelectorAll("[data-acao]").forEach((b) => b.addEventListener("click", () => {
  const msg = b.dataset.acao === "atualizar"
    ? "Atualizar a Locadora agora? Os serviços ficam fora do ar por alguns minutos."
    : "Fazer um backup agora? Os serviços param enquanto as configurações são copiadas.";
  if (confirm(msg)) iniciarTarefa({ acao: b.dataset.acao }, b);
}));

// ---------- início
api("GET", "/api/eu").then(mostrarPainel, () => {});
