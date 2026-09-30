# S/R Quant em DEMO — 30/09/2026

O S/R Quant agora pode analisar e enviar ordens **somente à conta DEMO**, após início manual e confirmação textual própria. Ele começa parado a cada abertura. As três regras experimentais usam H1, M15 e M5 fechados: pullback em tendência, rompimento com reteste e falso rompimento lateral. O usuário pode selecionar qualquer quantidade de ativos negociáveis recebidos do Market Watch; símbolos e sufixos do broker são preservados. Cada ativo é avaliado individualmente, e o tempo de cada ciclo aumenta conforme a quantidade selecionada.

## Como usar

1. Abra o MT5 DEMO, confirme que a negociação automática está habilitada e que ClockService publica dados recentes.
2. Em **Risco e segurança**, valide o horário UTC e configure lote, risco por operação, reserva de margem e limite diário na aba **Configurações**. O S/R usa o perfil persistido de **Estratégias**.
3. Pare o Analista e o motor de estratégias. No painel S/R, marque os ativos desejados do Market Watch ou use **Selecionar todos** e clique em **Iniciar execução DEMO**. Leia a confirmação e digite `INICIAR S/R SOMENTE DEMO`.
4. Acompanhe os estados por ativo. **DEMO armado** significa que o motor pode tentar uma ordem se houver sinal; **CONFIRMADA_MT5** exige posição correlacionada com stop e alvo no terminal. Se não houver sinal, o estado será aguardar ou sem sinal elegível.
5. Use **Parar S/R** para impedir novas entradas. Isso não fecha posições. **Parada de emergência** interrompe os motores e aciona o fluxo de fechamento conforme a conta e a confirmação.

## Caminho técnico

O conector lê ticks UTC com o ClockService e candles brutos H1/M15/M5. Um candle M1 em formação e o tick validam o deslocamento **atual** do servidor. Os indicadores e zonas são calculados na ordem bruta do broker; o deslocamento atual só identifica em UTC o candle recente usado como sinal, para auditoria e deduplicação. Ele não é aplicado a todo o histórico. Falta de âncora, conta, tick, barras, sinal ou qualidade de preço bloqueia o envio daquele ciclo.

Na execução DEMO, o serviço confirma conta e servidor, relógio, risco diário, sinal em candle fechado, stop/alvo e dimensionamento. O gateway auditado confere novamente identidade, permissão de negociação, preço/spread, lote, posições, ordens pendentes, margem, risco, `order_check` e a reconciliação no MT5. Uma intenção por regra/candle/ativo/conta é reservada no SQLite; timeout ou resultado ambíguo não gera reenvio automático. A auditoria de ordens registra a tentativa e o resultado.

## Limites da validação

- A regra é experimental e não tem evidência estatística de rentabilidade no servidor atual. DEMO permite validação operacional, não comprova vantagem.
- O replay histórico S/R continua separado e recusará H1/M15/M5 sem a regra sazonal UTC histórica do broker. O caminho ao vivo não modifica a regra de tempo do replay nem dos outros motores.
- O aplicativo/executável anterior precisa ser reiniciado ou reconstruído para conter esta mudança. Nenhuma sessão DEMO é armada automaticamente após reinício.
- Na leitura somente de leitura de EURUSD# em 30/09, H1/M15/M5 foram avaliados com offset atual +03:00. Não houve sinal elegível nesse ciclo; nenhuma ordem S/R foi enviada nessa leitura.
