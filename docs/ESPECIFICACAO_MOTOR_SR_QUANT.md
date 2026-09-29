# Especificação de pesquisa: motor de zonas e comportamento do preço

**Estado em 29/09/2026:** a primeira versão de pesquisa e replay foi implementada nesta branch, sempre sem ativação de ordens. Este arquivo conserva a especificação e pode conter etapas ainda não aceitas empiricamente. Confira [implementação](IMPLEMENTACAO_SR_QUANT_2026-09-29.md) e [estado atual](ESTADO_ATUAL.md).

**Origem:** `Texto colado.txt` fornecido pelo usuário em 29/09/2026.
**Universo inicial:** símbolos exatos do Market Watch que representem EURUSD e ouro no broker conectado. O nome, contrato e possibilidade de negociação vêm do conector; não há símbolo fixo no código.

## Interpretação da proposta

O documento descreve uma família de estratégias condicionadas ao regime e à localização do preço, e não uma estratégia única baseada em um score. As decisões devem ocorrer em três etapas: contexto conhecido no instante, evento observável numa zona e autorização operacional após custos e risco. Tendência/lateralização e volatilidade são dimensões separadas; volatilidade alta não constitui uma terceira direção de mercado.

As seções de reversão à média e reversão no suporte compartilham o mesmo evento de rejeição. A primeira pode ser um filtro experimental da segunda, não uma segunda ordem independente. Rompimento, reteste e falso rompimento são estados mutuamente exclusivos para uma mesma zona e candle. Um score não transforma um sinal contrário ao regime em sinal válido e não substitui o preflight de risco.

## Situação do ScalperLab

| Componente | Existente | Lacuna para esta proposta |
| --- | --- | --- |
| Dados MT5 | Candles fechados de um timeframe, tick, spread, contrato, conta e posições pelo `TradingPort` | Coleta sincronizada de H1, M15 e M5; ticks históricos para custos/saídas |
| Estrutura | Pivôs confirmados, SMA 21/50, ATR, RSI, Bollinger e tick volume | Zonas persistentes, testes independentes, invalidação e distância em ATR |
| Sinal | Uma regra experimental de pullback à SMA 21 | Regras distintas por regime, máquina de estados e arbitragem de conflitos |
| Risco/execução | Lote por risco, limites, preflight MT5, envio e reconciliação | Gestão parcial, break even e trailing com reconciliação própria |
| Replay | Um timeframe, OHLC, custos assumidos, baseline e corte cronológico | Mesma interface de sinal para múltiplos timeframes, dados por tick e contadores de filtros |
| Eventos | Calendário MT5 como contexto parcial | Política formal de janela por moeda/ativo e estado de dado ausente |

O motor ativo e a regra `pullback_sma21_closed_candle` permanecem intactos durante a pesquisa. Novas estratégias só devem chegar à execução pela mesma porta `TradingPort`, sem SDK MT5 direto nas regras e sem um segundo EA emissor de ordens.

## Contrato de dados e causalidade

Para cada símbolo, obter barras **fechadas** em H1, M15 e M5, mais tick e contrato atuais. M1 pode ser estudado depois como gatilho de execução; não é requisito da primeira versão. Cada decisão registra o horário UTC do gatilho, o último candle fechado usado em cada timeframe, a versão dos dados, o offset/fonte de tempo, a versão da regra e seus parâmetros. Para uma decisão no instante `t`, nenhuma barra pode fechar após `t`. Pivô de largura `w` só existe após `w` barras futuras de confirmação terem fechado; usar o pivô antes disso seria vazamento de futuro.

Ausência de histórico, calendário exigido, tick recente ou contrato negociável produz `DADOS_INSUFICIENTES` ou `BLOQUEADO`, nunca pontuação zero interpretada como confirmação. Em FX, `tick_volume` é atividade observada no broker, não volume consolidado. VWAP calculado com esse dado deve receber o rótulo de aproximação baseada em tick volume; pode ficar fora da versão inicial.

## Zonas e regime

Uma zona é um intervalo `[limite_inferior, limite_superior]`, com lado, timeframe de origem, pivôs que a formaram, instante de confirmação, número de testes independentes, toques, rejeições, idade e condição de invalidação. Sua largura inicial é função do ATR do timeframe de estrutura, sujeita a estudo por ativo. Dois toques em candles adjacentes do mesmo movimento não contam automaticamente como dois testes. Zonas próximas podem ser agrupadas apenas com regra fixa e causal.

O regime tem campos separados: `direcao={alta,baixa,lateral,indefinida}` e `volatilidade={normal,alta,baixa,indisponivel}`. EMA 20/50/200, ADX 14 e pivôs H1/M15 são candidatos para a classificação, não parâmetros aprovados. Empate, contradição entre timeframes e histórico insuficiente resultam em `indefinida`.

## Três estratégias candidatas sem sobreposição

### 1. Continuação após pullback em tendência

- **Condição obrigatória:** regime direcional H1/M15 coerente, zona de suporte para compra ou resistência para venda, zona confirmada antes do setup.
- **Setup M5:** retorno à zona sem rompimento estrutural confirmado; o último candle fechado mostra rejeição na direção da tendência. Limites de pavio/corpo e tolerância da zona são parâmetros de pesquisa.
- **Gatilho:** fechamento de confirmação M5; cotação atual ainda preserva stop, alvo e retorno/risco mínimos após spread.
- **Invalidação:** fechamento além da zona, regime muda, janela de sessão encerra ou setup vence sem confirmação.
- **Stop/alvo:** stop além da zona/estrutura com buffer ATR; alvo na próxima zona oposta ou distância em R, conforme variante testada. Se a resistência/suporte próximo não sustenta o RR mínimo, não operar.

### 2. Rompimento com reteste

- **Condição obrigatória:** zona de resistência/suporte confirmada; candle M5 fecha além do limite externo por distância mínima definida em ATR, com corpo mínimo e custo aceitável.
- **Estado `BREAKOUT_CONFIRMED`:** congelar zona e extremo do rompimento; não comprar/vender imediatamente se a variante estudada exige reteste.
- **Reteste:** em janela finita de candles, o preço visita a zona pelo lado novo sem fechamento invalidante; um candle M5 fecha novamente na direção do rompimento.
- **Invalidação:** fechamento de volta através da zona, janela de reteste expira ou outra posição/setup do mesmo símbolo assume prioridade.
- **Entrada:** na cotação posterior à confirmação, após recalcular custos, stop, alvo, lote e risco no conector.

### 3. Falso rompimento e rejeição em lateralização

- **Condição obrigatória:** regime lateral ou reversão explicitamente permitida, zona confirmada e espaço até a zona oposta.
- **Evento:** máxima ultrapassa resistência (ou mínima ultrapassa suporte), mas o candle M5 **fecha de volta dentro da zona**. Um fechamento além dela pertence à hipótese de breakout, não a esta.
- **Confirmação:** candle seguinte, quando exigido pela variante, confirma rejeição; se não confirmar dentro da janela, descartar.
- **Invalidação:** novo fechamento fora da zona, distância até o alvo insuficiente ou alteração de regime.
- **Stop/alvo:** além do extremo do falso rompimento com buffer ATR; alvo na região central/oposta do range, respeitando RR após custos.

RSI, Bollinger e volume relativo podem ser medidos como variáveis ou filtros candidatos nessa terceira família. Não recebem peso operacional sem demonstrar ganho incremental sobre a mesma regra sem eles.

## Score, filtros e arbitragem

Definir primeiro requisitos obrigatórios por estratégia. Depois calcular um score auditável para **priorizar** candidatos que já passaram: qualidade da zona, estrutura, confirmação, custos e sessão. Os pontos `60/75/100` do texto são exemplos ilustrativos; não são probabilidades nem limiares homologados. Fatores dependentes, como swing, múltiplos testes e suporte forte, não devem somar evidência duplicada.

Uma versão de pesquisa pode guardar `features`, `score_components` e `score_total`, sem converter score em ordem. Para cada símbolo e candle, a arbitragem escolhe no máximo um candidato: primeiro invalida setups vencidos; depois resolve conflito de lado por política explícita; se houver empate contraditório, aguarda. A chave idempotente inclui conta, símbolo, estratégia, zona e candle de confirmação.

Filtros de envio continuam fora do score: conta/mode, UTC, símbolo negociável, cotação recente, spread/custo, posição/ordem existente, limites diários, margem, lote, stop mínimo, `order_check` e reconciliação. Um score alto nunca contorna esses filtros.

## Estado persistente e resultado

`WAITING -> ZONE_DETECTED -> SETUP_FOUND -> WAITING_CONFIRMATION -> SIGNAL_CONFIRMED -> PREFLIGHT -> SENT_UNCERTAIN/RECONCILED/REJECTED -> POSITION_OPEN -> MANAGING -> EXIT -> COOLDOWN`.

Persistir transições por conta/símbolo/estratégia/versão. Depois de reiniciar, consultar posições, ordens e histórico no MT5 antes de retomar. `SENT_UNCERTAIN` nunca provoca reenvio automático. A gestão de TP parcial/break even/trailing é um módulo posterior: só pode mudar stop de posição identificada e reconciliada, com preço e restrições do broker revalidados.

## Sequência de validação

1. Congelar contratos de dados e hipóteses de cada regra; registrar parâmetros iniciais como experimentais.
2. Construir detectores puros de regime, zonas e eventos, com a mesma função chamada em observação e replay. Registrar contadores por filtro, inclusive spread/custo, para explicar ausência de operações.
3. Fazer replay causal com custos do broker. O replay OHLC atual serve à triagem; quando stop e alvo cabem no mesmo candle, o resultado é ambíguo. Para validação operacional, comparar com ticks reais e/ou Strategy Tester MT5 em modo de ticks reais.
4. Separar desenvolvimento, validação cronológica e nova janela independente. Comparar cada família com baseline simples e com versões sem RSI, VWAP, volume e score. Relatar trades e incerteza por ativo, sessão e regime; não selecionar apenas o melhor par/período.
5. Publicar em observação com decisões e motivos persistidos. Só depois habilitar cada família em DEMO por versão, usando o preflight e reconciliação existentes. Nenhuma das regras acima está validada para REAL.

**Primeira entrega recomendada:** detector de zonas + regime e as três famílias apenas em observação/replay, com contadores de filtros. Isso permite descobrir se há sinais suficientes e se os custos deixam espaço antes de ampliar o executor.
