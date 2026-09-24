(() => {
  "use strict";

  const TOKEN = document.querySelector('meta[name="app-token"]')?.content || "";
  const state = { snapshot: null, strategyFilter: "all", research: [] };
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

  function renderConnection(mt5) {
    const connected = Boolean(mt5?.connected);
    const account = mt5?.account;
    const connector = mt5?.connector;
    const lifecycleLabels = {
      disconnected: "Conector desconectado",
      connecting: "Iniciando conector MT5",
      degraded: "MT5 reconectando",
      error: "Falha no conector MT5",
    };
    const dotClass = connected ? "state-dot" : "state-dot muted";
    $("#mini-terminal-state").className = dotClass;
    $("#runtime-dot").className = dotClass;
    $("#runtime-label").textContent = connected ? `Terminal MT5 ${account.mode === "DEMO" ? "DEMO" : "REAL"} conectado` : "Aguardando conexão MT5";
    $("#header-server").textContent = account?.server || "Servidor indisponível";
    $("#mini-terminal-label").textContent = connector?.identity_changed
      ? "Conta mudou; motores desarmados"
      : connected ? "Terminal conectado"
        : lifecycleLabels[connector?.lifecycle] || mt5?.detail || "Aguardando conexão";
    $("#mini-server").textContent = account?.server || "—";
    $("#mini-login").textContent = account?.login || "—";
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
    $("#risk-badge").textContent = emergencyState[2];
    $("#risk-badge").classList.toggle("risk-badge-success", emergency.status === "completed");
    $("#emergency-result").textContent = emergency.detail || "Aguardando comando de emergência nesta sessão.";
    $("#emergency-stop").title = emergency.updated_at
      ? `Última ação: ${new Date(emergency.updated_at).toLocaleString("pt-BR")}` : "Solicitar parada do motor e fechamento DEMO com confirmação";
    $("#test-demo-order").disabled = !(connected && account?.mode === "DEMO");
    const live = account?.mode === "REAL" || account?.mode === "CONTEST";
    const engineState = state.snapshot?.engine?.state || {};
    $("#kpi-risk").textContent = engineState.running
      ? engineState.mode === "demo" ? "Ativo DEMO" : engineState.mode === "real" ? "Ativo REAL" : "Observação" : "Motor parado";
    $("#kpi-risk").className = `kpi-value ${live ? "red-value" : ""}`;
    $("#kpi-risk-detail").textContent = live && !engineState.running ? "REAL exige confirmação explícita" : engineState.running
      ? engineState.detail : "Inicie o motor manualmente para monitorar";
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
  function strategyCard(item, { compact = false } = {}) {
    const detail = item.description || "Sem descrição.";
    const type = item.source_type === "description" ? "DESCRIÇÃO" : item.source_type.toUpperCase();
    const validation = item.validation?.summary || "Aguardando validação";
    const warnings = item.validation?.warnings || [];
    const safeStatus = `<span class="status-chip ${escapeHtml(item.status)}">${escapeHtml(statusPt[item.status] || item.status)}</span>`;
    const tags = `<div class="tag-row"><span class="tag">${escapeHtml(type)}</span>${!compact && item.file_name ? `<span class="tag">${escapeHtml(item.file_name)}</span>` : ""}</div>`;
    const actions = `${item.file_name ? `<button class="text-button" data-source-id="${item.id}">Ver arquivo</button>` : ""}${item.status === "draft" ? `<button class="text-button" data-review-id="${item.id}" data-review-status="review">Enviar para revisão</button>` : ""}${item.status === "review" ? `<button class="text-button" data-review-id="${item.id}" data-review-status="approved">Aprovar para estudo demo</button><button class="text-button" data-review-id="${item.id}" data-review-status="rejected">Rejeitar</button>` : ""}`;
    const stamp = Number.isNaN(Date.parse(item.updated_at)) ? "" : new Date(item.updated_at).toLocaleDateString("pt-BR");
    if (compact) {
      return `<article class="strategy-card strategy-card-compact"><div class="strategy-card-head"><div><h3>${escapeHtml(item.name)}</h3>${tags}</div>${safeStatus}</div><p class="description">${escapeHtml(detail)}</p><div class="strategy-card-foot"><span>${stamp ? `Atualizada ${escapeHtml(stamp)}` : "No catálogo"}</span></div></article>`;
    }
    return `<article class="strategy-card"><div class="strategy-card-head"><div><h3>${escapeHtml(item.name)}</h3>${tags}</div>${safeStatus}</div><p class="description">${escapeHtml(detail)}</p><p class="description">${escapeHtml(validation)}${warnings.length ? ` · ${escapeHtml(warnings.join(" "))}` : ""}</p><div class="strategy-card-foot"><span>Atualizada ${escapeHtml(stamp)}</span><div class="strategy-actions">${actions}</div></div></article>`;
  }

  function renderStrategies(items) {
    const strategies = items || [];
    $("#strategy-count").textContent = `${strategies.length} estratégia${strategies.length === 1 ? "" : "s"}`;
    $("#strategy-total-label").textContent = `${strategies.length} registro(s)`;
    $("#strategy-nav-count").textContent = String(strategies.length);
    const visible = state.strategyFilter === "all" ? strategies : strategies.filter((item) => item.status === state.strategyFilter);
    const empty = '<div class="empty-card">Nenhuma estratégia cadastrada. Use “Nova estratégia” para criar uma descrição ou importar um arquivo .mq5/.py.</div>';
    $("#dashboard-strategies").innerHTML = strategies.length ? strategies.slice(0, 4).map((item) => strategyCard(item, { compact: true })).join("") : empty;
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
    };
    const badge = $("#engine-status");
    badge.textContent = phaseNames[runtime.phase] || (runtime.running ? "ATIVO" : "PARADO");
    badge.className = `status-chip ${runtime.running ? "approved" : runtime.phase === "resultado_desconhecido" ? "rejected" : ""}`;
    $("#engine-detail").textContent = `${runtime.mode === "demo" ? "DEMO · envio automático" : runtime.mode === "real" ? "REAL · envio automático" : runtime.mode === "observacao" ? "OBSERVAÇÃO · sem envio" : "PARADO"} — ${runtime.detail || "Aguardando configuração."}`;
    const signal = runtime.last_signal;
    const signalNode = $("#engine-last-signal");
    if (signal) {
      signalNode.textContent = `Último sinal/execução:\n${signal.side} ${signal.symbol} · lote ${number(signal.volume, 3)}\nEntrada ${number(signal.entry, 8)} · S/L ${number(signal.stop, 8)} · T/P ${number(signal.target, 8)}\nPerda estimada no stop: ${money(signal.estimated_loss, mt5?.account?.currency)}\n${signal.execution?.detail || ""}`;
      signalNode.classList.remove("hidden");
    } else signalNode.classList.add("hidden");
    const selected = allStrategies.find((item) => String(item.id) === select.value);
    const selectedSupported = supportedNames.includes(selected?.name);
    $("#engine-demo").disabled = Boolean(runtime.running || mt5?.account?.mode !== "DEMO" || selected?.status !== "approved" || !selectedSupported);
    $("#engine-real").disabled = Boolean(runtime.running || mt5?.account?.mode !== "REAL" || selected?.status !== "approved" || !selectedSupported);
    $("#engine-observe").disabled = Boolean(runtime.running || !mt5?.connected || selected?.status !== "approved" || !selectedSupported);
    $("#engine-stop").disabled = !runtime.running;
  }

  function renderAnalyst(analyst = {}) {
    const config = analyst.config || {};
    const runtime = analyst.state || {};
    const form = $("#analyst-form");
    if (!form.dataset.initialized) {
      form.elements.namedItem("symbols").value = (config.symbols || []).join(", ");
      form.elements.namedItem("timeframe").value = config.timeframe || "M15";
      form.dataset.initialized = "true";
    }
    const phases = { parado: "PARADO", configurado: "CONFIGURADO", inicializando: "INICIANDO", analisando: runtime.mode === "demo" ? "DEMO ATIVO" : runtime.mode === "real" ? "REAL ATIVO" : "OBSERVANDO", indisponivel: "INDISPONÍVEL" };
    const badge = $("#analyst-status");
    badge.textContent = phases[runtime.phase] || (runtime.running ? "ATIVO" : "PARADO");
    badge.className = `status-chip ${runtime.running ? (runtime.mode === "observacao" ? "" : "approved") : ""}`;
    $("#analyst-detail").textContent = `${runtime.running ? (runtime.mode === "demo" ? "EXECUTANDO DEMO" : runtime.mode === "real" ? "EXECUTANDO REAL" : "SOMENTE OBSERVAÇÃO") : "PARADO"} — ${runtime.detail || "Configure ativo(s) e inicie."}${runtime.last_cycle_at ? ` · Atualizado ${new Date(runtime.last_cycle_at).toLocaleTimeString("pt-BR", { hour12: false })}` : ""}`;
    $("#analyst-observe").disabled = Boolean(runtime.running || !config.symbols?.length);
    $("#analyst-demo").disabled = Boolean(runtime.running || !config.symbols?.length || state.snapshot?.mt5?.account?.mode !== "DEMO");
    $("#analyst-real").disabled = Boolean(runtime.running || !config.symbols?.length || state.snapshot?.mt5?.account?.mode !== "REAL");
    $("#analyst-stop").disabled = !runtime.running;
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
      const candidate = decision.directional_context && decision.directional_context !== "sem_confluência"
        ? `Viés técnico/quantitativo alinhado: ${decision.directional_context}` : "Sem confluência direcional técnica/quantitativa";
      const execution = decision.execution_status ? ` · execução: ${decision.execution_status}` : "";
      return `<article class="analysis-card"><div class="analysis-card-title"><strong>${escapeHtml(item.symbol || "Ativo")}</strong><span>${escapeHtml(item.timeframe || "")}</span><span class="status-chip">${escapeHtml(decision.action || "AGUARDAR")}</span></div><small>${item.last_closed_bar_at ? `Último candle fechado: ${escapeHtml(new Date(item.last_closed_bar_at).toLocaleString("pt-BR"))}` : `${number(item.bars_used, 0)} barras lidas`}</small><div class="analysis-layer-grid"><section class="analysis-layer"><h3>Técnica</h3><div class="analysis-metrics">${metrics.slice(0, 5).map(([label, value]) => `<div><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`).join("")}</div><p>${escapeHtml(technical.volume_note || technical.detail || "Valores descritivos; não são gatilhos de entrada.")}</p></section><section class="analysis-layer"><h3>Quantitativa</h3><div class="analysis-metrics">${metrics.slice(5).map(([label, value]) => `<div><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`).join("")}</div><p>${escapeHtml(quant.method_note || quant.detail || "Sem série suficiente para estatísticas.")}</p></section>${renderFundamentalLayer(fundamental)}</div><div class="analysis-verdict"><strong>${escapeHtml(candidate)}${escapeHtml(execution)}</strong><ul>${reasons}</ul><small>${decision.order_eligible ? "Sinal elegível; no modo DEMO ainda passa pelos bloqueios de conta, cotação, risco e posições." : "Sem sinal confirmado; nenhuma ordem elegível."}</small></div></article>`;
    }).join("");
  }

  function renderDashboardAnalyst(analyst = {}) {
    const runtime = analyst.state || {};
    const analyses = runtime.analyses || [];
    const status = runtime.running
      ? (runtime.mode === "demo" ? "DEMO AUTOMÁTICO" : runtime.mode === "real" ? "REAL AUTOMÁTICO" : "OBSERVANDO")
      : (analyses.length ? "ÚLTIMA LEITURA" : "PARADO");
    const badge = $("#dashboard-analyst-status");
    badge.textContent = status;
    badge.className = `status-chip ${runtime.running && runtime.mode !== "observacao" ? "approved" : ""}`;
    $("#dashboard-analyst-count").textContent = `${analyses.length || (analyst.config?.symbols || []).length} ativo${(analyses.length || (analyst.config?.symbols || []).length) === 1 ? "" : "s"}`;
    $("#dashboard-analyst-caption").textContent = runtime.last_cycle_at
      ? `${runtime.running && runtime.mode !== "observacao" ? `Execução ${runtime.mode.toUpperCase()} armada` : runtime.running ? "Monitoramento ativo" : "Últimos resultados disponíveis"} · Atualizado ${new Date(runtime.last_cycle_at).toLocaleTimeString("pt-BR", { hour12: false })}`
      : "Leituras técnica, quantitativa e fundamental dos ativos monitorados";
    if (!analyses.length) {
      $("#dashboard-analyst-results").innerHTML = `<div class="empty-card">${runtime.running ? "Aguardando o primeiro ciclo de análise dos ativos configurados." : "Configure os ativos e inicie o Analista em Risco e segurança para exibir as leituras aqui."}</div>`;
      return;
    }
    $("#dashboard-analyst-results").innerHTML = analyses.map((item) => {
      const technical = item.technical || {};
      const quantitative = item.quantitative || {};
      const fundamental = item.fundamental || {};
      const decision = item.decision || {};
      const candle = technical.latest_candle || {};
      const ret = typeof quantitative.return_20_bars === "number" ? `${number(quantitative.return_20_bars * 100, 3)}%` : "—";
      const execution = decision.execution_status ? ` · ${decision.execution_status}` : "";
      const reasons = (decision.reasons || []).slice(0, 2).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");
      const updated = item.last_closed_bar_at
        ? new Date(item.last_closed_bar_at).toLocaleString("pt-BR") : `${number(item.bars_used, 0)} barras lidas`;
      return `<article class="analysis-card dashboard-analysis-card"><div class="analysis-card-title"><strong>${escapeHtml(item.symbol || "Ativo")}</strong><span>${escapeHtml(item.timeframe || "")}</span><span class="status-chip">${escapeHtml(decision.action || "AGUARDAR")}</span></div><small>Último candle fechado: ${escapeHtml(updated)}</small><div class="analysis-layer-grid"><section class="analysis-layer"><h3>Técnica</h3><div class="analysis-metrics"><div><span>Estrutura</span><b>${escapeHtml(technical.trend_structure || "indisponível")}</b></div><div><span>Viés</span><b>${escapeHtml(technical.bias || "indisponível")}</b></div><div><span>SMA 21 / 50</span><b>${escapeHtml(number(technical.sma21, 5))} / ${escapeHtml(number(technical.sma50, 5))}</b></div><div><span>ATR 14 / RSI 14</span><b>${escapeHtml(number(technical.atr14, 6))} / ${escapeHtml(number(technical.rsi14, 2))}</b></div></div><p>Candle outside: ${candle.outside_bar ? `sim · ${escapeHtml(candle.direction || "")}` : "não"}</p></section><section class="analysis-layer"><h3>Quantitativa</h3><div class="analysis-metrics"><div><span>Retorno 20 barras</span><b>${escapeHtml(ret)}</b></div><div><span>Viés</span><b>${escapeHtml(quantitative.bias || "indisponível")}</b></div><div><span>Volatilidade ATR</span><b>${escapeHtml(number(quantitative.atr14_vs_recent_median, 3))}</b></div><div><span>Spread / ATR</span><b>${escapeHtml(number(item.quote?.spread_to_atr, 4))}</b></div></div><p>Estatísticas descritivas; não representam probabilidade de lucro.</p></section>${renderFundamentalLayer(fundamental)}</div><div class="analysis-verdict"><strong>${escapeHtml(decision.directional_context || "Sem confluência")}${escapeHtml(execution)}</strong><ul>${reasons || "<li>Sem motivos adicionais registrados.</li>"}</ul><small>${decision.order_eligible ? "Sinal elegível; execução depende do modo DEMO e das verificações de risco." : "Aguardar · sem sinal elegível para ordem."}</small></div></article>`;
    }).join("");
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
    return `<section class="analysis-layer"><h3>Fundamental</h3><strong class="fundamental-status">${state}</strong><p>${escapeHtml(fundamental.detail || "Sem dados fundamentais estruturados para este ativo.")}</p>${events ? `<ul class="fundamental-events">${events}</ul>` : `<p class="fundamental-empty">${empty}</p>`}</section>`;
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
      if (!output.children.length) output.innerHTML = '<div class="terminal-line muted-line">Aguardando atividade do aplicativo…</div>';
      return;
    }
    list.innerHTML = items.slice(0, 10).map((item) => `<div class="activity-row"><time>${escapeHtml(new Date(item.created_at).toLocaleTimeString("pt-BR", { hour12: false }))}</time><b>${escapeHtml(item.level)}</b><span>${escapeHtml(item.message)}</span></div>`).join("");
    output.innerHTML = items.slice(0, 24).reverse().map((item) => `<div class="terminal-line ${item.level === "WARN" || item.level === "CRITICAL" ? "warn" : ""}"><span class="terminal-time">${escapeHtml(new Date(item.created_at).toLocaleTimeString("pt-BR", { hour12: false }))}</span>${escapeHtml(item.message)}</div>`).join("");
  }

  function renderState(snapshot) {
    state.snapshot = snapshot;
    const mt5 = snapshot.mt5;
    const account = mt5.account;
    renderConnection(mt5);
    renderOrders(snapshot.orders, account);
    renderStrategies(snapshot.strategies);
    renderEngine(snapshot.engine, snapshot.strategies, mt5);
    renderAnalyst(snapshot.analyst);
    renderDashboardAnalyst(snapshot.analyst);
    renderResearch(snapshot.research);
    renderProviders(snapshot.providers);
    renderLogs(snapshot.logs);
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

  function setView(name) {
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
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
    try {
      const result = await api("/api/analyst/profile", { method: "POST", body: JSON.stringify(config) });
      toast(result.detail, "success");
      await refresh();
    } catch (error) { toast(error.message, "error"); }
  }

  async function startAnalyst(mode) {
    let confirmation = "";
    if (mode === "demo" || mode === "real") {
      const real = mode === "real";
      const phrase = real ? "AUTORIZO ANALISTA EM CONTA REAL" : "INICIAR ANALISTA SOMENTE DEMO";
      const target = real ? "REAL" : "DEMO";
      confirmation = prompt(real
        ? `A conta REAL enviará ordens a mercado se o sinal experimental confirmar. Limites: risco estimado de 0,10% do equity, 0,01 lote, uma posição. Fundamental indisponível; perda pode exceder o risco estimado. Digite ${phrase}.`
        : `O Analista poderá enviar ordens na conta DEMO, com risco estimado máximo de 0,10% do equity e volume limitado a 0,01 lote. Digite ${phrase}.`);
      if (confirmation === null) return;
      if (!confirm(`Confirma execução automática em ${target}? Verifique conta/servidor no MT5. A análise fundamental continua indisponível.`)) return;
    }
    try {
      const result = await api("/api/analyst/start", { method: "POST", body: JSON.stringify({ mode, confirmation }) });
      toast(result.detail, "success");
      await refresh();
    } catch (error) { toast(error.message, "error"); }
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
      confirmation = prompt(`Isso permite ao motor enviar ordens automaticamente na conta ${mode.toUpperCase()}, com limite de 0,01 lote e tetos de risco configurados. Digite ${phrase}.`);
      if (confirmation === null) return;
      if (!confirm(`Confirma iniciar a estratégia aprovada em ${mode.toUpperCase()}? As posições abertas permanecem no MT5 quando o motor parar.`)) return;
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
  $("#refresh-button").addEventListener("click", () => refresh(true));
  $("#arm-demo").addEventListener("click", armDemo);
  $("#risk-arm-demo").addEventListener("click", armDemo);
  $("#arm-real-close").addEventListener("click", armRealClose);
  $("#risk-arm-real-close").addEventListener("click", armRealClose);
  $("#engine-form").addEventListener("submit", saveEngineProfile);
  $("#analyst-form").addEventListener("submit", saveAnalystProfile);
  $("#analyst-observe").addEventListener("click", () => startAnalyst("observacao"));
  $("#analyst-demo").addEventListener("click", () => startAnalyst("demo"));
  $("#analyst-real").addEventListener("click", () => startAnalyst("real"));
  $("#analyst-stop").addEventListener("click", stopAnalyst);
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

  refresh();
  renderFeeds().catch(() => {});
  setInterval(() => refresh(), 9000);
})();
