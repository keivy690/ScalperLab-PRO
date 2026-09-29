(() => {
  "use strict";

  const TOKEN = document.querySelector('meta[name="app-token"]')?.content || "";
  const state = { snapshot: null, strategyFilter: "all", research: [], marketWatch: null,
    marketWatchTerminal: null, marketWatchLoading: false, selectedAnalystSymbols: null,
    dashboardShowAll: false, logFilter: "all" };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const api = async (path, options = {}) => {
    const { timeoutMs = 0, ...fetchOptions } = options;
    const headers = { "X-ScalperLab-Token": TOKEN, ...(options.headers || {}) };
    if (fetchOptions.body) headers["Content-Type"] = "application/json";
    const controller = timeoutMs ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    let response;
    try {
      response = await fetch(path, { ...fetchOptions, headers, cache: "no-store",
        ...(controller ? { signal: controller.signal } : {}) });
    } catch (error) {
      if (error.name === "AbortError") throw new Error("A consulta excedeu o tempo limite. Tente atualizar novamente.");
      throw error;
    } finally {
      if (timer) clearTimeout(timer);
    }
    let body;
    try { body = await response.json(); } catch { body = {}; }
    if (!response.ok) throw new Error(body.error || body.detail || `Falha local HTTP ${response.status}`);
    return body;
  };

  function toast(message, kind = "") {
    const node = document.createElement("div");
    node.className = `toast ${kind}`;
    node.textContent = message;
    $("#toast-region").append(node);
    setTimeout(() => node.remove(), 5200);
  }

  function logLine(message, kind = "") {
    const out = $("#terminal-output");
    if (!out) return;
    if (out.querySelector(".muted-line")) out.replaceChildren();
    const line = document.createElement("div");
    line.className = `terminal-line ${kind}`;
    const time = document.createElement("span");
    time.className = "terminal-time";
    time.textContent = new Date().toLocaleTimeString("pt-BR", { hour12: false });
    line.append(time, document.createTextNode(message));
    out.append(line);
    out.scrollTop = out.scrollHeight;
    while (out.children.length > 40) out.firstElementChild.remove();
    $("#terminal-update").textContent = new Date().toLocaleTimeString("pt-BR", { hour12: false });
  }

  function money(value, currency = "") {
    if (typeof value !== "number" || !Number.isFinite(value)) return "—";
    return new Intl.NumberFormat("pt-BR", { style: "currency", currency: currency || "BRL", maximumFractionDigits: 2 }).format(value);
  }

  function number(value, digits = 5) {
    return typeof value === "number" && Number.isFinite(value)
      ? new Intl.NumberFormat("pt-BR", { maximumFractionDigits: digits }).format(value) : "—";
  }

  function serverTimeNote(item) {
    const normalization = item?.time_normalization;
    const offset = normalization?.bar_offset_applied_seconds
      ?? normalization?.server_utc_offset_seconds;
    if (typeof offset !== "number" || !Number.isFinite(offset)) return "";
    const coverage = normalization?.bars_dropped_for_time_validation > 0
      ? ` · ${normalization.bars_used}/${normalization.bars_received} candles: trecho contínuo recente` : "";
    if (offset === 0) return ` · Candles recebidos em UTC${coverage}`;
    const sign = offset < 0 ? "−" : "+";
    const absolute = Math.abs(Math.trunc(offset));
    const hours = String(Math.floor(absolute / 3600)).padStart(2, "0");
    const minutes = String(Math.floor((absolute % 3600) / 60)).padStart(2, "0");
    return ` · Candles UTC${sign}${hours}:${minutes}, convertidos para UTC${coverage}`;
  }

  function runtimeDescriptor(name, runtime = {}) {
    if (runtime.running) {
      const mode = runtime.mode || "observacao";
      const executionMode = ["demo", "real"].includes(mode);
      const modeLabel = mode === "observacao" ? "OBSERVAÇÃO" : mode.toUpperCase();
      return {
        running: true, mode,
        header: name.toUpperCase() + " · " + (executionMode ? "EXECUÇÃO " : "") + modeLabel,
        metric: mode === "observacao" ? "Observação ativa" : name + " · " + modeLabel,
        badge: mode === "observacao" ? "OBSERVANDO" : modeLabel + " AUTOMÁTICO",
        detail: runtime.detail || name + " em " + modeLabel.toLowerCase() + ".",
        kind: executionMode ? "approved" : "review",
      };
    }
    if (["bloqueado_relogio", "resultado_desconhecido"].includes(runtime.phase)) {
      return {
        running: false, blocked: true, mode: "blocked",
        header: name.toUpperCase() + " · EXECUÇÃO BLOQUEADA",
        metric: "Execução bloqueada",
        badge: runtime.phase === "resultado_desconhecido" ? "CONFERIR MT5" : "EXECUÇÃO BLOQUEADA",
        detail: runtime.detail || "A execução foi bloqueada; confira o MT5 antes de iniciar novamente.",
        kind: "rejected",
      };
    }
    return { running: false, blocked: false, mode: "stopped", header: "", metric: "", badge: "PARADO", detail: "", kind: "" };
  }

  function operationalStatus(snapshot = {}) {
    const analyst = runtimeDescriptor("Analista", snapshot.analyst?.state || {});
    const strategies = runtimeDescriptor("Estratégias", snapshot.engine?.state || {});
    const active = [analyst, strategies].filter((runtime) => runtime.running);
    const blocked = [analyst, strategies].filter((runtime) => runtime.blocked);
    const represented = [...active, ...blocked];
    const realAccount = ["REAL", "CONTEST"].includes(snapshot.mt5?.account?.mode);
    if (represented.length) {
      return {
        header: represented.map((runtime) => runtime.header).join(" + "),
        metric: active.length > 1 ? active.length + " motores ativos"
          : active.length === 1 ? active[0].metric : "Execução bloqueada",
        detail: represented.map((runtime) => runtime.detail).join(" · "),
        kind: blocked.length ? "rejected"
          : active.some((runtime) => runtime.mode === "demo" || runtime.mode === "real") ? "approved" : "review",
        tone: blocked.length || realAccount || active.some((runtime) => runtime.mode === "real") ? "red-value"
          : active.length ? "green-value" : "",
      };
    }
    return {
      header: "AUTOMAÇÃO PARADA",
      metric: "Motores parados",
      detail: realAccount ? "Conta REAL conectada; nenhuma automação está ativa."
        : "Analista e motor de estratégias parados.",
      kind: "",
      tone: realAccount ? "red-value" : "",
    };
  }

  function executionStatusLabel(value) {
    const labels = {
      CONFIRMADA_MT5: "ORDEM CONFIRMADA NO MT5",
      ACEITA_AGUARDANDO_RECONCILIACAO: "ACEITA · AGUARDANDO RECONCILIAÇÃO",
      RESULTADO_DESCONHECIDO: "RESULTADO DESCONHECIDO · CONFERIR MT5",
      BLOQUEADO_RELOGIO_UTC: "BLOQUEADA · VALIDAR UTC",
      NAO_EXECUTADA: "NÃO EXECUTADA",
      SINAL_NAO_CONFIRMADO: "SEM SINAL ELEGÍVEL",
      SINAL_JA_PROCESSADO: "SINAL JÁ PROCESSADO",
    };
    return labels[value] || String(value).replaceAll("_", " ");
  }

  function renderConnection(mt5) {
    const connected = Boolean(mt5?.connected);
    const account = mt5?.account;
    const dotClass = connected ? "state-dot" : "state-dot muted";
    $("#runtime-dot").className = dotClass;
    $("#runtime-label").textContent = connected ? "Terminal MT5 conectado" : "Aguardando conexão MT5";
    $("#header-account").textContent = account ? `Conta ${account.mode} · ${account.login}` : "Conta indisponível";
    $("#header-server").textContent = account?.server || "Servidor indisponível";
    $("#footer-data-status").textContent = connected ? `Conta ${account.mode}` : "Sem conexão";
    $("#demo-armed-label").textContent = mt5?.demo_armed ? "ARMADO" : "DESARMADO";
    $("#real-close-armed-label").textContent = mt5?.real_close_armed ? "ARMADO" : "DESARMADO";
    $("#settings-real-close-state").textContent = mt5?.real_close_armed ? "ARMADO" : "DESARMADO";
    $("#real-trading-label").textContent = account?.mode === "REAL" ? "CONFIRMAÇÃO POR INÍCIO" : "DESARMADA";
    $("#risk-demo-state").textContent = mt5?.demo_armed ? "ARMADO" : "DESARMADO";
    $("#arm-demo").textContent = mt5?.demo_armed ? "Fechamento armado" : "Armar fechamento";
    $("#arm-demo").disabled = Boolean(mt5?.demo_armed);
    const emergency = mt5?.emergency_action || {};
    const emergencyLabels = {
      idle: [`FECHAR POSIÇÕES ${account?.mode === "REAL" ? "REAL" : "DEMO"}`, "PARADA DE EMERGÊNCIA", "PROTEGIDO"],
      completed: [emergency.remaining_count === 0 ? "FECHAMENTO CONFIRMADO" : "PARADA CONFIRMADA", "PARADA CONFIRMADA", "PARADA ACIONADA"],
      partial: ["FECHAMENTO PARCIAL", "EMERGÊNCIA PARCIAL", "AÇÃO PARCIAL"],
      unknown: ["CONFIRMAÇÃO PENDENTE", "CONFIRMAÇÃO PENDENTE", "VERIFICAR MT5"],
      failed: ["AÇÃO NÃO CONFIRMADA", "PARADA NÃO CONFIRMADA", "AÇÃO NÃO CONFIRMADA"],
      blocked: ["AÇÃO BLOQUEADA", "AÇÃO BLOQUEADA", "BLOQUEADO"],
    };
    const emergencyState = emergencyLabels[emergency.status] || emergencyLabels.idle;
    $("#emergency-button-label").textContent = emergencyState[0];
    $("#sidebar-emergency-label").textContent = emergencyState[1];
    const sidebarEmergency = $("#sidebar-emergency");
    sidebarEmergency.dataset.compactLabel = emergency.status === "completed" ? "Confirmada"
      : emergency.status === "idle" ? "Emergência" : "Verificar";
    sidebarEmergency.setAttribute("aria-label", emergencyState[1]);
    $("#risk-badge").textContent = emergencyState[2];
    $("#risk-badge").classList.toggle("risk-badge-success", emergency.status === "completed");
    $("#emergency-result").textContent = emergency.detail || "Aguardando comando de emergência nesta sessão.";
    $("#emergency-stop").title = emergency.updated_at
      ? `Última ação: ${new Date(emergency.updated_at).toLocaleString("pt-BR")}` : "Solicitar parada do motor e fechamento DEMO com confirmação";
    $("#test-demo-order").disabled = !(connected && account?.mode === "DEMO");

  }


  function renderOperationalStatus(snapshot) {
    const status = operationalStatus(snapshot);
    $("#automation-mode").textContent = status.header;
    $("#automation-mode").className = "status-chip " + status.kind;
    $("#kpi-risk").textContent = status.metric;
    $("#kpi-risk").className = "kpi-value " + status.tone;
    $("#kpi-risk-detail").textContent = status.detail;
  }

  function renderClockStatus(clock = {}) {
    const node = $("#clock-health");
    const button = $("#clock-sync-button");
    if (!node || !button) return;
    const analyst = state.snapshot?.analyst?.state || {};
    const engine = state.snapshot?.engine?.state || {};
    const executionActive = [analyst, engine].some((runtime) =>
      runtime.running && ["demo", "real"].includes(runtime.mode));
    const stateNames = {
      not_checked: "not-checked",
      checking: "checking",
      system_synchronized: "checking",
      synchronized: "success",
      mt5_unverified: "warning",
      error: "error",
      unsupported: "warning",
      expired: "warning",
    };
    node.className = `clock-health ${stateNames[clock.status] || "not-checked"}`;
    button.disabled = clock.status === "checking" || clock.status === "system_synchronized" || executionActive;
    button.title = executionActive
      ? "Pare a execução DEMO/REAL antes de corrigir o relógio"
      : "Verificar e corrigir o horário do Windows e do MT5";
    button.setAttribute("aria-busy", String(button.disabled));
    const labels = {
      not_checked: "Horário ainda não validado nesta sessão. Ao iniciar o Analista, o sistema fará uma verificação automática somente de leitura.",
      checking: "Verificando o serviço Windows Time e a diferença para a fonte UTC…",
      system_synchronized: clock.detail || "Windows sincronizado; confirmando o horário do terminal MT5…",
      error: clock.detail || "Não foi possível validar o horário. A execução permanece bloqueada.",
      unsupported: clock.detail || "Verificação de horário indisponível neste sistema.",
      mt5_unverified: `${clock.detail || "UTC do MT5 não confirmado."} ${clock.mt5_detail || ""}`.trim(),
      expired: clock.monitor_enabled && clock.monitor_status === "retrying"
        ? `${clock.detail || "A confirmação UTC venceu."} `
          + `Próxima tentativa automática em ${Math.max(1, Math.ceil((clock.next_check_in_seconds || 0) / 60))} min.`
        : clock.detail || "Validação expirada. Verifique o horário UTC novamente.",
    };
    if (clock.status === "synchronized") {
      const offset = typeof clock.ntp_offset_seconds === "number"
        ? ` · diferença da fonte ${number(clock.ntp_offset_seconds, 3)}s` : "";
      const serverOffset = typeof clock.mt5_server_utc_offset_seconds === "number"
        ? ` · servidor MT5 UTC${clock.mt5_server_utc_offset_seconds < 0 ? "−" : "+"}${String(Math.floor(Math.abs(clock.mt5_server_utc_offset_seconds) / 3600)).padStart(2, "0")}:${String(Math.floor((Math.abs(clock.mt5_server_utc_offset_seconds) % 3600) / 60)).padStart(2, "0")}` : "";
      const coverage = clock.mt5_symbols_total
        ? ` · ${clock.mt5_symbols_checked}/${clock.mt5_symbols_total} ativos verificados` : "";
      const retrying = clock.monitor_enabled && clock.monitor_status === "retrying";
      const nextCheck = Number.isFinite(clock.next_check_in_seconds)
        ? ` em ${Math.max(1, Math.ceil(clock.next_check_in_seconds / 60))} min` : "";
      const monitor = clock.monitor_enabled
        ? retrying
          ? ` · revalidação automática tentando novamente; confirmação atual válida por ${Math.ceil(clock.proof_expires_in_seconds || 0)} s`
          : ` · revalidação automática ativa${nextCheck}`
        : "";
      node.textContent = `Horário sincronizado · UTC confirmado no Windows e no MT5${offset}${serverOffset}${coverage}${monitor}.`;
    } else {
      node.textContent = labels[clock.status] || labels.not_checked;
    }
    if (executionActive) node.textContent += " Pare a execução DEMO/REAL antes de sincronizar o relógio.";
    button.innerHTML = clock.status === "checking" || clock.status === "system_synchronized"
      ? '<span class="clock-spinner" aria-hidden="true"></span><b>Verificando horário…</b>'
      : '<span><svg class="icon"><use href="#icon-clock"/></svg></span><b>Verificar horário UTC</b>';
  }

  function renderOrders(result, account) {
    const allRows = result?.available ? result.items : null;
    const caption = result?.available ? `${allRows.length} posição(ões) retornadas pelo terminal` : (result?.detail || "Consulta MT5 indisponível");
    $("#orders-caption").textContent = caption;
    $("#all-orders-caption").textContent = caption;
    $("#position-count").textContent = result?.available ? `${allRows.length} posições` : "— posições";
    $("#all-position-count").textContent = result?.available ? `${allRows.length} posição(ões)` : "Indisponível";
    $("#kpi-positions").textContent = result?.available ? String(allRows.length) : "—";
    $("#kpi-orders-detail").textContent = result?.available ? "Atualizado do MT5" : (result?.detail || "Consulta MT5 indisponível");
    if (allRows) {
      const total = allRows.reduce((sum, item) => sum + item.profit, 0);
      $("#orders-profit").textContent = money(total, account?.currency);
      $("#orders-profit").className = total >= 0 ? "positive" : "negative";
    } else {
      $("#orders-profit").textContent = "—";
      $("#orders-profit").className = "";
    }
    const markup = !result?.available
      ? `<tr><td colspan="10" class="empty-cell">${escapeHtml(result?.detail || "Conecte o terminal MT5 para consultar posições.")}</td></tr>`
      : !allRows.length
        ? '<tr><td colspan="10" class="empty-cell">Nenhuma posição aberta foi retornada pelo terminal.</td></tr>'
        : allRows.map((item) => {
          const profitClass = item.profit >= 0 ? "positive" : "negative";
          const closeEnabled = account?.mode === "DEMO" ? state.snapshot?.mt5?.demo_armed
            : account?.mode === "REAL" ? state.snapshot?.mt5?.real_close_armed : false;
          return `<tr><td>#${escapeHtml(item.ticket)}</td><td><strong>${escapeHtml(item.symbol)}</strong></td><td><span class="type-chip ${item.type === "SELL" ? "sell" : ""}">${escapeHtml(item.type)}</span></td><td class="right">${number(item.volume, 3)}</td><td class="right">${number(item.price_open, 8)}</td><td class="right">${number(item.price_current, 8)}</td><td class="right">${number(item.sl, 8)}</td><td class="right">${number(item.tp, 8)}</td><td class="right ${profitClass}">${money(item.profit, account?.currency)}</td><td><button class="close-order" data-close-ticket="${escapeHtml(item.ticket)}" ${closeEnabled ? "" : "disabled title=\"Arme o fechamento para esta conta\""}>Fechar</button></td></tr>`;
        }).join("");
    $("#dashboard-orders").innerHTML = markup;
    $("#all-orders").innerHTML = markup;
  }

  const statusPt = { draft: "Rascunho", review: "Em revisão", approved: "Aprovada", rejected: "Rejeitada" };
  function strategyCard(item) {
    const detail = item.description || "Sem descrição.";
    const type = item.source_type === "description" ? "DESCRIÇÃO" : item.source_type.toUpperCase();
    const validation = item.validation?.summary || "Aguardando validação";
    const warnings = item.validation?.warnings || [];
    const safeStatus = `<span class="status-chip ${escapeHtml(item.status)}">${escapeHtml(statusPt[item.status] || item.status)}</span>`;
    const tags = `<div class="tag-row"><span class="tag">${escapeHtml(type)}</span>${item.file_name ? `<span class="tag">${escapeHtml(item.file_name)}</span>` : ""}</div>`;
    const actions = `${item.file_name ? `<button class="text-button" data-source-id="${item.id}">Ver arquivo</button>` : ""}${item.status === "draft" ? `<button class="text-button" data-review-id="${item.id}" data-review-status="review">Enviar para revisão</button>` : ""}${item.status === "review" ? `<button class="text-button" data-review-id="${item.id}" data-review-status="approved">Aprovar para estudo demo</button><button class="text-button" data-review-id="${item.id}" data-review-status="rejected">Rejeitar</button>` : ""}`;
    const stamp = Number.isNaN(Date.parse(item.updated_at)) ? "" : new Date(item.updated_at).toLocaleDateString("pt-BR");
    return `<article class="strategy-card"><div class="strategy-card-head"><div><h3>${escapeHtml(item.name)}</h3>${tags}</div>${safeStatus}</div><p class="description">${escapeHtml(detail)}</p><p class="description">${escapeHtml(validation)}${warnings.length ? ` · ${escapeHtml(warnings.join(" "))}` : ""}</p><div class="strategy-card-foot"><span>Atualizada ${escapeHtml(stamp)}</span><div class="strategy-actions">${actions}</div></div></article>`;
  }

  function renderStrategies(items) {
    const strategies = items || [];
    $("#strategy-total-label").textContent = `${strategies.length} registro(s)`;
    $("#strategy-nav-count").textContent = String(strategies.length);
    const visible = state.strategyFilter === "all" ? strategies : strategies.filter((item) => item.status === state.strategyFilter);
    const empty = '<div class="empty-card">Nenhuma estratégia cadastrada. Use “Nova estratégia” para criar uma descrição ou importar um arquivo .mq5/.py.</div>';
    $("#all-strategies").innerHTML = visible.length ? visible.map(strategyCard).join("") : empty;
  }

  function renderEngine(engine, strategies = [], mt5 = {}) {
    const config = engine?.config || {};
    const runtime = engine?.state || {};
    const form = $("#engine-form");
    const select = $("#engine-strategy");
    const previous = select.value || String(config.strategy_id || "");
    const allStrategies = strategies || [];
    const supportedNames = engine?.supported_strategies || [engine?.supported_strategy].filter(Boolean);
    const compatible = allStrategies.filter((item) => supportedNames.includes(item.name));
    const approved = allStrategies.filter((item) => item.status === "approved");
    select.innerHTML = allStrategies.length
      ? allStrategies.map((item) => {
        const supported = supportedNames.includes(item.name);
        const blocked = !supported;
        const reason = supported ? (statusPt[item.status] || item.status) : "regra não implementada";
        return `<option value="${item.id}" ${blocked ? "disabled" : ""}>${escapeHtml(item.name)} · ${escapeHtml(reason)}</option>`;
      }).join("")
      : '<option value="">Cadastre uma estratégia</option>';
    if (allStrategies.some((item) => String(item.id) === previous)) select.value = previous;
    const unsupportedApproved = approved.filter((item) => !supportedNames.includes(item.name));
    $("#engine-compat-note").textContent = unsupportedApproved.length
      ? `${approved.length} aprovada(s); ${approved.length - unsupportedApproved.length} compatível(is) com este motor. As demais aparecem desativadas até existir uma regra executável.`
      : compatible.length
        ? "Aprovação humana e regra compatível são requisitos separados para iniciar o motor."
        : "Nenhuma regra cadastrada é compatível com os executores disponíveis neste build.";
    if (!form.dataset.initialized && config.strategy_id) {
      for (const [key, value] of Object.entries(config)) {
        const field = form.elements.namedItem(key);
        if (field && value !== undefined && value !== null) field.value = String(value);
      }
      form.dataset.initialized = "true";
    }
    const selectedProfile = allStrategies.find((item) => String(item.id) === select.value);
    const strategyName = selectedProfile?.name || "";
    const orb = strategyName === "Rompimento da faixa de abertura de Londres (ORB FX)";
    const cross = strategyName === "Momentum cross-sectional de moedas (literatura)";
    const weekend = strategyName === "Reversão de gap de fim de semana em FX";
    if (weekend) form.elements.namedItem("timezone").value = "America/New_York";
    const ruleNotes = {
      "Momentum cross-sectional de moedas (literatura)": "Adaptação: média de retornos D1 no universo informado; opera o par direto entre moeda mais forte e mais fraca; stop 2 ATR.",
      "Momentum de séries temporais em futuros (literatura)": "Adaptação: sinal pela direção do retorno próprio no lookback D1; stop 2 ATR. O estudo original abrange futuros diversificados.",
      "Carry trade FX com controle fora da amostra": "Adaptação: escolhe a direção com swap positivo do símbolo MT5; stop 2 ATR. Não é a carteira de forwards do estudo.",
      "Reversão de gap de fim de semana em FX": "Adaptação: fade de gap acima do limiar ATR na abertura de domingo 17:00 Nova York; alvo no fechamento de sexta.",
      "Rompimento da faixa de abertura de Londres (ORB FX)": "Adaptação: rompe a faixa configurada da sessão usando fechamento confirmado M1; stop no outro lado da faixa.",
    };
    $("#engine-rule-note").textContent = ruleNotes[strategyName] || "";
    $$(".orb-only", form).forEach((label) => label.classList.toggle("hidden", !orb));
    const timezoneLabel = form.elements.namedItem("timezone").closest("label");
    timezoneLabel.classList.toggle("hidden", !orb && !weekend);
    if (orb) form.elements.namedItem("timezone").value = "Europe/London";
    $("#engine-lookback-label").classList.toggle("hidden", !cross && strategyName !== "Momentum de séries temporais em futuros (literatura)");
    if (strategyName === "Momentum de séries temporais em futuros (literatura)") $("#engine-lookback-label").classList.remove("hidden");
    $("#engine-gap-label").classList.toggle("hidden", !weekend);
    $("#engine-symbol-label").firstChild.textContent = cross ? "Universo de pares MT5 (separados por vírgula)" : "Ativo MT5";
    $("#engine-symbol-label").querySelector("input").placeholder = cross ? "EURUSD,GBPUSD,AUDUSD,USDJPY" : "Ex.: EURUSD";
    const phaseNames = {
      parado: "PARADO", inicializando: "INICIANDO", aguardando_faixa: "AGUARDANDO FAIXA",
      monitorando: "MONITORANDO", sinal_observado: "SINAL · SEM ORDEM", enviando: "VALIDANDO ORDEM",
      ordem_confirmada: "ORDEM CONFIRMADA", ordem_recusada: "ORDEM RECUSADA",
      resultado_desconhecido: "ESTADO INCERTO", dados_incompletos: "DADOS INCOMPLETOS",
      dados_atrasados: "DADOS ATRASADOS", sessao_encerrada: "SESSÃO ENCERRADA",
      entrada_usada: "ENTRADA USADA", bloqueado_posicao: "BLOQUEADO · POSIÇÃO",
      sinal_bloqueado: "SINAL BLOQUEADO", indisponivel: "INDISPONÍVEL",
      bloqueado_relogio: "EXECUÇÃO BLOQUEADA · UTC",
    };
    const badge = $("#engine-status");
    badge.textContent = phaseNames[runtime.phase] || (runtime.running ? "ATIVO" : "PARADO");
    badge.className = `status-chip ${runtime.running ? "approved" : ["resultado_desconhecido", "bloqueado_relogio"].includes(runtime.phase) ? "rejected" : ""}`;
    $("#engine-detail").textContent = `${runtime.mode === "demo" ? "MODO DEMO ATIVO · aguardando sinal" : runtime.mode === "real" ? "MODO REAL ATIVO · aguardando sinal" : runtime.mode === "observacao" ? "OBSERVAÇÃO · sem envio" : "PARADO"} — ${runtime.detail || "Aguardando configuração."}`;
    const signal = runtime.last_signal;
    const signalNode = $("#engine-last-signal");
    if (signal) {
      signalNode.textContent = `Último sinal/execução:\n${signal.side} ${signal.symbol} · lote ${number(signal.volume, 3)}\nEntrada ${number(signal.entry, 8)} · S/L ${number(signal.stop, 8)} · T/P ${number(signal.target, 8)}\nPerda estimada no stop: ${money(signal.estimated_loss, mt5?.account?.currency)}\n${signal.execution?.detail || ""}`;
      signalNode.classList.remove("hidden");
    } else signalNode.classList.add("hidden");
    const selected = allStrategies.find((item) => String(item.id) === select.value);
    const selectedSupported = supportedNames.includes(selected?.name);
    const clockReady = state.snapshot?.system_clock?.status === "synchronized"
      && state.snapshot?.system_clock?.mt5_status === "verified";
    const srBusy = Boolean(state.snapshot?.sr_research?.busy);
    $("#engine-demo").disabled = Boolean(runtime.running || srBusy || !clockReady || mt5?.account?.mode !== "DEMO" || selected?.status !== "approved" || !selectedSupported);
    $("#engine-real").disabled = Boolean(runtime.running || srBusy || !clockReady || mt5?.account?.mode !== "REAL" || selected?.status !== "approved" || !selectedSupported);
    $("#engine-demo").title = clockReady ? "Iniciar execução DEMO" : "Verifique o horário UTC no botão lateral antes de executar";
    $("#engine-real").title = clockReady ? "Iniciar execução REAL" : "Verifique o horário UTC no botão lateral antes de executar";
    $("#engine-observe").disabled = Boolean(runtime.running || srBusy || !mt5?.connected || selected?.status !== "approved" || !selectedSupported);
    $("#engine-stop").disabled = !runtime.running;
  }

  function renderAnalyst(analyst = {}) {
    const config = analyst.config || {};
    const runtime = analyst.state || {};
    const form = $("#analyst-form");
    if (!form.dataset.initialized) {
      state.selectedAnalystSymbols = [...(config.symbols || [])];
      form.elements.namedItem("timeframe").value = config.timeframe || "M15";
      form.elements.namedItem("decision_basis").value = config.decision_basis || "technical_quantitative";
      form.dataset.initialized = "true";
    }
    renderMarketWatchPicker();
    const phases = { parado: "PARADO", configurado: "CONFIGURADO", inicializando: "INICIANDO", analisando: runtime.mode === "demo" ? "DEMO ATIVO" : runtime.mode === "real" ? "REAL ATIVO" : "OBSERVANDO", indisponivel: "INDISPONÍVEL", bloqueado_relogio: "EXECUÇÃO BLOQUEADA", resultado_desconhecido: "CONFERIR MT5" };
    const badge = $("#analyst-status");
    const descriptor = runtimeDescriptor("Analista", runtime);
    badge.textContent = descriptor.running || descriptor.blocked
      ? descriptor.badge : (phases[runtime.phase] || descriptor.badge);
    badge.className = `status-chip ${descriptor.kind}`;
    $("#analyst-detail").textContent = `${runtime.running ? (runtime.mode === "demo" ? "EXECUTANDO DEMO" : runtime.mode === "real" ? "EXECUTANDO REAL" : "SOMENTE OBSERVAÇÃO") : "PARADO"} — ${runtime.detail || "Configure ativo(s) e inicie."}${runtime.last_cycle_at ? ` · Atualizado ${new Date(runtime.last_cycle_at).toLocaleTimeString("pt-BR", { hour12: false })}` : ""}`;
    const symbols = state.selectedAnalystSymbols || config.symbols || [];
    const connected = Boolean(state.snapshot?.mt5?.connected);
    const catalogItems = new Map((state.marketWatch?.items || []).map((item) => [item.broker_symbol, item]));
    const tradableSelection = symbols.length > 0 && symbols.every((symbol) => catalogItems.get(symbol)?.trade_enabled);
    const executionActive = runtime.running && ["demo", "real"].includes(runtime.mode);
    const clockReady = state.snapshot?.system_clock?.status === "synchronized"
      && state.snapshot?.system_clock?.mt5_status === "verified";
    const srBusy = Boolean(state.snapshot?.sr_research?.busy);
    $("#analyst-observe").disabled = Boolean(runtime.running || srBusy || !symbols.length || !connected);
    $("#analyst-demo").disabled = Boolean(executionActive || srBusy || !tradableSelection || !connected);
    $("#analyst-real").disabled = Boolean(executionActive || srBusy || !tradableSelection || !connected);
    const tradeNote = tradableSelection ? "" : "Selecione apenas ativos disponíveis e negociáveis para habilitar envio";
    const clockNote = clockReady ? "" : "O horário UTC será conferido automaticamente antes da execução";
    const accountMode = state.snapshot?.mt5?.account?.mode || "não identificada";
    $("#analyst-demo").title = tradeNote || clockNote || (accountMode === "DEMO" ? "Iniciar execução DEMO" : `Conta atual ${accountMode}; o backend só inicia DEMO em conta DEMO`);
    $("#analyst-real").title = tradeNote || clockNote || (accountMode === "REAL" ? "Iniciar execução REAL" : `Conta atual ${accountMode}; o backend só inicia REAL em conta REAL`);
    $("#analyst-mode-help").textContent = tradeNote || clockNote || `Conta conectada: ${accountMode}. Os dois modos podem ser solicitados; o backend só aceita o modo que corresponde à conta aberta no MT5.`;
    $("#analyst-stop").disabled = !runtime.running;
    if (descriptor.blocked) {
      badge.classList.add("rejected");
      $("#analyst-detail").textContent = descriptor.detail;
    }
    const analyses = runtime.analyses || [];
    if (!analyses.length) {
      $("#analyst-results").innerHTML = '<div class="empty-card">Nenhuma análise disponível. Os resultados aparecem após o primeiro ciclo.</div>';
      return;
    }
    $("#analyst-results").innerHTML = analyses.map((item) => {
      const technical = item.technical || {};
      const quant = item.quantitative || {};
      const fundamental = item.fundamental || {};
      const decision = item.decision || {};
      const candle = technical.latest_candle || {};
      const metrics = [
        ["Estrutura", technical.trend_structure || "indisponível"],
        ["Viés técnico", technical.bias || "indisponível"],
        ["SMA 21 / 50", `${number(technical.sma21, 5)} / ${number(technical.sma50, 5)}`],
        ["ATR 14", number(technical.atr14, 6)],
        ["RSI 14", number(technical.rsi14, 2)],
        ["Retorno 20 barras", typeof quant.return_20_bars === "number" ? `${number(quant.return_20_bars * 100, 3)}%` : "—"],
        ["Viés quantitativo", quant.bias || "indisponível"],
        ["Candle outside", candle.outside_bar ? `sim · ${candle.direction || ""}` : "não"],
        ["Spread / ATR", number(item.quote?.spread_to_atr, 4)],
      ];
      const reasons = (decision.reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");
      const basisLabel = decision.basis_label || "Técnica + quantitativa";
      const candidate = decision.directional_context && decision.directional_context !== "sem_confluência"
        ? `${basisLabel} · viés alinhado: ${decision.directional_context}` : `${basisLabel} · sem confluência direcional`;
      const execution = decision.execution_status ? " · execução: " + executionStatusLabel(decision.execution_status) : "";
      return `<article class="analysis-card"><div class="analysis-card-title"><strong>${escapeHtml(item.symbol || "Ativo")}</strong><span>${escapeHtml(item.timeframe || "")}</span><span class="status-chip">${escapeHtml(decision.action || "AGUARDAR")}</span></div><small>${item.last_closed_bar_at ? `Último candle fechado: ${escapeHtml(new Date(item.last_closed_bar_at).toLocaleString("pt-BR"))}` : `${number(item.bars_used, 0)} barras lidas`}${escapeHtml(serverTimeNote(item))}</small><div class="analysis-layer-grid"><section class="analysis-layer"><h3>Técnica</h3><div class="analysis-metrics">${metrics.slice(0, 5).map(([label, value]) => `<div><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`).join("")}</div><p>${escapeHtml(technical.volume_note || technical.detail || "Valores descritivos; não são gatilhos de entrada.")}</p></section><section class="analysis-layer"><h3>Quantitativa</h3><div class="analysis-metrics">${metrics.slice(5).map(([label, value]) => `<div><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`).join("")}</div><p>${escapeHtml(quant.method_note || quant.detail || "Sem série suficiente para estatísticas.")}</p></section>${renderFundamentalLayer(fundamental)}</div><div class="analysis-verdict"><strong>${escapeHtml(candidate)}${escapeHtml(execution)}</strong><ul>${reasons}</ul><small>${decision.order_eligible ? "Sinal elegível neste modo; envio ainda passa pelos controles de conta, cotação, risco e posições." : "Sem sinal elegível neste modo; nenhuma ordem será solicitada."}</small></div></article>`;
    }).join("");
  }

  function renderMarketWatchPicker() {
    const host = $("#market-watch-symbols");
    if (!host) return;
    const catalog = state.marketWatch;
    const filter = $("#market-watch-search")?.value.trim().toLocaleLowerCase("pt-BR") || "";
    if (!catalog) {
      host.innerHTML = `<div class="empty-card">${state.marketWatchLoading ? "Carregando símbolos do MT5…" : "Atualize a lista para consultar o Market Watch."}</div>`;
      renderReplaySymbolOptions();
      return;
    }
    if (!catalog.available) {
      host.innerHTML = `<div class="empty-card">${escapeHtml(catalog.detail || "Catálogo MT5 indisponível.")}</div>`;
      $("#market-watch-status").textContent = "O conector não conseguiu consultar a lista nesta sessão.";
      renderReplaySymbolOptions();
      return;
    }
    const allItems = catalog.items || [];
    const catalogNames = new Set(allItems.map((item) => item.broker_symbol));
    const missing = (state.selectedAnalystSymbols || []).filter((name) => !catalogNames.has(name));
    const items = allItems.filter((item) =>
      `${item.broker_symbol} ${item.asset_class || ""} ${item.base || ""} ${item.quote || ""}`.toLocaleLowerCase("pt-BR").includes(filter));
    if (!items.length && !missing.length) {
      host.innerHTML = '<div class="empty-card">Nenhum ativo corresponde ao filtro ou o Market Watch está vazio.</div>';
    } else {
      const selected = new Set(state.selectedAnalystSymbols || []);
      const staleRows = missing.map((name) => `<label class="symbol-picker-item" title="Símbolo salvo ausente do Market Watch atual"><input type="checkbox" value="${escapeHtml(name)}" checked><span>${escapeHtml(name)}</span><small>indisponível</small></label>`);
      const activeRows = items.map((item) => `<label class="symbol-picker-item" title="${escapeHtml(item.broker_symbol)} · ${item.trade_enabled ? "negociação habilitada" : "somente leitura"}"><input type="checkbox" value="${escapeHtml(item.broker_symbol)}" ${selected.has(item.broker_symbol) ? "checked" : ""} ${!selected.has(item.broker_symbol) && selected.size >= 12 ? "disabled" : ""}><span>${escapeHtml(item.broker_symbol)}</span><small>${item.trade_enabled ? "trade" : "leitura"}</small></label>`);
      host.innerHTML = [...staleRows, ...activeRows].join("");
    }
    const missingNote = missing.length ? ` Remova ou habilite no MT5: ${missing.join(", ")}.` : "";
    $("#market-watch-status").textContent = `${catalog.count} ativo(s) recebido(s) do ${catalog.source || "MT5"}. Selecione até 12; nomes e sufixos são preservados. Selecionados: ${(state.selectedAnalystSymbols || []).length}/12.${missingNote}`;
    renderReplaySymbolOptions();
  }

  function renderReplaySymbolOptions() {
    const select = $("#replay-symbol");
    if (!select) return;
    const catalog = state.marketWatch;
    if (!catalog?.available) {
      select.innerHTML = '<option value="">Market Watch indisponível</option>';
      select.disabled = true;
      $("#replay-run").disabled = true;
      return;
    }
    const items = (catalog.items || []).filter((item) => item.broker_symbol);
    const previous = select.value;
    const preferredCandidate = previous || state.snapshot?.analyst?.config?.symbols?.[0] || "";
    const preferred = items.find((item) => item.broker_symbol === preferredCandidate && item.trade_enabled)?.broker_symbol
      || items.find((item) => item.trade_enabled)?.broker_symbol || "";
    select.innerHTML = '<option value="">Selecione um ativo</option>' + items.map((item) =>
      `<option value="${escapeHtml(item.broker_symbol)}" ${item.broker_symbol === preferred ? "selected" : ""} ${item.trade_enabled ? "" : "disabled"}>${escapeHtml(item.broker_symbol)}${item.trade_enabled ? "" : " · somente leitura"}</option>`
    ).join("");
    select.disabled = !items.some((item) => item.trade_enabled);
    const active = Boolean(state.snapshot?.analyst?.state?.running || state.snapshot?.engine?.state?.running);
    $("#replay-run").disabled = select.disabled || !select.value || active;
    if (active) $("#replay-status").textContent = "Pare o Analista e o motor de estratégias antes do replay; o conector é compartilhado.";
  }

  function renderSrSymbolOptions() {
    const items = state.marketWatch?.available ? (state.marketWatch.items || []).filter((item) => item.broker_symbol) : [];
    const first = $("#sr-symbol-1"), second = $("#sr-symbol-2");
    if (!first || !second) return;
    const previousFirst = first.value || state.snapshot?.sr_research?.symbols?.[0] || "";
    const previousSecond = second.value || state.snapshot?.sr_research?.symbols?.[1] || "";
    const options = items.map((item) => `<option value="${escapeHtml(item.broker_symbol)}" ${item.trade_enabled ? "" : "disabled"}>${escapeHtml(item.broker_symbol)}${item.trade_enabled ? "" : " · somente leitura"}</option>`).join("");
    first.innerHTML = '<option value="">Selecione um ativo</option>' + options;
    second.innerHTML = '<option value="">Nenhum</option>' + options;
    first.value = items.some((item) => item.broker_symbol === previousFirst && item.trade_enabled) ? previousFirst : "";
    second.value = items.some((item) => item.broker_symbol === previousSecond && item.trade_enabled) ? previousSecond : "";
    first.disabled = second.disabled = !state.marketWatch?.available;
    const replay = $("#sr-replay-symbol");
    const replayPrevious = replay.value;
    replay.innerHTML = '<option value="">Selecione um ativo</option>' + options;
    replay.value = items.some((item) => item.broker_symbol === replayPrevious && item.trade_enabled) ? replayPrevious : "";
    replay.disabled = !state.marketWatch?.available;
    renderSrResearch(state.snapshot?.sr_research || {});
  }

  function renderSrResearch(research = {}) {
    const running = Boolean(research.running);
    const busy = Boolean(research.busy);
    const conflict = Boolean(state.snapshot?.analyst?.state?.running || state.snapshot?.engine?.state?.running);
    const badge = $("#sr-status");
    if (!badge) return;
    badge.textContent = running ? "PESQUISANDO · SEM ORDENS" : busy ? "FINALIZANDO" : "PARADA";
    badge.className = `status-chip ${running ? "active" : ""}`;
    $("#sr-start").disabled = busy || conflict || !$("#sr-symbol-1").value;
    $("#sr-stop").disabled = !running;
    $("#sr-symbol-1").disabled = $("#sr-symbol-2").disabled = busy || !state.marketWatch?.available;
    $("#sr-replay-run").disabled = busy || conflict || !$("#sr-replay-symbol").value;
    $("#sr-replay-saved").disabled = busy || conflict;
    $("#sr-detail").textContent = `${research.detail || "Pesquisa desligada."}${research.last_cycle_at ? ` · ${new Date(research.last_cycle_at).toLocaleTimeString("pt-BR", {hour12:false})}` : ""}${conflict && !running ? " · Pare os motores de ordens para iniciar esta pesquisa." : ""}`;
    const results = research.last_results || [];
    $("#sr-results").innerHTML = results.length ? results.map((item) => {
      const direction = item.regime?.direction || "indisponível";
      const candidates = (item.candidates || []).map((candidate) => `${candidate.strategy} ${candidate.side} (${candidate.status})`).join(" · ") || "Nenhum candidato";
      const reasons = (item.rejections || []).map((reason) => reason.code).join(" · ") || item.detail || "Sem bloqueios registrados";
      const filters = Object.entries(item.filter_counts || {}).map(([name, count]) => `${name}: ${count}`).join(" · ");
      return `<article class="sr-result"><div class="sr-result-head"><strong>${escapeHtml(item.symbol || "Ativo")}</strong><span>${escapeHtml(item.status || "—")}</span></div><div class="sr-result-grid"><span>Regime <b>${escapeHtml(direction)}</b></span><span>Zonas <b>${number(item.zones_found || 0, 0)}</b></span><span>Spread/ATR M5 <b>${item.spread_to_atr_m5 == null ? "—" : number(item.spread_to_atr_m5, 3)}</b></span><span>Último M5 <b>${item.frame_last_closed?.M5 ? escapeHtml(new Date(item.frame_last_closed.M5 * 1000).toLocaleString("pt-BR")) : "—"}</b></span></div><p><b>Hipóteses:</b> ${escapeHtml(candidates)}</p><p><b>Motivos:</b> ${escapeHtml(reasons)}</p><small>${escapeHtml(filters)}</small></article>`;
    }).join("") : '<div class="empty-card">Nenhuma avaliação desta sessão.</div>';
  }

  async function startSrResearch() {
    const symbols = [$("#sr-symbol-1").value, $("#sr-symbol-2").value].filter(Boolean);
    if (!symbols.length || new Set(symbols).size !== symbols.length) {
      toast("Selecione um ou dois ativos diferentes do Market Watch.", "error"); return;
    }
    try {
      const result = await api("/api/sr-quant/start", {method:"POST", body:JSON.stringify({symbols}), timeoutMs:15000});
      toast(result.detail, "success"); await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  async function stopSrResearch() {
    try {
      const result = await api("/api/sr-quant/stop", {method:"POST", body:"{}", timeoutMs:15000});
      toast(result.detail, "success"); await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  function renderSrReplayReport(result) {
    const host = $("#sr-replay-report");
    const familyNames = {trend_pullback:"Pullback em tendência", breakout_retest:"Rompimento e reteste",
      range_fakeout:"Falso rompimento lateral", momentum20_baseline:"Baseline momentum 20"};
    const segments = result.segments || {};
    const renderSegment = (title, segment = {}) => `<section class="sr-replay-segment"><h3>${title}</h3><small>${escapeHtml(segment.first_bar_utc || "")} → ${escapeHtml(segment.last_bar_utc || "")} · ${number(segment.evaluated_bars || 0, 0)} candles avaliados</small><div class="table-wrap"><table><thead><tr><th>Família</th><th>Sinais</th><th>Trades</th><th>R líquido</th><th>Drawdown</th><th>Amostra</th></tr></thead><tbody>${Object.entries(segment.families || {}).map(([name, metrics]) => `<tr><td>${escapeHtml(familyNames[name] || name)}</td><td>${number(metrics.signals || 0, 0)}</td><td>${number(metrics.closed_trades || 0, 0)}</td><td>${metrics.net_r == null ? "—" : `${number(metrics.net_r, 2)} R`}</td><td>${metrics.max_drawdown_r == null ? "—" : `${number(metrics.max_drawdown_r, 2)} R`}</td><td>${escapeHtml(metrics.sample_status || "—")}</td></tr>`).join("")}</tbody></table></div><small>Filtros: ${escapeHtml(Object.entries(segment.filters || {}).map(([key, value]) => `${key}: ${value}`).join(" · ") || "nenhum")}</small></section>`;
    host.innerHTML = `<div class="sr-replay-heading"><strong>${escapeHtml(result.symbol || "")} · versão ${escapeHtml(result.version || "")}</strong><span>TRIAGEM OHLC · SEM ORDENS</span></div>${renderSegment("Desenvolvimento · 70% inicial", segments.development)}${renderSegment("Holdout · 30% final", segments.holdout)}<div class="replay-hash"><span>SHA-256 do histórico, contrato e custos</span><code>${escapeHtml(result.data_sha256 || "")}</code></div><div class="replay-limitations"><strong>Limitações</strong><ul>${(result.limitations || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`;
    host.classList.remove("hidden");
  }

  async function runSrReplay(event) {
    event.preventDefault();
    const form = $("#sr-replay-form");
    if (!form.reportValidity()) return;
    const data = Object.fromEntries(new FormData(form));
    data.costs_confirmed = form.elements.costs_confirmed.checked;
    const button = $("#sr-replay-run");
    button.disabled = true;
    $("#sr-replay-report").classList.add("hidden");
    $("#sr-replay-status").textContent = `Consultando H1, M15 e M5 de ${data.symbol} e simulando custos; nenhuma ordem será enviada.`;
    try {
      const response = await api("/api/sr-quant/replay", {method:"POST", body:JSON.stringify(data), timeoutMs:120000});
      $("#sr-replay-status").textContent = response.detail;
      renderSrReplayReport(response.result);
    } catch (error) { $("#sr-replay-status").textContent = error.message; toast(error.message, "error"); }
    finally { renderSrResearch(state.snapshot?.sr_research || {}); }
  }

  async function replaySavedSr() {
    const button = $("#sr-replay-saved");
    button.disabled = true;
    $("#sr-replay-status").textContent = "Reproduzindo o último histórico S/R salvo, sem consultar o MT5.";
    try {
      const response = await api("/api/sr-quant/replay-saved", {method:"POST", body:"{}", timeoutMs:120000});
      $("#sr-replay-status").textContent = response.detail;
      renderSrReplayReport(response.result);
    } catch (error) { $("#sr-replay-status").textContent = error.message; toast(error.message, "error"); }
    finally { renderSrResearch(state.snapshot?.sr_research || {}); }
  }

  async function refreshMarketWatch(showToast = true) {
    if (state.marketWatchLoading) return;
    state.marketWatchLoading = true;
    $("#refresh-market-watch").disabled = true;
    renderMarketWatchPicker();
    try {
      const catalog = await api("/api/mt5/market-watch", { timeoutMs: 12000 });
      state.marketWatch = catalog;
      state.marketWatchTerminal = catalog.terminal_id;
      if (state.selectedAnalystSymbols === null) {
        state.selectedAnalystSymbols = [...(state.snapshot?.analyst?.config?.symbols || [])];
      }
      renderMarketWatchPicker();
      renderSrSymbolOptions();
      if (showToast) toast(`${catalog.count} ativo(s) carregado(s) do MT5.`, "success");
    } catch (error) {
      state.marketWatch = { available: false, source: "MT5 Market Watch", count: 0, items: [], detail: error.message };
      renderMarketWatchPicker();
      renderSrSymbolOptions();
      if (showToast) toast(error.message, "error");
    } finally {
      state.marketWatchLoading = false;
      $("#refresh-market-watch").disabled = false;
      renderMarketWatchPicker();
      if (state.snapshot) renderAnalyst(state.snapshot.analyst || {});
    }
  }

  function renderReplayReport(result) {
    const host = $("#replay-report");
    if (!host) return;
    const metrics = result.metrics || {};
    const segments = result.segments || {};
    const comparison = result.comparison || {};
    const currency = state.snapshot?.mt5?.account?.currency || "USD";
    const trades = result.trades || [];
    const rows = trades.slice(0, 30).map((trade) => `<tr><td>${escapeHtml(trade.signal_time_utc || trade.entry_time_utc || "—")}</td><td>${escapeHtml(trade.side || "—")}</td><td>${escapeHtml(trade.entry_time_utc || "—")}</td><td>${escapeHtml(trade.exit_time_utc || "—")}</td><td>${trade.net_r == null ? "—" : `${number(trade.net_r, 2)} R`}</td><td>${escapeHtml((trade.exit_reason || trade.reason || "—").replaceAll("_", " "))}</td></tr>`).join("");
    const limitations = (result.limitations || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    const segmentMarkup = (label, segment) => {
      if (!segment) return "";
      const pullback = segment.pullback?.metrics || {};
      const baseline = segment.baseline?.metrics || {};
      const row = (name, item) => `<div><span>${name}</span><strong>${number(item.closed_trades, 0)} trades · ${item.net_r_total == null ? "—" : `${number(item.net_r_total, 2)} R`}</strong><small>Expectativa ${item.expectancy_r == null ? "—" : `${number(item.expectancy_r, 2)} R`} · DD ${item.max_drawdown_r == null ? "—" : `${number(item.max_drawdown_r, 2)} R`}</small></div>`;
      return `<section class="replay-segment"><div><strong>${label}</strong><small>${escapeHtml(segment.start_utc || "")} → ${escapeHtml(segment.end_utc || "")} · ${number(segment.bars, 0)} candles</small></div><div class="replay-segment-rows">${row("Pullback SMA 21", pullback)}${row("Baseline momentum 20", baseline)}</div></section>`;
    };
    const sampleText = comparison.sample_status === "amostra_descritiva_minima_atingida"
      ? "A amostra mínima descritiva foi atingida; isso ainda não homologa a estratégia."
      : "Amostra insuficiente no holdout: não concluir que uma regra é superior ou inferior.";
    host.innerHTML = `<div class="replay-report-heading"><div><strong>${escapeHtml(result.symbol)} · ${escapeHtml(result.timeframe)}</strong><small>${escapeHtml(result.first_bar_utc || "")} → ${escapeHtml(result.last_bar_utc || "")} · ${number(result.bars_used, 0)} candles · versão ${escapeHtml(result.version || "")}</small></div><span class="status-chip">HOLDOUT OHLC</span></div><div class="replay-metrics"><div><small>Holdout · pullback: trades</small><strong>${number(metrics.closed_trades, 0)}</strong></div><div><small>Baseline: trades</small><strong>${number(comparison.baseline_closed_trades, 0)}</strong></div><div><small>Pullback: resultado líquido</small><strong>${metrics.net_r_total == null ? "—" : `${number(metrics.net_r_total, 2)} R`}</strong></div><div><small>Baseline: resultado líquido</small><strong>${comparison.holdout_baseline_net_r == null ? "—" : `${number(comparison.holdout_baseline_net_r, 2)} R`}</strong></div><div><small>Diferença pullback − baseline</small><strong>${comparison.holdout_delta_net_r == null ? "—" : `${number(comparison.holdout_delta_net_r, 2)} R`}</strong></div><div><small>Expectativa pullback</small><strong>${metrics.expectancy_r == null ? "—" : `${number(metrics.expectancy_r, 2)} R`}</strong></div><div><small>Drawdown pullback</small><strong>${metrics.max_drawdown_r == null ? "—" : `${number(metrics.max_drawdown_r, 2)} R`}</strong></div><div><small>Resultado monetário estimado</small><strong>${metrics.net_cash_estimate == null ? "—" : money(metrics.net_cash_estimate, currency)}</strong></div></div><div class="replay-limitations"><strong>${escapeHtml(sampleText)}</strong><small>${escapeHtml(comparison.interpretation || "")}</small></div><div class="replay-segments">${segmentMarkup("Desenvolvimento · 70% inicial", segments.development)}${segmentMarkup("Validação · 30% final intocado", segments.holdout)}</div><div class="replay-hash"><span>SHA-256 dos candles, contrato e parâmetros</span><code>${escapeHtml(result.data_sha256 || "")}</code></div><div class="table-wrap"><table><thead><tr><th>Sinal UTC</th><th>Lado</th><th>Entrada UTC</th><th>Saída UTC</th><th>Resultado</th><th>Saída</th></tr></thead><tbody>${rows || '<tr><td colspan="6" class="empty-cell">Nenhuma operação fechada no holdout; nenhuma conclusão estatística será feita.</td></tr>'}</tbody></table></div><div class="replay-limitations"><strong>Limites desta simulação</strong><ul>${limitations}</ul><small>${metrics.skipped_after_gap ? `${number(metrics.skipped_after_gap, 0)} sinal(is) descartado(s) após gap de entrada.` : ""}${metrics.censored_positions ? ` ${number(metrics.censored_positions, 0)} posição(ões) ficaram abertas no fim da amostra e foram excluídas das métricas.` : ""}</small></div>`;
    host.classList.remove("hidden");
  }

  async function runReplay(event) {
    event.preventDefault();
    const form = $("#replay-form");
    const button = $("#replay-run");
    const data = Object.fromEntries(new FormData(form).entries());
    data.bars = Number(data.bars);
    data.slippage_points = Number(data.slippage_points);
    data.commission_per_lot_round_turn = Number(data.commission_per_lot_round_turn);
    data.swap_long_per_lot_per_utc_rollover = Number(data.swap_long_per_lot_per_utc_rollover);
    data.swap_short_per_lot_per_utc_rollover = Number(data.swap_short_per_lot_per_utc_rollover);
    data.costs_confirmed = form.elements.costs_confirmed.checked;
    if (!data.symbol) { toast("Selecione um ativo do Market Watch.", "error"); return; }
    button.disabled = true;
    $("#replay-status").textContent = `Consultando ${data.bars} candles fechados de ${data.symbol}; comparando 70% de contexto e 30% de holdout com o baseline. Nenhuma ordem será enviada.`;
    $("#replay-report").classList.add("hidden");
    try {
      const response = await api("/api/analyst/replay", { method: "POST", body: JSON.stringify(data), timeoutMs: 120000 });
      renderReplayReport(response.result);
      $("#replay-status").textContent = response.detail;
      logLine(`Validação ${data.symbol} ${data.timeframe}: ${response.result.metrics.closed_trades} trades de pullback no holdout, sem ordens.`, "");
      toast("Replay concluído e snapshot salvo localmente.", "success");
    } catch (error) {
      $("#replay-status").textContent = error.message;
      toast(error.message, "error");
    } finally {
      button.disabled = !state.marketWatch?.available || !$("#replay-symbol").value;
    }
  }

  function renderDashboardStatus(snapshot = {}) {
    const mt5 = snapshot.mt5 || {};
    const account = mt5.account || {};
    const analyst = snapshot.analyst || {};
    const runtime = analyst.state || {};
    const analyses = runtime.analyses || [];
    const configured = analyst.config?.symbols?.length || 0;
    const connectionStatus = $("#dashboard-connection-status");
    const connectionDot = $("#dashboard-connection-dot");
    connectionStatus.textContent = mt5.connected ? "Conectado" : "Desconectado";
    connectionStatus.className = mt5.connected ? "status-value good" : "status-value bad";
    connectionDot.className = mt5.connected ? "state-dot" : "state-dot muted";

    const accountMode = account.mode || "—";
    $("#dashboard-account-mode").textContent = accountMode;
    $("#dashboard-account-mode").className = `status-value ${accountMode === "DEMO" ? "good" : accountMode === "REAL" ? "live" : ""}`;
    $("#dashboard-symbol-count").textContent = analyses.length
      ? `${analyses.length}/${configured || analyses.length} lidos`
      : configured ? `${configured} configurados` : "—";
    $("#dashboard-timeframe").textContent = analyst.config?.timeframe || "—";

    const tickAges = analyses.map((item) => {
      const measuredAge = item.time_normalization?.tick_age_seconds;
      if (typeof measuredAge !== "number" || !Number.isFinite(measuredAge) || measuredAge < 0) return null;
      const analyzedAt = Date.parse(item.analyzed_at || "");
      const elapsed = Number.isFinite(analyzedAt) ? Math.max(0, (Date.now() - analyzedAt) / 1000) : 0;
      return measuredAge + elapsed;
    }).filter((age) => age !== null);
    const tickAge = tickAges.length ? Math.max(...tickAges) : null;
    const tickLabel = tickAge === null ? (analyses.length ? `${tickAges.length}/${analyses.length} lidos` : "Sem leitura")
      : `${tickAge.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s${tickAge > 120 ? " · atrasado" : ""}`;
    const tickNode = $("#dashboard-tick-age");
    tickNode.textContent = tickLabel;
    tickNode.className = `status-value ${tickAge === null ? "muted-value" : tickAge > 120 ? "warning-value" : "good"}`;
    tickNode.title = tickAges.length
      ? `Idade máxima dos ticks na última análise (${tickAges.length} de ${analyses.length} ativos com tick).`
      : "A análise ainda não forneceu idade de tick.";

    const cycle = runtime.last_cycle_at ? new Date(runtime.last_cycle_at) : null;
    $("#dashboard-last-cycle").textContent = cycle && Number.isFinite(cycle.getTime())
      ? cycle.toLocaleTimeString("pt-BR", { hour12: false }) : "—";
  }

  function renderDashboardAnalyst(analyst = {}) {
    const runtime = analyst.state || {};
    const analyses = runtime.analyses || [];
    const descriptor = runtimeDescriptor("Analista", runtime);
    const status = runtime.running || descriptor.blocked
      ? descriptor.badge : (analyses.length ? "ÚLTIMA LEITURA" : descriptor.badge);
    const badge = $("#dashboard-analyst-status");
    badge.textContent = status;
    badge.className = `status-chip ${descriptor.kind}`;
    $("#dashboard-analyst-count").textContent = `${analyses.length || (analyst.config?.symbols || []).length} ativo${(analyses.length || (analyst.config?.symbols || []).length) === 1 ? "" : "s"}`;
    $("#dashboard-analyst-caption").textContent = runtime.last_cycle_at
      ? `${runtime.running && runtime.mode !== "observacao" ? `Modo ${runtime.mode.toUpperCase()} ativo · aguardando confirmação reconciliada pelo MT5` : runtime.running ? "Monitoramento ativo" : "Últimos resultados disponíveis"} · Atualizado ${new Date(runtime.last_cycle_at).toLocaleTimeString("pt-BR", { hour12: false })}`
      : "Modo Técnica + quantitativa · fundamental/calendário informativos";
    if (descriptor.blocked) {
      badge.classList.add("rejected");
      $("#dashboard-analyst-caption").textContent = descriptor.detail;
    }
    const eligible = analyses.filter((item) => item.decision?.order_eligible).length;
    const unavailable = analyses.filter((item) => item.technical?.status !== "available"
      || item.quantitative?.status !== "available").length;
    const waiting = Math.max(0, analyses.length - eligible - unavailable);
    $("#dashboard-signal-summary").textContent = analyses.length
      ? `${eligible} ${eligible === 1 ? "sinal elegível" : "sinais elegíveis"} · ${waiting} aguardando${unavailable ? ` · ${unavailable} sem dados` : ""}`
      : "Aguardando dados da análise";
    if (!analyses.length) {
      $("#dashboard-analyst-results").innerHTML = `<div class="empty-card">${runtime.running ? "Aguardando o primeiro ciclo de análise dos ativos configurados." : "Configure os ativos e inicie o Analista em Risco e segurança para exibir as leituras aqui."}</div>`;
      $("#dashboard-show-more").classList.add("hidden");
      return;
    }
    const visibleAnalyses = state.dashboardShowAll ? analyses : analyses.slice(0, 3);
    $("#dashboard-analyst-results").innerHTML = visibleAnalyses.map((item, index) => {
      const technical = item.technical || {};
      const quantitative = item.quantitative || {};
      const fundamental = item.fundamental || {};
      const decision = item.decision || {};
      const candle = technical.latest_candle || {};
      const ret = typeof quantitative.return_20_bars === "number" ? `${number(quantitative.return_20_bars * 100, 3)}%` : "—";
      const reasons = (decision.reasons || []).slice(0, 2).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");
      const updated = item.last_closed_bar_at
        ? new Date(item.last_closed_bar_at).toLocaleTimeString("pt-BR", { hour12: false }) : "sem candle válido";
      const confirmed = decision.execution_status === "CONFIRMADA_MT5";
      const statusLabel = confirmed ? "ORDEM CONFIRMADA PELO MT5"
        : decision.order_eligible ? (decision.side === "BUY" ? "CANDIDATO DE COMPRA" : "CANDIDATO DE VENDA")
          : technical.status !== "available" || quantitative.status !== "available" ? "DADOS INDISPONÍVEIS" : "AGUARDAR";
      const statusClass = confirmed ? "confirmed" : decision.order_eligible ? "signal"
        : technical.status !== "available" || quantitative.status !== "available" ? "unavailable" : "waiting";
      const executionNote = decision.execution_status && decision.execution_status !== "SINAL_NAO_CONFIRMADO"
        ? `<span class="analysis-execution-note">${escapeHtml(executionStatusLabel(decision.execution_status))}</span>` : "";
      const firstReason = decision.reasons?.[0] || "Sem motivo adicional registrado.";
      const compactFundamental = { ...fundamental, events: (fundamental.events || []).slice(0, 2) };
      return `<details class="dashboard-asset-row" ${index === 0 ? "open" : ""}><summary class="dashboard-asset-summary"><span class="asset-chevron" aria-hidden="true">›</span><span class="dashboard-asset-name"><strong>${escapeHtml(item.symbol || "Ativo")}</strong><small>${escapeHtml(item.timeframe || "")} · candle ${escapeHtml(updated)}${escapeHtml(serverTimeNote(item))}</small></span><span class="dashboard-asset-status ${statusClass}">${escapeHtml(statusLabel)}</span><span class="dashboard-asset-reason">${escapeHtml(firstReason)}</span></summary><div class="dashboard-asset-details"><div class="analysis-layer-grid"><section class="analysis-layer"><h3>Técnica</h3><div class="analysis-metrics"><div><span>Estrutura</span><b>${escapeHtml(technical.trend_structure || "indisponível")}</b></div><div><span>Viés</span><b>${escapeHtml(technical.bias || "indisponível")}</b></div><div><span>SMA 21 / 50</span><b>${escapeHtml(number(technical.sma21, 5))} / ${escapeHtml(number(technical.sma50, 5))}</b></div><div><span>ATR 14 / RSI 14</span><b>${escapeHtml(number(technical.atr14, 6))} / ${escapeHtml(number(technical.rsi14, 2))}</b></div></div><p>Candle outside: ${candle.outside_bar ? `sim · ${escapeHtml(candle.direction || "")}` : "não"}</p></section><section class="analysis-layer"><h3>Quantitativa</h3><div class="analysis-metrics"><div><span>Retorno 20 barras</span><b>${escapeHtml(ret)}</b></div><div><span>Viés</span><b>${escapeHtml(quantitative.bias || "indisponível")}</b></div><div><span>Volatilidade ATR</span><b>${escapeHtml(number(quantitative.atr14_vs_recent_median, 3))}</b></div><div><span>Spread / ATR</span><b>${escapeHtml(number(item.quote?.spread_to_atr, 4))}</b></div></div><p>Estatísticas descritivas; não representam probabilidade de lucro.</p></section>${renderFundamentalLayer(compactFundamental)}</div><div class="analysis-verdict"><strong>${escapeHtml(decision.basis_label || "Técnica + quantitativa")} · ${escapeHtml(decision.directional_context || "sem confluência")}</strong>${executionNote}<ul>${reasons || "<li>Sem motivos adicionais registrados.</li>"}</ul><small>${confirmed ? "Execução confirmada e reconciliada pelo MT5." : decision.order_eligible ? "Sinal elegível; aguardando as verificações finais de risco e execução." : "Aguardar · sem sinal elegível para envio."}</small></div></div></details>`;
    }).join("");
    const showMore = $("#dashboard-show-more");
    showMore.classList.toggle("hidden", analyses.length <= 3);
    showMore.setAttribute("aria-expanded", String(state.dashboardShowAll));
    showMore.textContent = state.dashboardShowAll ? "Mostrar menos ativos" : `Ver outros ${analyses.length - 3} ativos`;
  }

  function renderFundamentalLayer(fundamental = {}) {
    const labels = { partial: "PARCIAL", stale: "ATRASADO", unavailable: "INDISPONÍVEL" };
    const state = labels[fundamental.status] || (fundamental.status === "available" ? "DISPONÍVEL" : "INDISPONÍVEL");
    const events = (fundamental.events || []).slice(0, 4).map((event) => {
      const importance = { 3: "ALTA", 2: "MODERADA", 1: "BAIXA" }[event.importance] || "SEM CLASSIFICAÇÃO";
      const safeUrl = /^https:\/\//i.test(event.source_url || "")
        ? `<a href="${escapeHtml(event.source_url)}" target="_blank" rel="noopener noreferrer">fonte</a>` : "";
      return `<li><strong>${escapeHtml(event.currency || "") } · ${importance}</strong><span>${escapeHtml(event.name || "Evento")}</span><small>${escapeHtml(event.event_time_server || "Horário indisponível")} (servidor MT5) ${safeUrl}</small></li>`;
    }).join("");
    const empty = fundamental.status === "partial" ? "Nenhum evento futuro associado às moedas do ativo na janela consultada." : "";
    return `<section class="analysis-layer"><h3>Fundamental · informativo</h3><strong class="fundamental-status">${state}</strong><p>${escapeHtml(fundamental.detail || "Sem dados fundamentais estruturados para este ativo.")}</p><p>Não participa do gatilho do modo Técnica + quantitativa.</p>${events ? `<ul class="fundamental-events">${events}</ul>` : `<p class="fundamental-empty">${empty}</p>`}</section>`;
  }

  function renderProviders(providers = []) {
    const html = providers.map((provider) => `<article class="provider-card"><strong>${escapeHtml(provider.name)}<i class="provider-status ${provider.available || provider.ok ? "ok" : ""}"></i></strong><p>${escapeHtml(provider.detail || (provider.ok ? `${provider.count} resultado(s) nesta busca.` : `${provider.count ?? 0} resultado(s); fonte indisponível.`))}</p></article>`).join("");
    $("#provider-grid").innerHTML = html || '<div class="empty-card">Nenhum provedor configurado.</div>';
    $("#settings-providers").innerHTML = html || '<div class="empty-card">Nenhum provedor configurado.</div>';
  }

  function renderResearch(items) {
    state.research = items || [];
    $("#research-count").textContent = `${state.research.length} fonte${state.research.length === 1 ? "" : "s"}`;
    const selected = new Set($$("[data-research-id]:checked").map((input) => Number(input.value)));
    const button = $("#summarize-button");
    button.disabled = !state.research.length || !state.snapshot?.ai?.available || selected.size === 0;
    if (!state.research.length) {
      $("#research-results").innerHTML = '<div class="empty-card">Pesquise ou importe uma fonte para começar.</div>';
      return;
    }
    $("#research-results").innerHTML = state.research.map((item) => {
      const when = item.published_at ? `Publicado: ${item.published_at}` : `Capturado: ${new Date(item.fetched_at).toLocaleString("pt-BR")}`;
      return `<article class="research-item"><input type="checkbox" data-research-id value="${item.id}" aria-label="Selecionar ${escapeHtml(item.title)}"><div><h3><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a></h3><p>${escapeHtml(item.excerpt || "Sem trecho de descrição disponível.")}</p><div class="research-date">${escapeHtml(when)}</div></div><span class="research-source">${escapeHtml(item.source)}</span></article>`;
    }).join("");
    $$("[data-research-id]").forEach((box) => box.addEventListener("change", () => {
      button.disabled = !state.snapshot?.ai?.available || $$("[data-research-id]:checked").length === 0;
    }));
  }

  function renderLogs(items = []) {
    const list = $("#activity-list");
    const output = $("#terminal-output");
    if (!items.length) {
      list.innerHTML = '<div class="activity-empty">Nenhum evento registrado.</div>';
      output.innerHTML = '<div class="terminal-line muted-line">Nenhum evento registrado ainda.</div>';
      $("#terminal-update").textContent = "—";
      return;
    }
    list.innerHTML = items.slice(0, 10).map((item) => `<div class="activity-row"><time>${escapeHtml(new Date(item.created_at).toLocaleTimeString("pt-BR", { hour12: false }))}</time><b>${escapeHtml(item.level)}</b><span>${escapeHtml(item.message)}</span></div>`).join("");
    const filters = {
      all: () => true,
      info: (item) => item.level === "INFO",
      warn: (item) => item.level === "WARN",
      error: (item) => item.level === "ERROR" || item.level === "CRITICAL",
    };
    const filtered = items.filter(filters[state.logFilter] || filters.all);
    $$('[data-log-filter]').forEach((button) => {
      const selected = button.dataset.logFilter === state.logFilter;
      button.classList.toggle("selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    output.innerHTML = filtered.length
      ? filtered.slice(0, 24).reverse().map((item) => `<div class="terminal-line ${item.level === "WARN" || item.level === "CRITICAL" || item.level === "ERROR" ? "warn" : ""}"><span class="terminal-time">${escapeHtml(new Date(item.created_at).toLocaleTimeString("pt-BR", { hour12: false }))}</span>${escapeHtml(item.message)}</div>`).join("")
      : '<div class="terminal-line muted-line">Nenhum evento corresponde a este filtro.</div>';
    const latest = new Date(items[0].created_at);
    $("#terminal-update").textContent = Number.isFinite(latest.getTime())
      ? latest.toLocaleTimeString("pt-BR", { hour12: false }) : "—";
  }

  function renderState(snapshot) {
    state.snapshot = snapshot;
    const mt5 = snapshot.mt5;
    const account = mt5.account;
    const terminalId = mt5.connector?.terminal_id || mt5.terminal_id || null;
    renderConnection(mt5);
    renderOperationalStatus(snapshot);
    renderClockStatus(snapshot.system_clock);
    renderOrders(snapshot.orders, account);
    renderStrategies(snapshot.strategies);
    renderEngine(snapshot.engine, snapshot.strategies, mt5);
    renderAnalyst(snapshot.analyst);
    renderSrResearch(snapshot.sr_research);
    renderRiskSettings(snapshot);
    renderDashboardStatus(snapshot);
    renderDashboardAnalyst(snapshot.analyst);
    renderResearch(snapshot.research);
    renderProviders(snapshot.providers);
    renderLogs(snapshot.logs);
    if (mt5.connected && (!state.marketWatch || state.marketWatchTerminal !== terminalId)) {
      refreshMarketWatch(false);
    }
    $("#kpi-balance").textContent = account ? money(account.balance, account.currency) : "—";
    $("#header-balance").textContent = account ? money(account.balance, account.currency) : "Saldo —";
    $("#kpi-currency").textContent = account ? `${account.currency} · saldo informado pelo MT5` : (mt5.detail || "Aguardando MT5");
    $("#kpi-profit").textContent = account ? money(account.profit, account.currency) : "—";
    $("#kpi-profit").className = `kpi-value ${account && account.profit >= 0 ? "green-value" : account ? "red-value" : ""}`;
    $("#kpi-equity").textContent = account ? `Patrimônio ${money(account.equity, account.currency)}` : "Patrimônio —";
    $("#refresh-button").title = snapshot.ai.available ? `Atualizar dados · IA ${snapshot.ai.model}` : "Atualizar dados";
  }

  let refreshInFlight = false;
  let refreshSequence = 0;
  async function refresh(showToast = false) {
    if (refreshInFlight) return;
    refreshInFlight = true;
    const sequence = ++refreshSequence;
    try {
      const snapshot = await api("/api/state", { timeoutMs: 15000 });
      if (sequence === refreshSequence) renderState(snapshot);
      if (showToast) toast("Dados do aplicativo e MT5 atualizados.", "success");
    } catch (error) {
      toast(error.message, "error");
      logLine(`Falha ao atualizar: ${error.message}`, "error");
    } finally {
      refreshInFlight = false;
    }
  }

  async function synchronizeClock({ navigate = true, showToast = true } = {}) {
    if (navigate) setView("risk");
    renderClockStatus({ status: "checking" });
    try {
      const result = await api("/api/system/clock/synchronize", {
        method: "POST", body: JSON.stringify({}), timeoutMs: 60000,
      });
      if (state.snapshot) state.snapshot.system_clock = result;
      renderClockStatus(result);
      if (showToast) toast(result.detail, result.status === "synchronized" ? "success" : "error");
      await refresh();
      return result;
    } catch (error) {
      renderClockStatus({ status: "error", detail: error.message });
      if (showToast) toast(error.message, "error");
      await refresh();
      return null;
    }
  }

  function setView(name) {
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  }

  function setSidebarExpanded(expanded) {
    const shell = $(".app-shell");
    const button = $("#sidebar-toggle");
    shell.classList.toggle("sidebar-expanded", expanded);
    button.setAttribute("aria-expanded", String(expanded));
    button.setAttribute("aria-label", expanded ? "Recolher menu" : "Expandir menu");
    button.title = expanded ? "Recolher menu" : "Expandir menu";
    button.textContent = expanded ? "‹" : "›";
    try { localStorage.setItem("scalperlab-sidebar-expanded", String(expanded)); } catch { /* armazenamento local opcional */ }
  }

  function showStrategyModal() {
    $("#strategy-modal").classList.remove("hidden");
    $("#strategy-form [name=name]").focus();
  }
  function hideStrategyModal() {
    $("#strategy-modal").classList.add("hidden");
    $("#strategy-form").reset();
    $("#file-label").textContent = "Escolher arquivo";
    $("#source-adaptation").textContent = "";
    $("#source-adaptation").classList.add("hidden");
    delete $("#strategy-form [name=name]").dataset.importSuggestion;
    delete $("#strategy-form [name=description]").dataset.importSuggestion;
  }

  async function decodeStrategyFile(file) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) return new TextDecoder("utf-16le").decode(bytes.subarray(2));
    if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) return new TextDecoder("utf-16be").decode(bytes.subarray(2));
    try { return new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
    catch { return new TextDecoder("windows-1252").decode(bytes); }
  }

  async function armDemo() {
    const confirmation = prompt('Digite ATIVAR SOMENTE DEMO para habilitar fechamento de posições em conta demo.');
    if (confirmation === null) return;
    try {
      const result = await api("/api/trading/arm-demo", { method: "POST", body: JSON.stringify({ confirmation }) });
      toast(result.detail, "success");
      logLine(result.detail);
      await refresh();
    } catch (error) { toast(error.message, "error"); logLine(error.message, "warn"); }
  }

  async function armRealClose() {
    const confirmation = prompt('O fechamento REAL poderá encerrar individualmente a posição selecionada. Digite AUTORIZO FECHAMENTO EM CONTA REAL.');
    if (confirmation === null) return;
    try {
      const result = await api("/api/trading/arm-real-close", { method: "POST", body: JSON.stringify({ confirmation }) });
      toast(result.detail, "success");
      logLine(result.detail, "warn");
      await refresh();
    } catch (error) { toast(error.message, "error"); logLine(error.message, "warn"); }
  }

  function riskSummary(engine) {
    const settings = state.snapshot?.risk_settings || {};
    const p = settings.profiles?.[engine];
    if (!p) return "Carregando lote e risco…";
    const mode = p.sizing_mode === "fixed_lot" ? `lote fixo ${number(p.fixed_volume, 8)} · teto de risco ${number(p.risk_per_trade_pct, 3)}%` : p.sizing_mode === "risk_cash" ? `risco ${money(p.risk_cash, state.snapshot?.mt5?.account?.currency)}` : `risco ${number(p.risk_per_trade_pct, 3)}% do patrimônio`;
    return `${mode} · lote máximo ${number(p.max_volume, 8)} · reserva da margem livre ${number(p.margin_reserve_pct, 2)}% · perda diária ${number(settings.daily_loss_limit_pct, 3)}%`;
  }

  function loadRiskForm() {
    const form = $("#risk-settings-form");
    const settings = state.snapshot?.risk_settings;
    const p = settings?.profiles?.[form.elements.engine.value];
    if (!p) return;
    Object.entries(p).forEach(([key,value]) => {if (form.elements.namedItem(key)) form.elements.namedItem(key).value = value;});
    form.elements.daily_loss_limit_pct.value = settings.daily_loss_limit_pct;
    form.dataset.initialized = "true";
    form.dataset.dirty = "false";
    riskModeFields();
  }
  function riskModeFields() {
    const form = $("#risk-settings-form");
    const mode = form.elements.sizing_mode.value;
    form.querySelector('[data-risk-field="pct"]').classList.toggle("hidden", mode === "risk_cash");
    form.querySelector('[data-risk-field="cash"]').classList.toggle("hidden", mode !== "risk_cash");
    form.querySelector('[data-risk-field="fixed"]').classList.toggle("hidden", mode !== "fixed_lot");
  }
  function renderRiskSettings(snapshot) {
    const bridge = snapshot.mt5?.clock_bridge;
    const bridgeHealth = $("#clock-bridge-health");
    if (bridgeHealth) bridgeHealth.textContent = bridge?.ok
      ? `${bridge.publisher === "ScalperLabClockService" ? "Relógio independente ativo" : "Relógio legado do calendário"} · publicação há ${number(bridge.snapshot_age_seconds, 0)} s · identidade ${bridge.identity_scope === "terminal" ? "do terminal conferida" : "somente da conta"}.`
      : bridge?.detail || "Relógio indisponível; conecte o MT5 e inicie ScalperLabClockService.";
    const form = $("#risk-settings-form");
    if (!form.dataset.initialized) loadRiskForm();
    const running = snapshot.analyst?.state?.running || snapshot.engine?.state?.running;
    $("#risk-settings-save").disabled = Boolean(running);
    $("#risk-settings-status").textContent = running ? "Pare os motores para salvar alterações." : form.dataset.dirty === "true" ? "Alterações ainda não salvas." : "Perfil salvo · motores precisam ser iniciados manualmente.";
    $("#risk-version").textContent = `Versão ${snapshot.risk_settings?.version || "—"}`;
    $("#analyst-risk-summary").textContent = riskSummary("analyst");
    $("#strategy-risk-summary").textContent = riskSummary("strategy");
    $("#risk-currency").textContent = `Moeda da conta: ${snapshot.mt5?.account?.currency || "indisponível"}`;
    const day = snapshot.risk_day || {};
    $("#risk-daily-status").textContent = day.available ? `${day.blocked ? "NOVAS ENTRADAS PAUSADAS" : "LIMITE DIÁRIO"} · Desde ${new Date(day.reference_at).toLocaleString("pt-BR")} · Perda ${money(day.loss_cash, snapshot.mt5?.account?.currency)} / ${money(day.limit_cash, snapshot.mt5?.account?.currency)} · Última conferência ${new Date(day.checked_at).toLocaleTimeString("pt-BR")}. Dia de risco: UTC.` : day.detail || "Aguardando conta.";
    const select = $("#risk-preview-symbol");
    const items = state.marketWatch?.items || [];
    const signature = JSON.stringify(items.map(x => x.broker_symbol));
    if (select.dataset.catalog !== signature) {
      const old = select.value;
      select.innerHTML = '<option value="">Selecione um ativo</option>' + items.map(x => `<option value="${escapeHtml(x.broker_symbol)}">${escapeHtml(x.broker_symbol)}</option>`).join("");
      if (items.some(x => x.broker_symbol === old)) select.value = old;
      select.dataset.catalog = signature;
    }
    const contract = items.find(x => x.broker_symbol === select.value);
    $("#risk-symbol-contract").textContent = contract ? `Mínimo ${number(contract.volume_min, 8)} · passo ${number(contract.volume_step, 8)} · máximo ${number(contract.volume_max, 8)}` : "Especificações recebidas do MT5.";
  }
  async function saveRiskSettings(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    const engine = values.engine;
    const daily_loss_limit_pct = values.daily_loss_limit_pct;
    delete values.engine; delete values.daily_loss_limit_pct;
    try {
      const result = await api("/api/settings/risk", {method:"POST",body:JSON.stringify({engine,profile:values,daily_loss_limit_pct})});
      form.dataset.dirty = "false";
      toast(result.detail,"success");
      $("#risk-preview-result").textContent = "Perfil alterado. Calcule uma nova prévia.";
      await refresh(); loadRiskForm();
    } catch(error) {toast(error.message,"error");}
  }
  async function previewRisk(event) {
    event.preventDefault();
    const form = $("#risk-settings-form");
    if (form.dataset.dirty === "true") {toast("Salve lote e risco antes de calcular a prévia.","error"); return;}
    const data = Object.fromEntries(new FormData(event.currentTarget));
    data.engine = form.elements.engine.value;
    $("#risk-preview-button").disabled = true;
    $("#risk-preview-result").textContent = "Consultando cotação, contrato e margem no MT5…";
    try {
      const r = await api("/api/settings/risk/preview",{method:"POST",body:JSON.stringify(data)});
      $("#risk-preview-result").textContent = `${r.symbol} · entrada ${number(r.entry,8)} · lote ${number(r.volume,8)} · perda estimada ${money(r.estimated_loss,r.currency)} · margem ${money(r.margin_required,r.currency)} · margem livre após entrada ${money(r.margin_free_after,r.currency)}. ${r.detail}${r.daily_reference_available ? "" : " Referência diária ainda não iniciada."}`;
    } catch(error) {$("#risk-preview-result").textContent = error.message;}
    finally {$("#risk-preview-button").disabled = false;}
  }

  async function saveEngineProfile(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const config = Object.fromEntries(new FormData(form).entries());
    try {
      const result = await api("/api/engine/profile", { method: "POST", body: JSON.stringify(config) });
      toast(result.detail, "success");
      await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  async function saveAnalystProfile(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const config = Object.fromEntries(new FormData(form).entries());
    config.symbols = [...(state.selectedAnalystSymbols || [])];
    if (!config.symbols.length) { toast("Selecione pelo menos um ativo do Market Watch.", "error"); return; }
    try {
      const result = await api("/api/analyst/profile", { method: "POST", body: JSON.stringify(config) });
      toast(result.detail, "success");
      await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  async function startAnalyst(mode) {
    const real = mode === "real";
    const target = real ? "REAL" : "DEMO";
    const accountMode = state.snapshot?.mt5?.account?.mode;
    if (mode !== "observacao" && accountMode !== target) {
      toast(`Conecte uma conta ${target} no MT5 antes de iniciar esse modo. Conta atual: ${accountMode || "não identificada"}.`, "error");
      return;
    }
    const symbols = [...(state.selectedAnalystSymbols || [])];
    if (!symbols.length) { toast("Atualize o catálogo do MT5 e selecione ao menos um ativo.", "error"); return; }
    const runtime = state.snapshot?.analyst?.state || {};
    const switchingObservation = runtime.running && runtime.mode === "observacao" && mode !== "observacao";
    if (runtime.running && !switchingObservation) {
      toast("O Analista já está em execução. Pare o modo atual antes de iniciar outro.", "error");
      return;
    }
    let confirmation = "";
    const phrase = real ? "AUTORIZO ANALISTA EM CONTA REAL" : "INICIAR ANALISTA SOMENTE DEMO";
    const account = state.snapshot?.mt5?.account || {};
    const transition = switchingObservation ? " A observação atual será encerrada para iniciar este modo." : "";
    const confirmationText = `O Analista poderá enviar ordens à conta ${target} ${account.login || ""}@${account.server || ""} quando um sinal confirmar. Ativos: ${symbols.join(", ")}. ${riskSummary("analyst")}.${real ? " A perda real pode exceder estimativas." : ""}${transition} Digite exatamente: ${phrase}`;
    if (switchingObservation) {
      confirmation = prompt(confirmationText);
      if (confirmation === null) return;
    }
    try {
      if (switchingObservation) {
        const stopped = await api("/api/analyst/stop", { method: "POST", body: JSON.stringify({}) });
        toast(stopped.detail, "success");
      }
      const form = $("#analyst-form");
      const config = {
        symbols,
        timeframe: form.elements.namedItem("timeframe").value,
        decision_basis: form.elements.namedItem("decision_basis").value,
      };
      const prior = state.snapshot?.analyst?.config || {};
      const profileChanged = JSON.stringify(config.symbols) !== JSON.stringify(prior.symbols || [])
        || config.timeframe !== prior.timeframe || config.decision_basis !== prior.decision_basis;
      if (profileChanged) {
        const saved = await api("/api/analyst/profile", { method: "POST", body: JSON.stringify(config) });
        toast(saved.detail, "success");
        await refresh();
      }
      if (mode !== "observacao") {
        const clockReady = !profileChanged && state.snapshot?.system_clock?.status === "synchronized"
          && state.snapshot?.system_clock?.mt5_status === "verified";
        if (!clockReady) {
          const clock = await api("/api/system/clock/synchronize", {
            method: "POST", body: JSON.stringify({ read_only: true }), timeoutMs: 60000,
          });
          if (state.snapshot) state.snapshot.system_clock = clock;
          renderClockStatus(clock);
          if (!clock || clock.status !== "synchronized" || clock.mt5_status !== "verified") {
            toast(clock?.detail || "Não foi possível validar o horário UTC. Use Verificar horário UTC para corrigir a fonte.", "error");
            return;
          }
        }
        if (!switchingObservation) {
          confirmation = prompt(confirmationText);
          if (confirmation === null) return;
        }
      }
      const result = await api("/api/analyst/start", { method: "POST", body: JSON.stringify({ mode, confirmation }) });
      toast(result.detail, "success");
      await refresh();
    } catch (error) { toast(`${error.message} Se o UTC exigir correção, use Verificar horário UTC.`, "error"); }
  }

  async function stopAnalyst() {
    try {
      const result = await api("/api/analyst/stop", { method: "POST", body: JSON.stringify({}) });
      toast(result.detail, "success");
      await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  async function startEngine(mode) {
    let confirmation = "";
    if (mode === "demo" || mode === "real") {
      const real = mode === "real";
      const phrase = real ? "AUTORIZO MOTOR EM CONTA REAL" : "INICIAR MOTOR SOMENTE DEMO";
      confirmation = prompt(`Isso permite ao motor enviar ordens automaticamente na conta ${mode.toUpperCase()}, com ${riskSummary("strategy")}. Digite ${phrase}.`);
      if (confirmation === null) return;
    }
    try {
      const result = await api("/api/engine/start", { method: "POST", body: JSON.stringify({ mode, confirmation }) });
      toast(result.detail, "success");
      await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  async function stopEngine() {
    try {
      const result = await api("/api/engine/stop", { method: "POST", body: JSON.stringify({}) });
      toast(result.detail, "success");
      await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  async function emergencyStop() {
    const live = state.snapshot?.mt5?.account?.mode === "REAL";
    const phrase = live ? "FECHAR TODAS AS POSIÇÕES REAL" : "FECHAR TODAS AS POSIÇÕES DEMO";
    const confirmation = prompt(`Ação de emergência em ${live ? "REAL" : "DEMO"}. Isso para os motores e solicita fechamento de todas as posições. Digite ${phrase}.`);
    if (confirmation === null) return;
    if (!confirm(`Confirma fechar todas as posições da conta ${live ? "REAL" : "DEMO"} conectada? O resultado será reconciliado após o envio.`)) return;
    const buttons = [$("#emergency-stop"), $("#sidebar-emergency")];
    for (const button of buttons) button.disabled = true;
    $("#emergency-button-label").textContent = "PROCESSANDO…";
    $("#sidebar-emergency-label").textContent = "PROCESSANDO…";
    $("#sidebar-emergency").dataset.compactLabel = "Aguarde";
    try {
      const result = await api("/api/trading/emergency-stop", { method: "POST", body: JSON.stringify({ confirmation }) });
      toast(result.detail, result.ok ? "success" : "error");
      logLine(result.detail, result.ok ? "" : "warn");
      await refresh();
    } catch (error) { toast(error.message, "error"); logLine(error.message, "error"); }
    finally {
      await refresh();
      for (const button of buttons) button.disabled = false;
    }
  }

  async function testDemoOrder() {
    const confirmation = prompt('Uma compra de 0,01 lote no menor EURUSD disponível será enviada na conta DEMO e fechada imediatamente após a confirmação. Digite ENVIAR TESTE DEMO.');
    if (confirmation === null) return;
    if (!confirm("Executar agora a ordem de teste DEMO de 0,01 lote em EURUSD e solicitar o fechamento imediato? Posições preexistentes não serão alteradas.")) return;
    const button = $("#test-demo-order");
    button.disabled = true;
    try {
      const result = await api("/api/trading/test-order", { method: "POST", body: JSON.stringify({ confirmation }) });
      toast(result.detail, result.ok ? "success" : "error");
      logLine(result.detail, result.ok ? "" : "warn");
      await refresh();
    } catch (error) { toast(error.message, "error"); logLine(error.message, "warn"); }
    finally { button.disabled = false; }
  }

  async function closePosition(ticket) {
    const live = state.snapshot?.mt5?.account?.mode === "REAL";
    const phrase = live ? "FECHAR POSIÇÃO REAL" : "FECHAR POSIÇÃO DEMO";
    const confirmation = prompt(`Fechar a posição ${ticket} na conta ${live ? "REAL" : "DEMO"}. Digite ${phrase} para confirmar.`);
    if (confirmation === null) return;
    if (!confirm(`Enviar uma solicitação de fechamento a mercado para a posição ${ticket} da conta ${live ? "REAL" : "DEMO"}?`)) return;
    try {
      const result = await api(`/api/orders/${encodeURIComponent(ticket)}/close`, { method: "POST", body: JSON.stringify({ confirmation }) });
      toast(result.detail, result.ok ? "success" : "error");
      logLine(`Posição ${ticket}: ${result.detail}`, result.ok ? "" : "warn");
      await refresh();
    } catch (error) { toast(error.message, "error"); logLine(error.message, "warn"); }
  }

  async function submitResearch(event) {
    event.preventDefault();
    const query = $("#research-query").value.trim();
    if (!query) return;
    const button = $("#search-form button");
    button.disabled = true; button.textContent = "Pesquisando…";
    try {
      const result = await api("/api/research/search", { method: "POST", body: JSON.stringify({ query }) });
      const updated = await api("/api/state");
      renderState(updated);
      renderProviders(result.providers.map((provider) => ({ name: provider.name, available: provider.ok,
        ok: provider.ok, detail: provider.ok ? `${provider.count} resultado(s) encontrados nesta consulta.` : provider.detail })));
      $("#research-caption").textContent = `${result.items.length} resultado(s) · ${result.saved} novo(s) salvo(s). ${result.message}`;
      toast(`${result.items.length} resultado(s) encontrados; ${result.saved} novo(s) salvos.`, "success");
      logLine(`Pesquisa “${query}”: ${result.items.length} resultado(s) de fontes públicas.`);
    } catch (error) { toast(error.message, "error"); logLine(`Pesquisa falhou: ${error.message}`, "warn"); }
    finally { button.disabled = false; button.innerHTML = '<svg class="icon"><use href="#icon-search"/></svg> Pesquisar fontes'; }
  }

  async function importUrl(event) {
    event.preventDefault();
    const url = $("#source-url").value.trim();
    try {
      const result = await api("/api/research/import-url", { method: "POST", body: JSON.stringify({ url }) });
      renderState(await api("/api/state"));
      toast(`${result.saved} novo(s) item(ns) importado(s).`, "success");
      $("#source-url").value = "";
    } catch (error) { toast(error.message, "error"); }
  }

  async function addFeed(event) {
    event.preventDefault();
    const url = $("#feed-url").value.trim();
    const label = $("#feed-label").value.trim();
    try {
      await api("/api/research/feeds", { method: "POST", body: JSON.stringify({ url, label }) });
      $("#feed-form").reset();
      await renderFeeds();
      renderProviders((await api("/api/state")).providers);
      toast("Feed RSS/Atom cadastrado e fonte inicial importada.", "success");
    } catch (error) { toast(error.message, "error"); }
  }

  async function renderFeeds() {
    const result = await api("/api/research/feeds");
    $("#feed-list").innerHTML = result.items.length ? result.items.map((item) => `<span class="feed-chip">${escapeHtml(item.label)} · ${escapeHtml(new URL(item.url).hostname)}</span>`).join("") : "";
  }

  async function summarizeSelected() {
    const ids = $$("[data-research-id]:checked").map((input) => Number(input.value));
    if (!ids.length) return;
    if (!confirm("Títulos, URLs e trechos públicos selecionados serão enviados ao provedor de IA configurado no ambiente. Código de estratégia e dados da conta não serão enviados. Continuar?")) return;
    const button = $("#summarize-button");
    button.disabled = true; button.textContent = "Analisando…";
    try {
      const result = await api("/api/research/summarize", { method: "POST", body: JSON.stringify({ ids }) });
      const panel = $("#ai-summary");
      panel.textContent = `${result.summary}\n\n${result.disclaimer}`;
      panel.classList.remove("hidden");
      logLine(`Síntese de pesquisa criada para ${ids.length} fonte(s).`);
    } catch (error) { toast(error.message, "error"); }
    finally { button.disabled = false; button.textContent = "Analisar seleção com IA"; }
  }

  async function submitStrategy(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const file = $("#strategy-file").files[0];
    const market = String(form.get("market") || "").trim();
    const timeframe = String(form.get("timeframe") || "").trim();
    const ruleDescription = String(form.get("description") || "").trim();
    let description = ruleDescription;
    if (market) description = `Ativo/universo: ${market}\n${description}`;
    if (timeframe) description = `Período gráfico: ${timeframe}\n${description}`;
    const payload = { name: String(form.get("name") || "").trim(), description };
    if (file) {
      if (file.size > 1_000_000) { toast("O arquivo excede o limite de 1 MB.", "error"); return; }
      payload.filename = file.name;
      payload.source_code = await decodeStrategyFile(file);
    }
    if (!payload.name && !file) { toast("Informe o nome da estratégia ou importe um arquivo.", "error"); return; }
    if (!ruleDescription && !file) { toast("Informe as regras ou importe um arquivo para gerar um rascunho.", "error"); return; }
    const button = $("#strategy-form button[type=submit]");
    button.disabled = true;
    try {
      const result = await api("/api/strategies", { method: "POST", body: JSON.stringify(payload) });
      hideStrategyModal();
      await refresh();
      toast(`Rascunho salvo. ${result.item.validation.summary}`, "success");
      logLine(`Estratégia cadastrada: ${result.item.name}`);
      setView("strategies");
    } catch (error) { toast(error.message, "error"); }
    finally { button.disabled = false; }
  }

  async function reviewStrategy(id, status) {
    const labels = { review: "enviar para revisão humana", approved: "aprovar para estudo; isso não habilita automação", rejected: "rejeitar" };
    if (!confirm(`Confirma ${labels[status]} esta estratégia?`)) return;
    try {
      const result = await api(`/api/strategies/${id}/review`, { method: "PUT", body: JSON.stringify({ status }) });
      toast(`${statusPt[status]}: ${result.item.name}. ${result.note}`, "success");
      await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  async function showStrategySource(id) {
    try {
      const result = await api(`/api/strategies/${id}/source`);
      $("#source-modal-title").textContent = result.filename;
      $("#source-content").textContent = result.source_code;
      $("#source-modal").classList.remove("hidden");
    } catch (error) { toast(error.message, "error"); }
  }

  function hideStrategySource() {
    $("#source-modal").classList.add("hidden");
    $("#source-content").textContent = "";
  }

  document.addEventListener("click", async (event) => {
    const nav = event.target.closest("[data-view]");
    if (nav) setView(nav.dataset.view);
    if (event.target.closest('[data-action="clock-sync"]')) await synchronizeClock();
    const toggleAssets = event.target.closest('[data-action="toggle-dashboard-assets"]');
    if (toggleAssets) {
      state.dashboardShowAll = !state.dashboardShowAll;
      if (state.snapshot) renderDashboardAnalyst(state.snapshot.analyst || {});
    }
    const logFilter = event.target.closest("[data-log-filter]");
    if (logFilter) {
      state.logFilter = logFilter.dataset.logFilter;
      renderLogs(state.snapshot?.logs || []);
    }
    const newStrategy = event.target.closest('[data-action="new-strategy"]');
    if (newStrategy) showStrategyModal();
    if (event.target.closest('[data-action="refresh"]')) await refresh(true);
    const close = event.target.closest("[data-close-ticket]");
    if (close && !close.disabled) await closePosition(close.dataset.closeTicket);
    const review = event.target.closest("[data-review-id]");
    if (review) await reviewStrategy(Number(review.dataset.reviewId), review.dataset.reviewStatus);
    const source = event.target.closest("[data-source-id]");
    if (source) await showStrategySource(Number(source.dataset.sourceId));
    const filter = event.target.closest("[data-strategy-filter]");
    if (filter) {
      state.strategyFilter = filter.dataset.strategyFilter;
      $$("[data-strategy-filter]").forEach((button) => button.classList.toggle("selected", button === filter));
      renderStrategies(state.snapshot?.strategies || []);
    }
  });
  $("#sidebar-toggle").addEventListener("click", () => {
    setSidebarExpanded(!$(".app-shell").classList.contains("sidebar-expanded"));
  });
  $("#refresh-button").addEventListener("click", () => refresh(true));
  $("#arm-demo").addEventListener("click", armDemo);
  $("#risk-arm-demo").addEventListener("click", armDemo);
  $("#arm-real-close").addEventListener("click", armRealClose);
  $("#risk-arm-real-close").addEventListener("click", armRealClose);
  $("#risk-settings-form").addEventListener("submit", saveRiskSettings);
  $("#risk-settings-form").addEventListener("input", () => {$("#risk-settings-form").dataset.dirty = "true"; riskModeFields(); $("#risk-settings-status").textContent = "Alterações ainda não salvas.";});
  $("#risk-settings-form").elements.engine.addEventListener("change", () => {loadRiskForm(); $("#risk-preview-result").textContent = "Calcule uma prévia para o perfil selecionado.";});
  $("#risk-preview-form").addEventListener("submit", previewRisk);
  $("#risk-preview-symbol").addEventListener("change", () => renderRiskSettings(state.snapshot || {}));
  $("#engine-form").addEventListener("submit", saveEngineProfile);
  $("#analyst-form").addEventListener("submit", saveAnalystProfile);
  $("#refresh-market-watch").addEventListener("click", () => refreshMarketWatch(true));
  $("#replay-form").addEventListener("submit", runReplay);
  $("#replay-saved").addEventListener("click", async (event) => {
    event.currentTarget.disabled = true;
    try {
      const response = await api("/api/analyst/replay-saved", {method:"POST",body:"{}",timeoutMs:120000});
      renderReplayReport(response.result);
      $("#replay-status").textContent = response.detail;
    } catch(error) { $("#replay-status").textContent = error.message; }
    finally { $("#replay-saved").disabled = false; }
  });
  $("#replay-refresh").addEventListener("click", () => refreshMarketWatch(true));
  $("#market-watch-search").addEventListener("input", renderMarketWatchPicker);
  $("#market-watch-symbols").addEventListener("change", (event) => {
    const input = event.target.closest('input[type="checkbox"]');
    if (!input) return;
    const selected = new Set(state.selectedAnalystSymbols || []);
    if (input.checked) {
      if (selected.size >= 12 && !selected.has(input.value)) {
        input.checked = false;
        toast("O limite do Analista é de 12 ativos por perfil.", "error");
        return;
      }
      selected.add(input.value);
    } else selected.delete(input.value);
    state.selectedAnalystSymbols = [...selected];
    renderMarketWatchPicker();
    renderAnalyst(state.snapshot?.analyst || {});
  });
  $("#analyst-observe").addEventListener("click", () => startAnalyst("observacao"));
  $("#analyst-demo").addEventListener("click", () => startAnalyst("demo"));
  $("#analyst-real").addEventListener("click", () => startAnalyst("real"));
  $("#analyst-stop").addEventListener("click", stopAnalyst);
  $("#sr-start").addEventListener("click", startSrResearch);
  $("#sr-stop").addEventListener("click", stopSrResearch);
  $("#sr-symbol-1").addEventListener("change", () => renderSrResearch(state.snapshot?.sr_research || {}));
  $("#sr-replay-symbol").addEventListener("change", () => renderSrResearch(state.snapshot?.sr_research || {}));
  $("#sr-replay-form").addEventListener("submit", runSrReplay);
  $("#sr-replay-saved").addEventListener("click", replaySavedSr);
  $("#engine-strategy").addEventListener("change", () => renderEngine(state.snapshot?.engine, state.snapshot?.strategies, state.snapshot?.mt5));
  $("#engine-observe").addEventListener("click", () => startEngine("observacao"));
  $("#engine-demo").addEventListener("click", () => startEngine("demo"));
  $("#engine-real").addEventListener("click", () => startEngine("real"));
  $("#engine-stop").addEventListener("click", stopEngine);
  $("#test-demo-order").addEventListener("click", testDemoOrder);
  $("#emergency-stop").addEventListener("click", emergencyStop);
  $("#sidebar-emergency").addEventListener("click", emergencyStop);
  $("#search-form").addEventListener("submit", submitResearch);
  $("#import-form").addEventListener("submit", importUrl);
  $("#feed-form").addEventListener("submit", addFeed);
  $("#summarize-button").addEventListener("click", summarizeSelected);
  $("#strategy-form").addEventListener("submit", submitStrategy);
  $("#strategy-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    const preview = $("#source-adaptation");
    $("#file-label").textContent = file?.name || "Escolher arquivo";
    if (!file) { preview.textContent = ""; preview.classList.add("hidden"); return; }
    if (file.size > 1_000_000) { toast("O arquivo excede o limite de 1 MB.", "error"); event.target.value = ""; return; }
    try {
      const source_code = await decodeStrategyFile(file);
      const { result } = await api("/api/strategies/validate", {
        method: "POST", body: JSON.stringify({ filename: file.name, source_code }),
      });
      const adaptation = result.adaptation || {};
      const nameField = $("#strategy-form [name=name]");
      const descriptionField = $("#strategy-form [name=description]");
      if (!nameField.value.trim() || nameField.value === nameField.dataset.importSuggestion) {
        nameField.value = adaptation.suggested_name || "Estratégia importada";
        nameField.dataset.importSuggestion = nameField.value;
      }
      if (!descriptionField.value.trim() || descriptionField.value === descriptionField.dataset.importSuggestion) {
        descriptionField.value = adaptation.suggested_description || "Arquivo importado; descreva e revise as regras manualmente.";
        descriptionField.dataset.importSuggestion = descriptionField.value;
      }
      const warnings = result.warnings?.length ? `\nAtenção: ${result.warnings.join(" ")}` : "";
      preview.textContent = `${result.summary}\nFormato: ${adaptation.language || result.kind}. Importado como rascunho; compatibilidade com o motor: revisão manual necessária.${warnings}`;
      preview.classList.remove("hidden");
    } catch (error) {
      preview.textContent = `Não foi possível analisar o arquivo: ${error.message}`;
      preview.classList.remove("hidden");
    }
  });
  $("#close-strategy-modal").addEventListener("click", hideStrategyModal);
  $("#close-source-modal").addEventListener("click", hideStrategySource);
  $("#source-modal").addEventListener("click", (event) => { if (event.target.id === "source-modal") hideStrategySource(); });
  $("#cancel-strategy").addEventListener("click", hideStrategyModal);
  $("#strategy-modal").addEventListener("click", (event) => { if (event.target.id === "strategy-modal") hideStrategyModal(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { hideStrategyModal(); hideStrategySource(); } });

  let sidebarExpanded = false;
  try { sidebarExpanded = localStorage.getItem("scalperlab-sidebar-expanded") === "true"; } catch { /* usa menu compacto */ }
  setSidebarExpanded(sidebarExpanded);
  refresh();
  renderFeeds().catch(() => {});
  setInterval(() => refresh(), 9000);
})();
