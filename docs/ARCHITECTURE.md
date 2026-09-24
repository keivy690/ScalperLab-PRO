# Arquitetura inicial

## Processo desktop local

O shell pywebview apresenta a interface responsiva. Um serviço Flask temporário usa porta dinâmica e binding exclusivo a `127.0.0.1`, com token aleatório por processo, validação de host/origin e política CSP. A ponte MetaTrader5 permanece no backend Python e chama o terminal local.

## Módulos

- `research.py`: pesquisa opcional GitHub, Brave, YouTube e feeds RSS/Atom; guarda URL, data, origem e trecho curto.
- `strategy_validation.py`: análise estática de `.py` em subprocesso, verificações estruturais para `.mq5` e classificação de `.txt`; não executa nem compila as fontes. A descrição sugerida é apenas apoio à revisão.
- `mt5_gateway.py`: leitura do terminal/conta/posições e fechamento de posições em demo após armamento e confirmação.
- `trading/ports.py`: contratos `TradingPort` (consumido pelos motores) e `ConnectorV1` (fronteira de terminal), sem dependência de SDK de corretora nas estratégias.
- `trading/models.py`: símbolo normalizado por identidade canônica e nome real do broker, com metadados de preço, volume e permissão de negociação.
- `connectors/`: `ConnectorManager` mantém configurações e conectores sob IDs independentes; `discovery.py` procura instalações comuns do MT5 no Windows sem iniciá-las.
- `market_analyst.py`: leitura contínua de até 12 símbolos/timeframe do MT5. Mantém observação sem ordens ou pode armar caminhos DEMO/REAL independentes com confirmação específica. A regra experimental de pullback usa candles fechados, confluência técnica/quantitativa e retomada da SMA 21; calcula stop/alvo e dimensiona pelo risco do MT5. O calendário MQL5 pode acrescentar contexto fundamental parcial; notícias e séries macroeconômicas continuam indisponíveis.
- `execution_engine.py` / `strategy_rules.py`: monitor persistente de sinais declarativos M1/D1 para cinco adapters registrados; execução apenas em observação ou conta DEMO explicitamente armada.
- `db.py`: SQLite por usuário em `%LOCALAPPDATA%\ScalperLab`; não fica junto ao código instalado.
- `ai_assistant.py`: resumo opcional via Responses API, somente após ação do usuário e com os itens públicos selecionados.

## Estado de execução

O motor oferece perfis declarativos para cinco regras: força cross-sectional de moedas a partir de retornos D1, momentum de série temporal D1, direção pelo swap do broker, reversão do gap de reabertura semanal e ORB M1. São adaptações operacionais; não reproduzem integralmente os artigos nem herdam sua evidência de performance. Cada uma exige símbolo/universo e limites configurados, aprovação humana e conta DEMO para envio. O modo observação não envia ordens. DEMO exige frase explícita a cada inicialização do aplicativo, confirma identidade da conta e envia ordem de mercado com SL/TP ao servidor, após `order_check`; em seguida reconcilia a posição. `order_check` não garante execução. Um resultado ambíguo interrompe o motor e nunca causa reenvio automático.

Cada terminal MT5 roda em um processo worker isolado. Consultas RPC têm timeout de 4 segundos; ações que enviam ou fecham ordens têm limite separado de 30 segundos para não interromper uma operação durante a resposta do broker. Timeout de ação encerra o worker, marca o resultado como desconhecido e nunca repete a ordem. A reconexão usa backoff limitado, e cada terminal serializa suas operações. O desktop também usa um bloqueio de instância única por usuário. Antes de enviar uma ordem, o gateway confere novamente o fingerprint `login@servidor` aprovado, modo DEMO ou REAL confirmado, conexão, permissão de negociação e posições/ordens pendentes. Esses controles não impedem uma ação feita manualmente no terminal ou por outro programa externo.

## Trading Abstraction Layer e Connector v1

Estratégias e analista recebem `TradingPort`; não importam o pacote `MetaTrader5` nem chamam funções do terminal. O adaptador MT5 atual implementa a fronteira `ConnectorV1` e mantém as verificações de conta, risco e reconciliação existentes. O contrato v1 expõe estado do terminal e conta, catálogo de símbolos, Market Watch, ticks, rates, ordens, posições e envio de intenção de ordem através dos caminhos de segurança já existentes.

`Symbol.canonical_symbol` é a identidade interna; `broker_symbol` é o nome exato retornado pelo terminal. Mapeamentos ficam por configuração de terminal. Sem mapeamento explícito, o nome canônico mantém o nome exato do broker em maiúsculas; não se removem sufixos por heurística. Metadados incluem `digits`, `tick_size`, `volume_min`, `volume_step` e `trade_enabled`. `available_symbols` é o catálogo completo do broker; `market_watch_symbols` contém apenas itens visíveis; `selected_symbols` é a seleção persistida do ScalperLab e não altera silenciosamente o Market Watch.

Cada configuração tem `terminal_id` independente, caminho opcional do executável, símbolos selecionados e mapa canônico. O gerenciador cria conectores sob demanda e aceita caminhos de múltiplas instalações; cada worker carrega seu próprio estado da biblioteca MT5. A descoberta local apenas sugere caminhos encontrados; não inicia terminais nem altera configurações.

### Horários do MT5 e normalização UTC

A integração Python do MT5 documenta candles e ticks em UTC ([rates](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py), [ticks](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksfrom_py)). Na instalação XM testada em 2026-09-24 (terminal build 6182), a consulta somente de leitura mostrou `tick.time_msc` e `rates.time` exatamente três horas à frente do relógio UTC do Windows. Por isso o conector não confia cegamente no epoch recebido: ancora cada resposta no tick atual do mesmo símbolo, infere o offset do servidor em passos de 15 minutos, converte ticks e candles para UTC e publica `time_normalization` com offset, idade e resíduo da calibração. O cálculo é repetido a cada consulta para acompanhar mudança de horário sazonal, sem guardar um `-3h` específico da XM.

Se não houver tick atual, se a diferença não corresponder a um fuso reconhecido, se a idade do tick superar 120 segundos ou se o último candle fechado estiver velho para o timeframe, a consulta falha fechada e o analista mostra os dados como indisponíveis. Os limites diários, semanais e mensais permitem os fechamentos normais de fim de semana/feriados; intradiários mantêm janelas mais curtas. Uma segunda verificação bloqueia candles ainda futuros antes de qualquer análise. O relógio do computador precisa estar sincronizado; sem uma referência UTC confiável no host não é possível distinguir um relógio local errado de um offset do servidor usando apenas timestamps do terminal.

Após a correção e reinício em 2026-09-24, a API real analisou `EURUSD#`, `GOLD#`, `XRPUSD#` e `HK50Cash#` em M5: todos reportaram offset `10800` segundos, ticks com idade entre 0,05 e 2,23 segundos e candles fechados sem timestamp futuro. O Analista continuou em observação, com zero tentativas, zero posições e sem novas entradas na auditoria. Essa medição valida a instalação XM ativa; o offset é recalculado por terminal e não presume que outras corretoras usem o mesmo fuso.

## Auditoria e reconciliação de ordens

`AuditedTradingPort` envolve as ações de envio e fechamento usadas pela API, pelo motor e pelo analista. Antes do RPC, grava `correlation_id`, terminal, método, hora UTC, símbolo canônico/do broker, parâmetros operacionais e hash curto do fingerprint da conta; confirmação textual e fingerprint em texto claro não são persistidos. O mesmo ID gera um marcador `SC...`; os comentários são limitados a 29 caracteres, limite conservador confirmado pela `order_check` na instalação XM usada no teste.

O resultado imediato registra estado, tickets, volume/preço disponíveis e retcode. A leitura subsequente consulta histórico de ordens, histórico de negócios e posições. Além da janela temporal de até 31 dias, o conector pode consultar uma ordem pelo ticket e os negócios pela posição, usando `history_orders_get(ticket=...)` e `history_deals_get(position=...)`. A reconciliação usa os tickets da resposta de envio para descobrir o `position_id` e recuperar a entrada e a saída mesmo quando o intervalo temporal não contém os registros. Para ações ambíguas ou evidência incompleta, `POST /api/trading/audit/reconcile` repete apenas essas consultas de leitura. `GET /api/trading/audit` expõe a trilha local autenticada. Estados sem correspondência conclusiva permanecem pendentes; nenhuma rota de reconciliação reenvia, modifica ou fecha uma ordem.

O marcador pode ser alterado ou removido pelo broker. Nesse caso, tickets retornados pelo MT5 ainda permitem correspondência; se o resultado também se perdeu e o histórico não contém o marcador, o item continua pendente para revisão manual. A trilha cobre as ações iniciadas pelo ScalperLab e não inventaria uma correlação para operações manuais ou de outro programa.

O backend aceita corpos HTTP de até 3 MB. A pesquisa aceita até 12 feeds e aplica um orçamento global de 35 segundos, usando conexão HTTPS direta para preservar a verificação do endereço do servidor; redes que exigem proxy explícito podem não conseguir coletar fontes nesta versão.

Tetos codificados: 0,01 lote, uma tentativa por sessão para ORB/gap e por candle D1 fechado nas regras diárias, nenhuma posição preexistente por conta e perda diária de 0,1–1% (limite escolhido no perfil). Risco por ordem é limitado a 0,25% e o lote é calculado com `order_calc_profit`; estimativa não inclui comissão, swap, slippage, gaps ou falha de stop. Ao parar o motor, posições abertas permanecem no MT5 e dependem de SL/TP aceitos pelo servidor ou ação posterior do usuário. Ao reiniciar o app, o motor permanece parado.

Descrições livres e arquivos `.py`/`.mq5`/`.txt` não têm contrato executável e nunca são interpretados pelo motor. Só regras declarativas explicitamente suportadas podem ser configuradas; código importado exige tradução e homologação manual. A conta CONTEST não pode iniciar motores de ordem. A conta REAL possui caminhos de envio com confirmações e controles próprios, mas não está homologada para operação real.

O analista de mercado é um caminho adicional e não depende de uma estratégia cadastrada. Seu resultado é contextual/candidato; o veredito final fica em `AGUARDAR` enquanto não houver dados fundamentais estruturados, regra de entrada/saída validada e replay com custos. Não há conexão entre candidato do analista e envio de ordens.

## Extensão futura

### Ciclo de vida do Connector v1

Cada terminal roda em um worker independente. O processo principal envia operações permitidas por pipe privado, com ID sequencial e timeout. A requisição v1 contém ID, nome permitido da operação, argumentos e opções; a resposta contém o mesmo ID, indicador de sucesso e resultado ou erro. Os estados publicados são disconnected, connecting, ready, degraded e error. Heartbeats consultam terminal, conta e fingerprint login@servidor; a mudança de identidade desarma ambos os motores no worker. Desconexões do broker deixam o worker ativo para a retentativa existente do adapter. Queda ou timeout fatal encerra o worker e agenda reinício com backoff exponencial limitado. Uma resposta de ordem perdida é tratada como desconhecida, sem repetição automática.

Em 2026-09-24, a conexão somente de leitura e o endpoint GET /api/state foram verificados no Windows com uma conta DEMO: HTTP 200, worker ready, heartbeat presente, motores desarmados e nenhuma ordem enviada. Essa checagem confirma inicialização e leitura de estado; não valida envio, fechamento ou reconciliação de ordens.

O teste manual `place_demo_smoke_order` exige confirmação explícita, conta conectada em DEMO, negociação permitida e ausência de posições e ordens pendentes. Ele valida a ordem com `order_check`, verifica novamente identidade, conexão, permissões e conta vazia, envia uma única compra EURUSD de volume mínimo até 0,01, identifica a posição por magic/comment e tenta fechá-la uma vez. A aprovação requer resposta de abertura, posição identificada, fechamento aceito e posição reconciliada como ausente. Erro ou timeout no envio, resposta sem posição correlacionável ou fechamento parcial fica como estado desconhecido/parcial; não há reenvio cego e a exposição remanescente deve ser verificada no terminal.

Na execução operacional de 2026-09-24 na instalação XM, a compra `EURUSD#` de 0,01 foi aceita. A primeira pré-checagem do fechamento foi rejeitada porque o comentário de 31 caracteres não era aceito pelo MT5; não houve reenvio da compra. O comentário foi reduzido para 29 caracteres, a posição foi identificada pelo ticket/magic/comentário e fechada em uma ação individual auditada (retcode 10009). A primeira reconciliação não achou os registros na janela UTC; a consulta direta por tickets encontrou as duas ordens e os dois negócios da posição, confirmou volume aberto/fechado de 0,01 e vinculou o fechamento ao smoke test. A verificação final mostrou zero posições e zero ordens pendentes. O Analista e o motor de estratégias ficaram parados e as proteções de ordem ficaram desarmadas. Esse resultado valida o caminho controlado nessa instalação; não valida lucratividade, outras corretoras/símbolos ou operação REAL.

Antes de tratar outra regra ou a operação REAL como homologada: definir contrato declarativo, replicação/backtest reproduzível, especificação por broker/símbolo, validação de custos e testes forward demo, reconciliação e recuperação de falhas, limites de risco aprovados, telemetria e revisão operacional independente. O caminho REAL já existe no código e exige confirmação explícita; essa capacidade não substitui esses critérios.
