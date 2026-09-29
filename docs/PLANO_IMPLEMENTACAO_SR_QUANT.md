# Plano de ação: estratégias de zonas e comportamento do preço

**Acompanhamento:** etapas de código para pesquisa e replay foram implementadas em 29/09/2026; aceite empírico com histórico UTC comprovado, promoção a DEMO e pacote novo continuam pendentes. As “constatações no código atual” abaixo registram a base **antes** desta implementação. Consulte [a entrega](IMPLEMENTACAO_SR_QUANT_2026-09-29.md) e [o estado atual](ESTADO_ATUAL.md).

**Data:** 29/09/2026

**Base funcional:** [ESPECIFICACAO_MOTOR_SR_QUANT.md](ESPECIFICACAO_MOTOR_SR_QUANT.md)
**Resultado pretendido:** três famílias de sinais causais — continuação em tendência, rompimento com reteste e falso rompimento em lateralização — avaliadas com os dados do MT5, primeiro em pesquisa/observação e depois, se aprovadas, por execução DEMO no caminho de risco já existente.

**Andamento em 29/09/2026:** Etapas 0–4 implementadas em código, com backup local e replay sintético reproduzível. O replay ainda não foi executado com histórico real do broker nesta etapa; logo, o aceite empírico das Etapas 1, 3 e 4 depende dessa verificação. Etapas 5–7 permanecem pendentes de evidência e promoção explícita. Detalhes em [IMPLEMENTACAO_SR_QUANT_2026-09-29.md](IMPLEMENTACAO_SR_QUANT_2026-09-29.md).

## 1. Constatações no código atual

- `MarketAnalystEngine` em `scalperlab/market_analyst.py` possui uma regra de pullback SMA 21 e lê 300 candles de **um** timeframe por símbolo a cada ciclo. `analyze_market` e `_maybe_execute` ficam no mesmo módulo.
- `TradingPort.strategy_market_data` em `scalperlab/trading/ports.py` já permite pedir qualquer timeframe suportado; `MT5Gateway.strategy_market_data` em `scalperlab/mt5_gateway.py` devolve barras fechadas, contrato, spread e evidência de normalização temporal. O novo estudo pode começar por essa porta sem introduzir outro emissor de ordens.
- `scalperlab/replay.py` chama a mesma regra atual com OHLC de um timeframe e possui custos assumidos, baseline e divisão cronológica. O endpoint `/api/analyst/replay` recusa execução enquanto um motor está ativo; essa proteção deve permanecer.
- O envio existente calcula volume por risco, confirma conta/UTC, aplica limites do broker e reconcilia a ordem. Essa cadeia deve continuar sendo o único caminho de envio. O calendário é contexto parcial no modo técnico/quantitativo.
- `activity_log` é uma lista curta de mensagens; não registra uma avaliação estruturada por símbolo, candle, filtro e versão. `trade_audit` cobre tentativas de ordem, não todos os sinais rejeitados.
- O checkout contém muitas alterações locais ainda não consolidadas. Antes de editar módulos compartilhados, identificar a base exata e preservar essas alterações. A inspeção de processos desta data não encontrou ScalperLab nem MT5 abertos; rever o estado no momento da implantação, pois isso pode mudar.

## 2. Regras para não quebrar o que funciona

1. Congelar uma referência do código, configuração, banco e pacote atual. Fazer cópia recuperável do banco **fora** da pasta do executável. Não sobrescrever arquivos modificados por outro trabalho.
2. Criar módulos novos sob `scalperlab/sr_quant/`; manter `analyze_market`, o perfil salvo, o endpoint atual e o replay atual com o mesmo comportamento padrão.
3. A pesquisa nova começa desligada por padrão e não arma o `TradingPort`. A ativação de observação não muda o modo nem a seleção da regra existente.
4. Ler símbolos exatos e contratos do Market Watch; não fixar `EURUSD` ou `XAUUSD`, nem remover sufixos do broker. Começar com no máximo dois símbolos selecionados para medir carga do conector.
5. Não mudar o limite atual de spread de `0,08 ATR` apenas para produzir operações. Medir sua rejeição por ativo/timeframe e definir variantes de custo em pesquisa.
6. Persistir versão de regra, parâmetros, conta/terminal, horário e hash dos dados. Alterações de parâmetros criam nova versão de estudo; não reescrever resultados antigos.
7. Replays e novas famílias não enviam ordens; uma eventual liberação DEMO exige chave de habilitação própria, perfil explícito e o mesmo preflight e reconciliação existentes. Uma mudança no código não deve iniciar/rearmar o motor automaticamente.

## 3. Entregas sequenciais e critérios de aceite

### Etapa 0 — Base e diagnóstico

**Fazer:** inventariar as alterações locais, dependências, banco, perfis salvos, símbolos do broker e serviços de relógio; registrar comportamento atual do Analista, conector, replay e risco. Guardar snapshot do banco e uma referência recuperável do código. Separar alterações preexistentes das novas.

**Aceite:** estado de partida documentado; cópias recuperáveis; fluxo antigo continua produzindo os mesmos estados e motivos para amostras congeladas. Nenhum processo em execução é interrompido para criar a referência.

### Etapa 1 — Contrato de dados multitemporais

**Fazer:** criar `MarketFrameBundle` para H1, M15 e M5, usando inicialmente `TradingPort.strategy_market_data` em chamadas serializadas. Cada série inclui último candle **fechado**, timestamp UTC, qualidade/frescor, contrato e origem da conversão temporal. Definir relógio de decisão `t` pelo fechamento M5: H1/M15 só podem incluir candles fechados até `t`. Identificar indisponibilidade por timeframe e impedir fallback silencioso. Cachear H1/M15 até um novo fechamento para não multiplicar leituras a cada ciclo.

**Risco específico:** `strategy_market_data` usa evidência de M1 em formação para normalizar a cauda recente; o replay histórico multitemporal não pode aplicar indiscriminadamente o offset atual a datas antigas ou períodos com horário sazonal diferente. Resolver e demonstrar a base temporal do histórico antes de validar resultados longos.

**Aceite:** fixtures com fechamentos nas bordas de H1/M15, mudança de horário, lacunas e símbolos com sufixo produzem alinhamento causal; dado faltante gera `DADOS_INSUFICIENTES`. A latência e o número de chamadas MT5 por ciclo ficam registrados e dentro de orçamento definido após medição.

### Etapa 2 — Núcleo puro de pesquisa

**Fazer:** módulos separados para regime (`direcao` e `volatilidade`), zonas confirmadas e três detectores de setup. As funções recebem um snapshot imutável e devolvem `SignalCandidate` ou `RejectionReason`; não acessam MT5 nem banco. Pivôs entram somente depois de confirmados; zona tem limites, idade, testes independentes, invalidação e versão. Implementar máquina de estados por símbolo/zona/setup com expiração de reteste e cooldown. Rejeição e breakout para o mesmo candle têm classificação exclusiva.

**Aceite:** mesmas entradas produzem mesmas decisões em observação e replay; nenhuma barra posterior ao instante de decisão altera uma decisão passada. Um evento só gera um candidato por chave conta/símbolo/estratégia/zona/candle. Casos ambíguos resultam em aguardar, com motivo.

### Etapa 3 — Telemetria e observação

**Fazer:** adicionar tabelas novas, sem modificar destrutivamente as atuais, para avaliações, transições de setup e contadores de filtros. Registrar por avaliação: conta/terminal, símbolo exato, timeframe de cada evidência, candle, versão, parâmetros, regime, zona, estratégia, custo, score descritivo, rejeições e estado. Limitar retenção/tamanho e proteger dados sensíveis. Mostrar na interface resumo por símbolo e funil `dados → zona → setup → confirmação → custo → risco`, com modo **pesquisa/sem envio** inequívoco. Ativação padrão desligada.

**Aceite:** o operador consegue explicar por que não houve entrada num intervalo, inclusive bloqueio de spread como no diagnóstico de 29/09; reinício não perde a trilha. O painel não chama um candidato de ordem executada. Uma falha de gravação não abre ordem.

### Etapa 4 — Replay da mesma regra

**Fazer:** adaptar o replay para chamar as funções puras da Etapa 2 com H1/M15/M5 sincronizados. Congelar conjunto de candles/ticks, contrato, custos, parâmetros e hash. Contar candidatos, rejeições por filtro, operações simuladas e eventos ambíguos. Modelar bid/ask, spread variável, slippage, comissão, swap, gaps e restrições de lote/stop. O replay OHLC continua identificado como triagem; comparar depois com ticks reais do broker ou com implementação equivalente no Strategy Tester, sem presumir paridade entre Python e MQL5.

**Aceite:** replay e observação produzem o mesmo sinal quando alimentados com o mesmo histórico causal; diferenças de preço/execução são explicadas separadamente. Relatório compara cada família com baseline e variante sem filtros opcionais, em desenvolvimento e janela cronológica reservada. O holdout atual do pullback não é reutilizado para escolher os novos parâmetros; reservar nova janela independente.

### Etapa 5 — Decisão de qual família merece DEMO

**Fazer:** congelar previamente universo, sessões, custo adverso, mínimos de amostra, métricas de risco e critério de rejeição. Revisar por ativo, timeframe, sessão e regime; não selecionar apenas a combinação vencedora. Score de 0 a 100, VWAP, RSI, Bollinger, ADX e RVOL permanecem candidatos a variável, não gatilhos assumidos. Analisar redundância e ganho incremental. Notícias/calendário só bloqueiam por política explicitamente testada e cobertura conhecida; não inferir direção por título.

**Aceite:** relatório reproduzível com resultados líquidos e incerteza; configuração versionada e decisão explícita de manter, revisar ou descartar cada família. Falta de amostra ou dados é resultado inconclusivo, não aprovação.

### Etapa 6 — DEMO gradual pelo executor existente

**Fazer:** adicionar seleção de uma família/versionamento ao Analista, **desligada por padrão**. A família elegível passa pela mesma validação de conta, relógio, tick recente, ordens/posições, risco, margem, `order_check`, envio e reconciliação. Arbitragem permite no máximo um sinal por símbolo/candle e preserva o armamento exclusivo entre motores. Primeiro um símbolo e uma família; ampliar após observar comportamento. TP parcial/break even/trailing ficam em entrega posterior, com gestão de posição identificada e reconciliação própria.

**Aceite:** sinal, pré-envio, resposta do broker e posição/histórico reconciliados têm a mesma correlação; rejeição, timeout e resultado desconhecido não causam reenvio cego. Parar, emergência, reinício, mudança de conta e falha UTC interrompem novas entradas. A regra SMA21 antiga permanece disponível com resultados iguais aos da referência.

### Etapa 7 — Pacote e reversão

**Fazer:** incluir módulos novos e migrações no pacote Windows `onedir`, sem embutir dados pessoais, conta ou credenciais. Validar caminho de dados do usuário, serviços MQL5 já instalados, primeira execução, atualização e rollback. O recurso pode ser desligado sem reverter o banco; tabelas novas são aditivas. Manter versão anterior do pacote e cópia do banco para recuperação.

**Aceite:** instalação limpa e atualização de instalação existente preservam perfil, replays e auditoria; desabilitar o novo módulo devolve o comportamento anterior sem alterar ordens/posições já existentes.

## 4. Plano de verificação por risco

| Risco | Cenário mínimo |
| --- | --- |
| Vazamento de futuro | pivô ainda não confirmado, H1/M15 em formação e reteste que só se completa depois do gatilho |
| Duplicidade | dois ciclos no mesmo candle, reinício após envio incerto, breakout/fakeout na mesma zona, dois motores armados |
| Contrato do broker | símbolos com sufixo, ativo somente leitura, volume mínimo/passo, stop level, spread variável e mudança de conta |
| Tempo/dados | MQL5 ClockService parado, UTC divergente, candle desatualizado, histórico com lacuna e transição de horário sazonal |
| Risco e execução | limite diário, margem insuficiente, rejeição de `order_check`, preenchimento parcial, timeout e posição não reconciliada |
| Regressão | regra SMA21, replay antigo, configurações salvas, interface, fechamento/ emergência e serviços do MT5 |
| Produto | painel distingue pesquisa, sinal candidato, ordem solicitada e posição confirmada |

Executar verificações estáticas e unitárias nas regras puras, integração simulada da porta MT5, replay reproduzível, integração real **somente leitura** do conector, inspeção visual e, na Etapa 6, teste DEMO autorizado. Relatar cada nível separadamente; passar nos testes não comprova vantagem estatística.

## 5. Ordem recomendada de implementação

1. Fechar Etapas 0–3 como primeira entrega: dados, regras puras e observação com contadores. Nenhuma ordem nova.
2. Fechar Etapas 4–5 como segunda entrega: replay multitemporal, custos e decisão de aprovação por família.
3. Só então Etapas 6–7: uma família em DEMO, reconciliação e pacote atualizado.

**Critério de interrupção:** se a normalização temporal histórica não for confiável, se observação e replay divergirem sem explicação, ou se a auditoria/reconciliação falhar, não avançar para envio DEMO. Corrigir o ponto específico mantendo a regra SMA21 e o conector anteriores operáveis.
