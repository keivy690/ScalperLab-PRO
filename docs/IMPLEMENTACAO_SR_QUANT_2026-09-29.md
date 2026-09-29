# Implementação do motor de pesquisa S/R Quant — 29/09/2026

**Estado:** implementado na branch como pesquisa somente leitura. Não foi incluído automaticamente no executável piloto anterior e não teve replay real aceito no servidor XMGlobal observado; veja [estado atual](ESTADO_ATUAL.md).

## Escopo entregue nesta branch

- Núcleo puro em `scalperlab/sr_quant/core.py`: lê H1/M15/M5 fechados, classifica regime, extrai zonas de pivôs confirmados e avalia pullback em tendência, rompimento com reteste e falso rompimento lateral. Cada rejeição tem código e contador. A saída é sempre `research_only` e `order_eligible=false`.
- Observação opcional em `scalperlab/sr_quant/service.py`: no máximo dois símbolos exatos do Market Watch, iniciada manualmente e desligada após reinício. H1/M15 são reutilizados até o próximo fechamento esperado; M5 e tick são relidos a cada ciclo. Chamadas e duração do conector aparecem na avaliação. Não possui método de envio. Conta e terminal são vinculados à sessão; mudança interrompe a pesquisa. O Analista e o motor de estratégias não podem iniciar enquanto a pesquisa ocupa o conector.
- `sr_evaluations` armazena uma avaliação por conta, símbolo, versão e candle M5. O registro inicial é imutável; o limite local é de 20 mil avaliações. `sr_data_events` registra falhas de qualidade de dados em blocos de cinco minutos, preservando o motivo mesmo após reinício. O identificador da conta é SHA-256, sem login em claro nessas tabelas.
- Replay S/R em `scalperlab/sr_quant/replay.py`: usa o mesmo avaliador, divisão 70/30, baseline de momentum, custos informados, abertura do candle seguinte, spread por candle, slippage, comissão/swap e stop primeiro em candle ambíguo. `sr_replay_runs` guarda dados, parâmetros, versão, resultado e hash; o último estudo pode ser reproduzido offline com conferência do hash.
- Interface em **Risco e segurança → Pesquisa de zonas S/R**. Mostra regime, quantidade de zonas, custo relativo ao ATR, hipóteses e filtros por ativo. O replay fica recolhido abaixo. Estados de pesquisa e ordem são distintos.

## Condições de segurança e compatibilidade

- A regra SMA21, os perfis, o replay antigo, o conector, os serviços MQL5 e o caminho atual de envio permaneceram separados. Nenhuma estratégia S/R foi adicionada à seleção de execução DEMO/REAL.
- A pesquisa ao vivo recusa H1/M15 cuja base histórica UTC não esteja confirmada. O replay recusa qualquer timeframe sem essa confirmação. Não usa o offset de hoje para corrigir histórico antigo.
- O novo estudo não altera tetos de lote, margem, perda diária ou UTC. Não inicia o aplicativo ou o motor automaticamente.
- Uma cópia anterior à mudança do banco local foi criada em `%USERPROFILE%\ScalperLabData\backups\before_sr_quant_20260929T195248Z.sqlite3`.

## Evidência de verificação nesta entrega

- Testes de causalidade, falta de timeframe, base UTC não confirmada, idempotência do registro, reprodução determinística e bloqueio de concorrência.
- Regressão existente: 154 testes passaram em 29/09/2026; sintaxe Python/JavaScript e `git diff --check` passaram.
- Após a bateria, a consulta somente de leitura conectou à conta DEMO do terminal XMGlobal-MT5 7 e encontrou 17 símbolos negociáveis. O H1 foi recusado pelo conector porque os candles vieram no horário do servidor; M15 devolveu 95 barras e M5 287 barras de uma cauda recente, ambas com base histórica UTC **não verificada**. Uma execução da pesquisa com EURUSD# iniciou e explicou `DADOS_INSUFICIENTES`, sem ordem. `/api/state` respondeu 200 e mostrou o módulo parado após essa execução. O replay real continuou bloqueado pela qualidade temporal do histórico.
- A [documentação oficial da API Python](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py) descreve timestamps UTC, mas a amostra bruta deste terminal mostrou o candle M1 em formação três horas à frente de UTC, coerente com o offset +03:00 publicado pelo serviço MQL5. A [página oficial da XMTrading](https://www.xmtrading.com/my/platforms) menciona +02:00/+03:00 por estação, mas não confirma a regra de transição para esta conta/servidor XMGlobal. Uma inferência a partir do offset de hoje não será aplicada ao histórico longo.
- **Não houve replay real nem ordem DEMO nesta etapa.** O replay sintético verifica comportamento do código, não rentabilidade.

## Critério para promoção de uma família a DEMO

1. Confirmar a regra histórica de fuso **deste servidor** com fonte da corretora ou evidência independente suficiente; converter cada data por sua regra de vigência e confrontar barras/ticks nas transições de horário. Depois confirmar base UTC e integridade H1/M15/M5 para os símbolos e períodos escolhidos. Registrar qualidade do spread, candles faltantes e custo do broker.
2. Congelar antes da avaliação: universo, sessão, parâmetros, custos base e adversos, janela cronológica independente e baseline. Não escolher parâmetros com o holdout já visto.
3. Exigir amostra suficiente por família/ativo, resultado líquido, drawdown e análise de sensibilidade a custos. O painel marca menos de 30 operações fechadas no holdout como `amostra_insuficiente`; 30 não é aprovação automática.
4. Confrontar eventos do replay com observação MT5 e depois com ticks/Strategy Tester. Investigar divergências de tempo, spread, entrada e saída.
5. Somente após revisão explícita da evidência, implementar seleção de uma única família no executor existente, com chave desligada por padrão e os mesmos controles de conta, UTC, risco, pré-envio e reconciliação. O primeiro ensaio deve ser DEMO, um símbolo e uma família.

O replay OHLC permanece triagem. Mesmo um resultado positivo não é evidência suficiente para operação REAL.
