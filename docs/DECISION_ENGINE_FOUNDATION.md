# Fundamentos do analista de mercado

## Objetivo

O ScalperLab passa a ter uma camada de análise de mercado independente do catálogo de estratégias. O operador informa símbolos que existem no Market Watch e um timeframe; M15 é o padrão recomendado, e outros períodos aceitos pelo MT5 podem ser selecionados. O analista lê somente candles fechados e publica três visões separadas: técnica, quantitativa e fundamental.

Esta primeira versão é um analista observacional. Ela não envia ordens e não declara uma vantagem estatística. Uma direção candidata não é um sinal de entrada.

## Leitura das fontes anexadas

### BabyPips - Forex

O arquivo possui 388 páginas e é uma tradução educacional antiga da Escola BabyPips. Ele cobre fundamentos do Forex, leitura gráfica, suporte/resistência, tendência, candles, Fibonacci, médias móveis, indicadores, padrões, pivôs, rompimentos e falsos rompimentos, análise fundamental e notícias, sentimento, plano operacional, dimensionamento, stops, alavancagem e correlação entre moedas.

O motor aproveita esses temas como vocabulário e estrutura de análise, não como combinações de indicadores que garantam entradas. As estatísticas de mercado, regras regulatórias, provedores e exemplos históricos do material não são tratados como dados atuais.

### Análise Técnica dos Mercados Financeiros - Flávio Lemos

O arquivo entregue contém 23 páginas e termina no começo do primeiro capítulo. É uma amostra inicial do livro, não o livro completo. A amostra destaca disciplina e gestão financeira, a relação entre preço e oferta/demanda, tendências, gráficos e planejamento, mas não fornece o conteúdo integral anunciado no sumário. Portanto, o motor não atribui a esse arquivo regras de capítulos que não estão presentes.

### Artigo de Thiago de Sousa Barros (2015)

O artigo compara análise fundamentalista e técnica em sete ações de maior volume da BM&F Bovespa em 2012, usando cotações diárias e indicadores financeiros, médias móveis, suportes/resistências, Bandas de Bollinger, IFR/RSI e estatística descritiva. A conclusão do próprio artigo trata fundamentos como contexto de horizonte mais longo e análise técnica como leitura de prazo menor.

O período, a amostra pequena e concentrada em ações brasileiras e o caráter histórico/descritivo impedem transferir os resultados para qualquer ativo MT5, Forex ou timeframe M15. O documento é evidência de complementaridade conceitual, não homologação de rentabilidade nem validação fora da amostra.

## Como os conceitos entram no aplicativo

### Análise técnica

- Estrutura de mercado: pivôs locais confirmados somente após candles fechados; alta requer dois topos e dois fundos ascendentes, baixa requer os dois descendentes. Casos mistos ficam como indefinidos/laterais.
- Tendência: SMA 21 e SMA 50, com inclinação recente da SMA 21 como contexto, sem converter cruzamentos isolados em ordem.
- Pullback: distância do fechamento à SMA 21 expressa em ATR, candle mais recente (incluindo detecção objetiva de outside bar) e últimos pivôs confirmados de suporte/resistência são apresentados como evidências separadas. O arquivo de pullback não especifica limiares de proximidade, gatilho, stop ou alvo; nenhum valor desses foi inventado.
- RSI 14 e posição relativa às Bandas de Bollinger 20/2 são mostrados como contexto, não como gatilhos universais.
- Tick volume é identificado como contagem de ticks reportada pelo broker. Em Forex OTC não é tratado como volume consolidado do mercado.

### Análise quantitativa

- Retorno direcional das últimas 20 barras, RMS dos retornos e ATR 14 relativo à mediana recente dão contexto descritivo de direção e volatilidade.
- A camada registra se a direção quantitativa coincide com a direção técnica. Não estima probabilidade de sucesso e não calcula Sharpe, expectancy ou drawdown sem um backtest reproduzível com custos.
- Os valores usam candles fechados para reduzir repaint e look-ahead. Dados insuficientes ou OHLC inválido levam a `AGUARDAR`.

### Análise fundamentalista

Os PDFs explicam conceitos e exemplos históricos, mas não oferecem uma série atual de indicadores, comunicados ou calendário por símbolo. A pesquisa pública já cadastrada no ScalperLab não é um feed macro estruturado e atualizado para cada ativo. Por isso, esta camada reporta `indisponível`, nunca inventa viés fundamental.

Ativos de classes diferentes exigem fontes distintas: moedas dependem de dados macro por países/moedas; ações dependem de demonstrações, eventos e dados da empresa; commodities e índices precisam de variáveis próprias do contrato e do subjacente. A integração precisa identificar a classe do símbolo e a cobertura real do provedor.

## Regra de decisão nesta versão

O código agora oferece uma regra experimental explícita para validar em DEMO: direção técnica/quantitativa alinhada; candle fechado retorna à SMA 21 e fecha com corpo de pelo menos 55% do range na direção do viés, fechando no quarto extremo do candle; stop fica além do último suporte/resistência confirmado ou extremo do candle com margem de 0,1 ATR; alvo de 1,5R. O spread precisa ser no máximo 0,08 ATR. Só então o sinal fica elegível para preflight. No modo observação, ele apenas registra; no modo DEMO, pode enviar a ordem após checagem de conta, cotação, posição, lote, risco, stop/alvo e `order_check`.

Essa definição é uma heurística de engenharia para ensaio, não uma estratégia comprovada. O calendário MQL5 pode apresentar contexto fundamental parcial; notícias e séries macroeconômicas continuam indisponíveis. Esta regra de preço não deve ser interpretada como análise completa das três disciplinas. Não há replay/backtest com spread, comissão, slippage, gaps e execução adversa para essa composição. O caminho REAL existe com confirmação explícita, mas não foi homologado.

## Próximos requisitos para decisão e execução

1. Implementar fontes fundamentais estruturadas com timestamp, origem, revisão e tratamento por classe de ativo. A agenda econômica interna do terminal requer integração MQL5; ela não aparece entre as chamadas da API Python usadas pelo ScalperLab.
2. Construir replay sem look-ahead e com especificação real do símbolo MT5, spreads/custos e execução adversa; separar períodos cronológicos de desenvolvimento e validação.
3. Comparar decisões do replay com os registros DEMO e revisar limites por classe de ativo antes de ampliar exposição. Nenhum retorno passado ou exemplo didático será convertido em promessa.

## Implementação disponível

`scalperlab/market_analyst.py` contém análise determinística sobre candles fechados e uma regra heurística de pullback na SMA 21; `MarketAnalystEngine` monitora até 12 símbolos, por padrão em M15, com intervalo de 30 segundos. O perfil é salvo, mas o motor reinicia parado e precisa ser iniciado manualmente. Em DEMO, sinais elegíveis avançam ao preflight de risco e gateway de ordens; observação segue sem ordens. A API MT5 não tem feed fundamental configurado nesta versão, então nenhum relatório fundamental é inferido a partir de preço.
