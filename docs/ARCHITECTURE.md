# Arquitetura inicial

## Processo desktop local

O shell pywebview apresenta a interface responsiva. Um serviço Flask temporário usa porta dinâmica e binding exclusivo a `127.0.0.1`, com token aleatório por processo, validação de host/origin e política CSP. A ponte MetaTrader5 permanece no backend Python e chama o terminal local.

## Módulos

- `research.py`: pesquisa opcional GitHub, Brave, YouTube e feeds RSS/Atom; guarda URL, data, origem e trecho curto.
- `strategy_validation.py`: análise estática de `.py` em subprocesso, verificações estruturais para `.mq5` e classificação de `.txt`; não executa nem compila as fontes. A descrição sugerida é apenas apoio à revisão.
- `mt5_gateway.py`: leitura do terminal/conta/posições e fechamento de posições em demo após armamento e confirmação.
- `market_analyst.py`: leitura contínua de até 12 símbolos/timeframe do MT5. Mantém observação sem ordens ou pode armar caminhos DEMO/REAL independentes com confirmação específica. A regra experimental de pullback usa candles fechados, confluência técnica/quantitativa e retomada da SMA 21; calcula stop/alvo e dimensiona pelo risco do MT5. O calendário MQL5 pode acrescentar contexto fundamental parcial; notícias e séries macroeconômicas continuam indisponíveis.
- `execution_engine.py` / `strategy_rules.py`: monitor persistente de sinais declarativos M1/D1 para cinco adapters registrados; execução apenas em observação ou conta DEMO explicitamente armada.
- `db.py`: SQLite por usuário em `%LOCALAPPDATA%\ScalperLab`; não fica junto ao código instalado.
- `ai_assistant.py`: resumo opcional via Responses API, somente após ação do usuário e com os itens públicos selecionados.

## Estado de execução

O motor oferece perfis declarativos para cinco regras: força cross-sectional de moedas a partir de retornos D1, momentum de série temporal D1, direção pelo swap do broker, reversão do gap de reabertura semanal e ORB M1. São adaptações operacionais; não reproduzem integralmente os artigos nem herdam sua evidência de performance. Cada uma exige símbolo/universo e limites configurados, aprovação humana e conta DEMO para envio. O modo observação não envia ordens. DEMO exige frase explícita a cada inicialização do aplicativo, confirma identidade da conta e envia ordem de mercado com SL/TP ao servidor, após `order_check`; em seguida reconcilia a posição. `order_check` não garante execução. Um resultado ambíguo interrompe o motor e nunca causa reenvio automático.

O conector MT5 é inicializado de forma persistente, com timeout de 5 segundos e retentativa limitada após desconexão. Chamadas ao conector e operações que alteram posições são serializadas dentro do processo. O desktop também usa um bloqueio de instância única por usuário. Antes de enviar uma ordem, o gateway confere novamente o fingerprint `login@servidor` aprovado, modo DEMO ou REAL confirmado, conexão, permissão de negociação e posições/ordens pendentes. Esses controles não impedem uma ação feita manualmente no terminal ou por outro programa externo.

O backend aceita corpos HTTP de até 3 MB. A pesquisa aceita até 12 feeds e aplica um orçamento global de 35 segundos, usando conexão HTTPS direta para preservar a verificação do endereço do servidor; redes que exigem proxy explícito podem não conseguir coletar fontes nesta versão.

Tetos codificados: 0,01 lote, uma tentativa por sessão para ORB/gap e por candle D1 fechado nas regras diárias, nenhuma posição preexistente por conta e perda diária de 0,1–1% (limite escolhido no perfil). Risco por ordem é limitado a 0,25% e o lote é calculado com `order_calc_profit`; estimativa não inclui comissão, swap, slippage, gaps ou falha de stop. Ao parar o motor, posições abertas permanecem no MT5 e dependem de SL/TP aceitos pelo servidor ou ação posterior do usuário. Ao reiniciar o app, o motor permanece parado.

Descrições livres e arquivos `.py`/`.mq5`/`.txt` não têm contrato executável e nunca são interpretados pelo motor. Só regras declarativas explicitamente suportadas podem ser configuradas; código importado exige tradução e homologação manual. A conta CONTEST não pode iniciar motores de ordem. A conta REAL possui caminhos de envio com confirmações e controles próprios, mas não está homologada para operação real.

O analista de mercado é um caminho adicional e não depende de uma estratégia cadastrada. Seu resultado é contextual/candidato; o veredito final fica em `AGUARDAR` enquanto não houver dados fundamentais estruturados, regra de entrada/saída validada e replay com custos. Não há conexão entre candidato do analista e envio de ordens.

## Extensão futura

Antes de tratar outra regra ou a operação REAL como homologada: definir contrato declarativo, replicação/backtest reproduzível, especificação por broker/símbolo, validação de custos e testes forward demo, reconciliação e recuperação de falhas, limites de risco aprovados, telemetria e revisão operacional independente. O caminho REAL já existe no código e exige confirmação explícita; essa capacidade não substitui esses critérios.
