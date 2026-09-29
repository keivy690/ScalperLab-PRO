# Pesquisa e proposta: lote, risco e margem

Data: 28/09/2026. Escopo desta entrega: pesquisa de documentação dos projetos, comparação com o código local e especificação para implementação. Os controles descritos como proposta ainda não foram implementados nem habilitados.

## Referências verificadas

| Referência | Configurações pertinentes | Aplicação ao ScalperLab |
|---|---|---|
| [EarnForex Position Sizer](https://www.earnforex.com/metatrader-expert-advisors/Position-Sizer/) | Volume calculado por entrada, stop e risco; risco percentual ou monetário; edição do volume; painel de margem; limites de exposição. | Principal referência funcional de dimensionamento no MT5. É uma ferramenta de cálculo/execução, não substitui o motor de sinais. |
| [Freqtrade: configuração](https://www.freqtrade.io/en/stable/configuration/) | Capital por operação, orçamento disponível e número máximo de operações abertas. | Separar capital alocado, quantidade de posições e risco de perda. O stake de uma operação em exchange não equivale diretamente ao lote de um contrato MT5. |
| [Freqtrade: proteções](https://www.freqtrade.io/en/stable/plugins/#protections) | StoplossGuard, MaxDrawdown e CooldownPeriod. | Referência para pausas com motivos e duração explícitos; drawdown e perda diária precisam de definições distintas. |
| [QuantConnect: dimensionamento](https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/position-sizing) | Quantidade por peso da carteira e reserva de poder de compra. | Mostrar o orçamento disponível e a reserva usada no cálculo. Peso da carteira não equivale ao risco até o stop. |
| [QuantConnect: modelos de risco](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/risk-management/supported-models) | Drawdown por ativo/carteira e limites de exposição. Alguns modelos liquidam posições. | Definir explicitamente se uma regra apenas impede entradas ou também solicita encerramento; não copiar liquidação automática como efeito implícito. |

Essas referências sustentam escolhas de engenharia e interface. Não demonstram vantagem estatística da regra de entrada do ScalperLab. Os valores padrão de outros produtos não são parâmetros recomendados para esta conta.

## Situação local confirmada

- Analista: configure grava risco de 0,10% e perda diária de 1%; execução usa constantes correspondentes, teto de 0,01 lote e alvo de 1,5R. O formulário não permite ajustar esses valores.
- Motor de estratégias: risco de 0,01–0,25%, perda diária de 0,1–1% e alvo de 0,5–3R configuráveis; max_volume é gravado como 0,01.
- Conector: recusa volume acima de 0,01 e margem estimada acima de 80% da margem livre atual. Uma posição ou ordem pendente existente impede nova entrada.
- A referência diária do Analista é redefinida a cada início e reside em memória. O motor de estratégias tem persistência e usa o fuso da sessão. É preciso unificar o dia de risco da conta para que reiniciar/trocar motor não renove o orçamento.
- Catálogo tipado expõe volume mínimo e passo; completar volume máximo e limite agregado quando disponíveis no contrato do broker.

Pontos principais: scalperlab/market_analyst.py, execution_engine.py, mt5_gateway.py, trading/models.py, web.py, templates/index.html e static/app.js. Esta consulta não verificou o estado da aplicação aberta.

## Proposta funcional

Criar o bloco “Lote e risco” junto ao perfil de cada motor, com a mesma apresentação e o mesmo serviço de cálculo. Perfis podem ter valores próprios; o limite diário pertence à conta e deve valer para ambos.

| Campo | Semântica proposta |
|---|---|
| Dimensionamento | Por percentual do patrimônio; por valor monetário; ou lote fixo. Apenas um modo ativo. |
| Risco por operação | Orçamento estimado de perda até o stop. Mostrar valor na moeda da conta e percentual equivalente. No modo lote fixo, mantém-se um teto de risco. |
| Lote fixo | Quantidade exata solicitada por símbolo. Se incompatível com contrato, risco ou margem, recusar com motivo; não substituir silenciosamente. |
| Lote máximo | Teto adicional por símbolo para o cálculo automático. Volume mínimo, máximo e passo vêm do MT5. |
| Reserva de margem livre | Percentual da margem livre atual que a nova entrada deve preservar. A regra atual equivale a 20%; exibir essa base claramente. |
| Perda diária máxima | Limite compartilhado da conta, em percentual ou moeda, com data, referência e consumo visíveis. |
| Relação alvo/risco | Expor onde a estratégia permitir; alterações na regra do Analista precisam de versão e avaliação no replay. |
| Limites avançados futuros | Risco agregado, número de posições, pausa após perdas, spread e concentração por moeda/classe. |

Risco até o stop e margem são grandezas diferentes. A margem é garantia exigida para abrir a posição. Uma ordem pode caber na margem e ultrapassar o orçamento de perda.

Começar com as configurações atuais como valores migrados, sem aumentar automaticamente lote ou percentuais. A seleção de vários ativos deve permitir limites por símbolo: 0,01 lote pode não existir em determinado contrato. Um campo global pode servir como teto, desde que cada símbolo mostre a compatibilidade.

## Cálculo e contrato do conector

1. Receber sinal com símbolo exato, lado, entrada e stop válidos; consultar contrato, cotação, conta, posições e ordens pendentes.
2. Calcular o orçamento em moeda da conta. Percentual usa patrimônio atual; valor monetário usa o valor salvo. Disponibilizar o cálculo mesmo em observação.
3. Usar [order_calc_profit](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcprofit_py) para estimar a perda entre entrada e stop. Evitar valor de pip universal; contratos e moedas diferem. Usar um volume de referência aceito pelo contrato, converter proporcionalmente e revalidar o volume final.
4. Em automático, escolher um volume permitido que respeite orçamento e teto, arredondando para baixo pelo passo. Abaixo do mínimo: recusar, sem elevar o risco. Em fixo: verificar a quantidade escolhida; erro deve indicar mínimo, máximo e passo.
5. Conferir [order_calc_margin](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcmargin_py), reserva e [order_check](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py). O cálculo isolado de margem não considera posições e ordens pendentes; não somar margens ingenuamente ao ampliar para múltiplas posições. Pré-checagem aprovada não confirma execução.
6. Recalcular antes do envio se preço/conta/contrato mudarem. Bloquear valores não finitos, limites inválidos, dados indisponíveis e SL incompatível.
7. Registrar perfil e versão, volume pretendido/calculado, perda estimada, margem, restrição determinante, resultado do broker e reconciliação. Nunca repetir automaticamente uma ordem de resultado desconhecido.

Os limites de volume devem seguir as [propriedades oficiais do símbolo](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants), incluindo exposição direcional agregada quando aplicável. Custos informados e tolerância de execução devem aparecer separados da estimativa até o stop; gaps podem ultrapassar essa estimativa.

## Perda diária e recuperação

Persistir estado por servidor, login, modo de conta e dia de risco; adotar UTC inicialmente, independente do fuso da estratégia. Guardar patrimônio inicial observado, horário dessa observação, fluxo líquido de depósitos/saques, consumo e bloqueio. Reiniciar o programa, salvar perfil ou trocar motor no mesmo dia não deve apagar esse estado.

Com uma referência válida, perda = patrimônio de referência + fluxo líquido externo posterior − patrimônio atual. Assim, resultados fechados e flutuantes entram na variação sem contar depósitos como lucro ou saques como perda. Validar classificação de deals de saldo/crédito da corretora.

Se o aplicativo não observou o início do dia, não chamar a primeira leitura tardia de patrimônio à meia-noite. Exibir “desde HH:MM UTC” e reconstruir somente o que o histórico permite. Até estabelecer uma referência confiável, novas entradas aguardam resolução. Atingir o limite pausa novas entradas; encerramento de posições é uma política própria.

## Entregas e critérios de aceite

1. **Base de risco compartilhada:** esquema versionado, validação no backend, cálculo comum aos dois motores, persistência diária e migração conservadora. Aceite: reinício e troca de motor preservam consumo/bloqueio; campos salvos são realmente utilizados.
2. **Interface e prévia:** modos de dimensionamento, lote, risco, reserva e resumo por símbolo. Mostrar lote mínimo/passo, perda prevista, margem estimada, margem restante e motivo de recusa. Sem sinal/stop disponível, mostrar que a prévia aguarda esses dados. Aceite: não apresentar estimativa fictícia nem volume único para contratos incompatíveis.
3. **Integração:** levar o perfil validado por TradingPort até a verificação final do conector; substituir os tetos fixos distribuídos por limites explícitos. Aceite: aumentar o teto na interface não é ignorado no backend; falha de margem/risco não gera ordem; risco configurado diferente produz resultado correspondente.
4. **Verificação e pacote:** testar volume mínimo maior que 0,01, passos distintos, preço alterado, rejeição, preenchimento parcial/timeout, saldo externo e reinício. Validar em DEMO o volume efetivamente reconciliado e então gerar novo pacote com backup e relatório. Execução normal permanece uma ação explícita do usuário.
5. **Evolução posterior:** múltiplas posições, risco de carteira e concentração somente após substituir a atual regra de uma posição por uma gestão agregada testada. Pausas após perdas entram com histórico persistente e duração definida; não escolher parâmetros por lucro retrospectivo.

Cada entrega deve ter backup de código/dados e reversão própria. Não há razão funcional para alterar as correções UTC e de candles nesta mudança.
