# Plano de evolução do Analista e do motor de decisão

**Plano datado, revisto em 29/09/2026.** O calendário parcial, o replay SMA21 e a pesquisa/replay S/R já estão no código. Notícias/macro estruturadas, validação por ticks, evidência fora da amostra e promoção S/R para execução permanecem pendentes; confira [ESTADO_ATUAL.md](ESTADO_ATUAL.md).

**Estado da leitura:** 25/09/2026
**Escopo:** camada fundamental, coerência entre análise e execução, validação da regra experimental e eventual uso de aprendizado de máquina.

## 1. Estado atual verificado no código

- O Analista calcula estrutura de pivôs, SMA 21/50, inclinação da SMA, ATR, RSI, posição de Bollinger, retorno/momentum e estatísticas descritivas a partir de candles fechados do MT5.
- Uma regra heurística busca pullback e retomada da SMA 21. A elegibilidade depende do alinhamento técnico/quantitativo, candle forte, spread até 0,08 ATR e níveis válidos de stop e alvo (1,5R).
- O calendário econômico MQL5 pode fornecer contexto parcial. Não há notícias ou séries macroeconômicas integradas à regra.
- O código do Analista pode solicitar envio em DEMO ou REAL após armamento, confirmação, risco e preflight. A falta de dados fundamentais não bloqueia atualmente essa regra.
- O modo de observação não envia ordens. Arquivos `.mq5`, `.py` e `.txt` importados passam por análise/classificação, mas não viram código executável do motor.
- O replay OHLC da regra foi implementado como triagem reproduzível: mesma função de sinal, entrada estimada no candle seguinte, spread histórico por candle, slippage/comissão/swap informados, snapshot comprimido e SHA-256. Ele não é um backtest por ticks e não está estatisticamente validado. REAL existir no código não significa homologação.

## 2. Objetivo de produto

Separar claramente três estados que hoje podem ser confundidos:

1. **Leitura disponível:** dados e indicadores calculados, com origem e horário.
2. **Sinal elegível pela regra:** condições determinísticas da versão da regra satisfeitas; isso ainda não demonstra vantagem estatística.
3. **Execução permitida:** conta, modo, relógio, risco, cotação, símbolo e controles do broker aprovados; isso ainda não significa que o servidor executou ou que a operação foi lucrativa.

O relatório deve declarar quando a camada fundamental está `completa_para_perfil`, `parcial`, `atrasada` ou `indisponível`. Nunca converter dado ausente em neutralidade, zero ou confirmação.

## 3. Fases de trabalho

### Fase A — Coerência de comportamento e interface

- Corrigir textos/documentos para refletir que o Analista atual pode enviar ordens quando armado. **Concluído no código/documentação local:** o perfil identifica `technical_quantitative`; a futura opção de três camadas permanece indisponível.
- Separar no estado e na interface `sinal elegível`, `bloqueado por dados`, `preflight`, `enviando`, `confirmado`, `rejeitado` e `resultado desconhecido`.
- Identificar explicitamente a regra como **pullback técnico/quantitativo experimental** quando o fundamental estiver ausente/parcial. **Concluído no perfil, resultados, avisos e confirmação da interface local.**
- **Decisão do produto:** permitir o modo Técnica + quantitativa em separado e identificá-lo na configuração, nos resultados e nas confirmações de execução. Calendário/fundamental é informativo e não participa do gatilho atual. Um futuro modo de três camadas só poderá ser ativado com fontes adequadas e política de indisponibilidade definida.

**Aceite:** tela, logs, API e documentação descrevem o mesmo estado e distinguem sinal de ordem confirmada.

### Fase B — Dados fundamentais para FX

- Especificar primeiro o universo de moedas/símbolos do piloto e o calendário necessário por moeda.
- Integrar eventos com país/moeda, nome, importância, horário e fuso, consenso, valor anterior, valor divulgado, revisões, fonte e timestamp de coleta.
- Acrescentar séries e comunicados oficiais dos bancos centrais com período de referência, horário de publicação e revisão.
- Para notícias, usar API licenciada com cobertura e direitos de uso documentados; não usar scraping de Investing.com como dependência do motor.
- Implementar proveniência, deduplicação, normalização de horário, controle de atraso e indicador de cobertura. O provedor de notícias e eventuais limites de licença ainda precisam ser escolhidos.
- Tratar calendário como risco/evento até haver regra direcional especificada; não deduzir compra/venda apenas pelo título da notícia.

**Aceite:** evento ou série chega ao relatório com fonte e timestamp verificáveis; atraso, divergência de conta ou falta de cobertura aparece como indisponível; uma modalidade que declare exigir fundamental bloqueia entradas nesses estados.

### Fase C — Especificar e validar regras antes de ampliar execução

- Congelar uma versão formal do pullback: universo, timeframe, sessão, entrada, stop, alvo, expiração, saídas e tratamento de dados ausentes.
- Preservar dados brutos e contratos do broker; registrar hash do conjunto de dados, versão do código e parâmetros por experimento.
- Criar replay cronológico sem look-ahead. Modelar bid/ask, spread variável, comissão, swap, slippage, gaps e limites de stops/volume do símbolo.
- Comparar com baselines simples e com a mesma regra sem cada filtro, mantendo holdout intocado e testes walk-forward.
- Reportar quantidade de operações, expectativa líquida, drawdown, distribuição das perdas, custos e incerteza por par, timeframe e regime; não escolher apenas os pares vencedores.

**Entregue parcialmente em 25/09/2026:** replay com candles fechados de até 2.500 barras de um ativo negociável do Market Watch; comparação cronológica 70/30 entre contexto de desenvolvimento e holdout final; baseline fixo de cruzamento do retorno de 20 candles, usando a mesma gestão ATR14, alvo 1,5R e hipóteses de custo; snapshot integral, parâmetros e hash por até 50 execuções. O backend recusa replay enquanto qualquer motor está ativo. A documentação oficial do MT5 confirma que rates Python já vêm em UTC; removida a subtração indevida do offset do tick atual sobre o histórico. O sistema exibe o holdout como triagem OHLC, nunca como homologação ou prova de vantagem.

- **Pendências para concluir a fase:** comparar com dados por tick reais ou Strategy Tester Every tick based on real ticks; testar cobertura/limite de histórico do broker e mudança de horário sazonal; obter comissão, swap/rolagem tripla e conversão monetária histórica efetivos; preservar holdout após qualquer inspeção; obter nova janela independente e validar por regime/sessão. Enquanto o replay usar OHLC, o resultado continua censurado pela ambiguidade intrabar.

**Aceite:** resultado reproduzível em dados fora do período de ajuste, com custo adverso e amostra explícita; critério de aprovação e interrupção definido antes do forward test DEMO.

### Fase D — Validação DEMO supervisionada

- Rodar primeiro em observação e comparar cada sinal com o replay.
- Depois habilitar DEMO em universo limitado e limites explícitos, preservando confirmação e reconciliação.
- Comparar sinal, cotação, ordem, stop/alvo, execução, posição e histórico do terminal.
- Investigar rejeições, timeout e resultados desconhecidos sem reenvio cego.

**Aceite:** critérios operacionais e estatísticos previamente acordados são atendidos por janela de observação definida; qualquer falha de integridade, risco ou reconciliação interrompe novas entradas.

### Fase E — Machine Learning, somente se agregar valor mensurável

- Não treinar um modelo até haver dados rotulados e suficientes, logs reproduzíveis e baseline determinística validada.
- Usar divisão cronológica, prevenção de vazamento, controle de seleção de variáveis e avaliação em períodos intocados.
- Exigir ganho incremental líquido de custos em relação à baseline, estabilidade por regime e monitoramento de drift.
- Inicialmente, usar ML para classificação de regime ou priorização de sinais; manter risco, bloqueios e envio sob regras explícitas.

**Aceite:** melhoria incremental pré-definida em dados fora da amostra, com incerteza reportada, comparação reprodutível e mecanismo de desligamento. Caso contrário, permanecer determinístico.

## 4. Ordem recomendada

1. Finalizar a coerência entre estado exibido, regra e execução.
2. Escolher provedor/licença e cobertura da camada fundamental para o universo piloto.
3. Definir as regras de uso desses dados e implementar proveniência/estado de qualidade.
4. Evoluir a triagem OHLC para replay por ticks ou bid/ask validado, e então avaliar pullback contra baselines em períodos cronológicos reservados.
5. Fazer observação e forward test DEMO com critérios pré-aprovados.
6. Considerar ML só após evidência suficiente e melhoria fora da amostra.

## 5. Fora do escopo de uma conclusão atual

- Não declarar qualquer regra atual como lucrativa ou “validada”.
- Não tratar calendário parcial como análise fundamental completa.
- Não executar scripts importados como código confiável.
- Não considerar compilação, testes unitários ou ordem aceita como prova de robustez estatística ou homologação REAL.
