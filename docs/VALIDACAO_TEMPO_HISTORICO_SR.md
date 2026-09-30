# Tempo histórico do broker para a pesquisa S/R Quant

**Revisão:** 30/09/2026. Esta implementação é exclusiva da pesquisa S/R, somente leitura. Não altera `bar_time.py`, o relógio dos motores de ordens, o perfil de risco ou a autorização de envio.

## O que foi confirmado

- A [referência Python da MetaQuotes](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py) descreve candles e ticks recebidos em UTC e alerta para construir os parâmetros `datetime` em UTC. A [referência de `copy_rates_from_pos`](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py) também limita o histórico ao que está disponível no gráfico do terminal.
- Há [relatos de usuários no fórum MQL5](https://www.mql5.com/en/forum/483468) de barras Python apresentadas três horas à frente do UTC. Esses relatos explicam por que não podemos substituir a medição da instalação pela descrição geral da API; eles **não** estabelecem a regra do servidor XMGlobal-MT5 7.
- Discussões sobre sessões no [Reddit](https://www.reddit.com/r/algotrading/comments/1vcmxit/confused_about_trading_sessions_dstbst_and_broker/) alertam para distinguir o horário do broker dos horários locais de Londres e Nova York. São experiência comunitária, não evidência contratual para este servidor.
- `TimeTradeServer` é calculado no terminal e depende do relógio local, conforme a [referência MQL5](https://www.mql5.com/en/docs/dateandtime/timetradeserver). O snapshot corrente do ClockService é uma âncora para observações atuais, não uma tabela histórica de mudanças sazonais.

## Trilha 1: histórico existente

1. Com motores e pesquisa S/R parados, selecione o primeiro ativo na seção S/R e use **Diagnóstico do horário histórico → Coletar evidência do horário**. A interface chama `POST /api/sr-quant/time-sample`, corpo `{"symbol":"EURUSD#","bars":300}`. A rota local exige o token da sessão e não envia ordens.
2. A amostra contém barras fechadas e em formação M1/M5/M15/H1, tick UTC validado, offset corrente, versão do terminal e servidor. O login e o caminho privado do terminal são removidos antes do armazenamento. O banco guarda o payload comprimido e seu SHA-256. A resposta compara os candles recentes com os já arquivados.
3. Para converter períodos antigos, obtenha da corretora a regra **específica do servidor** por data, sua fonte verificável e âncoras UTC independentes antes e depois de cada transição sazonal. Registre o conteúdo da fonte e seu SHA-256. Teste inverno, verão e os dois limites sazonais, incluindo H1/M15/M5 e ticks.
4. `sr_quant/historical_time.py` implementa a conversão versionada `sr-broker-history-v1`. Ela exige o servidor exato, fonte e âncora por intervalo; rejeita lacunas, intervalos sobrepostos, barras ambíguas e sequência UTC invertida. **Ainda não existe política aprovada para XMGlobal-MT5 7 e a função não foi conectada ao replay.** Nenhuma suposição GMT+2/GMT+3 foi embutida.
5. A ativação futura exige comparação integral com as amostras brutas, alinhamento causal dos três períodos, verificação de transições e regressão dos motores atuais. Uma política incompleta permanece `DADOS_INSUFICIENTES`.

## Trilha 2: observação daqui para frente

- Enquanto a pesquisa S/R estiver iniciada, em cada ciclo o conector lê um tick UTC validado, M1 em formação e o candle atual e anterior de M5/M15/H1. A validação M1 determina se a série veio em UTC ou no horário do servidor naquele instante. Com a pesquisa parada, o arquivo progressivo não recebe novos candles; isso evita competir com os motores de ordens no conector compartilhado.
- Uma observação de candle em formação é persistida por conta, símbolo e período. Somente quando **o mesmo timestamp bruto** reaparece como candle fechado, com offset inalterado e horário causal, o banco arquiva o OHLC fechado, UTC calculado, timestamp bruto e as duas evidências.
- Mudança de conta/terminal, tick desatualizado, sequência inválida ou mudança de offset impedem a certificação daquele candle. Histórico não é retroativamente preenchido com o offset de hoje.
- O banco usa `sr_time_observations`, `sr_verified_bars` e `sr_raw_time_samples` em migração aditiva. O arquivo não alimenta o motor de ordens nem libera automaticamente o replay. É possível reverter a função parando a pesquisa S/R, sem alterar as leituras dos motores existentes.

## Limites e aceite

No momento da implementação, nenhum terminal MT5 estava aberto nesta sessão para uma nova amostra real. Os testes usaram respostas controladas e não comprovam a regra histórica da corretora. A pesquisa S/R continua bloqueada para H1 não confirmado e o replay real continua recusando base UTC não verificada. O arquivo progressivo precisará acumular amostra suficiente e ser confrontado com o histórico bruto e com a fonte independente antes de qualquer promoção.
