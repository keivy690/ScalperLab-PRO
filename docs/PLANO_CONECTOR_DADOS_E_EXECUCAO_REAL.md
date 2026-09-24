# Plano de ação — conector MT5 e dados para decisão

## Estado e objetivo

O conector atual consulta o terminal MT5 local e entrega ao motor: identificação básica da conta, saldo/equity, especificação do ativo, ticks, candles fechados, posições abertas e resultado de pedidos enviados. O MT5 Python não constitui, sozinho, uma fonte completa de calendário econômico, notícias ou fundamentos empresariais. Essas camadas requerem provedores separados e integração com proveniência, timestamps, cobertura e estado de indisponibilidade.

O objetivo é oferecer uma visão coerente e auditável por símbolo, sem converter campo ausente em valor fictício, e usar somente dados frescos e compatíveis com a estratégia. Toda decisão deve apontar quais dados sustentaram a decisão e quais estavam ausentes.

O plano de seleção/impacto de fornecedores, com etapas de contratação e integração de calendário, notícias e fundamentos, está detalhado em [PLANO_PROVEDORES_FUNDAMENTAIS.md](PLANO_PROVEDORES_FUNDAMENTAIS.md).

## Plano de implementação por etapas

### 1. Contrato de dados e integridade temporal

- Criar envelope comum para cada consulta: provedor, símbolo/conta, horário UTC da observação, horário de recepção, idade, unidade, cobertura, estado (`disponível`, `parcial`, `atrasado`, `indisponível`) e erro recuperável.
- Padronizar timestamps para UTC internamente; converter para sessão/fuso apenas na regra que necessitar.
- Detectar candles faltantes/duplicados, períodos de mercado fechado, histórico insuficiente e desalinhamento entre tick e candle.
- Registrar a origem e a versão do contrato/metadados em cada ciclo de decisão. Nunca substituir falha por preço, retorno ou notícia inventados.

### 2. Camada de conta, risco e negociação MT5

- Completar fotografia da conta: modo, login, servidor, corretora, moeda, saldo, equity, lucro, margem usada/livre/nível, alavancagem, permissões de negociação e limites do servidor.
- Atualizar ticks e barras por ativo/timeframe com idade máxima configurável, spread observado, tick volume e volume real quando o broker fornecer.
- Obter metadados de contrato por símbolo: tamanho de contrato, tamanho/valor de tick, moedas de lucro/margem, volume mínimo/máximo/passo, stops/freeze, sessões, modo de negociação e preenchimento.
- Consultar posições e ordens pendentes antes e depois de qualquer ação; conciliar ordens, negócios/deals e posições pelo ticket, magic, comentário e intervalo temporal.
- Antes de enviar: conferir lado permitido, preço e frescor, spread, stop/alvo, risco monetário por `order_calc_profit`, margem por `order_calc_margin`, saldo de margem livre, `order_check`, identidade da conta e ausência de exposição incompatível. Reconsultar o estado imediatamente antes do envio.
- Depois do envio: reconciliar aceitação, execução parcial, preço/volume, SL/TP no servidor e posição resultante. Em timeout/resultado incerto, parar e consultar histórico; nunca reenviar às cegas.
- Importar histórico completo em paginação temporal, com limites e checkpoint: ordens, deals, posições resultantes, comissões, swaps e taxas quando expostos pelo terminal.

### 3. Dados técnicos e quantitativos

- Manter indicadores calculados a partir de barras fechadas, com janela, fórmula e versão registrados.
- Adicionar medidas de qualidade dos dados, volatilidade, custos, slippage observado, exposição consolidada e risco por símbolo/moeda.
- Fazer replay reproduzível por snapshot dos dados usados; separar estatística descritiva de probabilidade ou evidência de vantagem.
- FX OTC usa tick volume como contagem de atualizações do broker, não volume centralizado. Identificar limites de cada classe de ativo.

### 4. Calendário, notícias e camada fundamental

- Integrar um ou mais provedores licenciados/permitidos que atendam cada classe de ativo. Calendário e notícias devem trazer origem, publicação, atualização, impacto, países/moedas/ativos relacionados, evento e URL de evidência.
- Para FX: decisões e expectativas de juros, inflação, emprego, atividade e eventos de bancos centrais; para ações/índices/commodities, selecionar dados específicos do instrumento e evitar aplicar métricas incompatíveis.
- Normalizar timezone, duplicatas, revisões, embargo, atraso e eventos cancelados. Não derivar orientação fundamental de manchete sem evidência rastreável.
- Exibir explicitamente cobertura parcial ou ausente. Política inicial: evento de alto impacto próximo, provedor atrasado ou fonte sem cobertura do ativo = decisão `AGUARDAR`, salvo política operacional conscientemente configurada e auditada.
- Guardar licenças, limites de uso, quotas, retenção e tratamento de indisponibilidade de cada provedor antes de produção.

### 5. Orquestração do analista

- Cada ciclo monta um snapshot imutável dos dados técnicos, quantitativos, fundamentais, de conta, contrato e custos.
- Regras versionadas retornam `comprar`, `vender` ou `aguardar`, com condições verificáveis, nível de confiança somente se calibrado, horizonte, invalidação e evidências.
- A aprovação de fonte ou estratégia não executa código importado; execução ocorre apenas por regra declarativa homologada.
- Guardar ciclo, snapshot, decisão, parâmetros, confirmação do operador, pedido, resposta MT5 e reconciliação em trilha de auditoria.

### 6. Resiliência, segurança e observabilidade

- Um único motor de ordens pode estar armado por vez, preso ao modo, login e servidor vistos na confirmação. Troca de conta, terminal ou permissão desarma e para o ciclo.
- Limites atuais do produto permanecem: lote máximo 0,01, uma posição por conta, limites percentuais configurados, stop/alvo exigidos e ausência de reenvio cego. O risco calculado é estimativa e não limita gaps, slippage, comissão ou falha de execução.
- Ações REAL exigem confirmação textual específica no início do motor, confirmação específica ao fechar posição e frase diferente para fechamento emergencial total. CONTEST não executa.
- Após reiniciar o aplicativo, execução permanece parada; posições existentes continuam no MT5. Parada do motor não fecha posição; emergência é uma ação distinta.
- Alertar e registrar desconexão, atraso de dados, margem insuficiente, rejeição, execução parcial, exposição inesperada e divergência entre pedido e posição.

### 7. Testes de aceitação antes de ampliar uso

- Conta DEMO: conectar/desconectar, alternar login/servidor, negociação desabilitada, símbolo inválido/fechado, preços stale, candles ausentes, spread fora do limite, volume mínimo acima do risco, margem insuficiente, stop inválido, execução parcial, rejeição, timeout ambíguo e reconciliação de ordem/deal/posição.
- REAL: confirmar que modo DEMO/CONTEST é recusado; confirmar que frase errada, mudança de conta, stop ausente, risco acima do limite, posição/ordem pendente prévia e terminal sem permissão impedem envio; nenhuma validação de código substitui homologação controlada.
- Dados fundamentais: provedor indisponível, evento revisado/cancelado, notícias duplicadas, ativo não coberto e janela de alto impacto.
- Ensaiar fechamento individual e parada de emergência em DEMO; provar que não se fecham posições quando a conta/servidor divergir ou a lista não puder ser reconciliada.
- Medir latência, taxa de dados atrasados, divergências, falhas de reconciliação e recuperação após reinício. Não alegar prontidão por compilação ou teste isolado.

### Implementação local da trilha de auditoria (2026-09-24)

- `ConnectorV1` oferece consultas por intervalo de histórico (até 31 dias), por ticket de ordem e por ticket de posição. `history_orders_get(ticket=...)` recupera cada ordem indicada pela resposta; `history_deals_get(position=...)` recupera os negócios de entrada e saída ligados à posição. O adapter normaliza os registros para objetos serializáveis e preserva volume, preço, estado, comissão, swap, taxas e lucro.
- `AuditedTradingPort` grava a tentativa no SQLite antes de enviar o RPC, com `correlation_id`, `terminal_id`, parâmetros operacionais e fingerprint da conta armazenado apenas como hash. O ID gera um marcador curto no comentário da ordem para permitir busca no histórico após perda da resposta.
- Resposta, tickets, volume/preço disponíveis e snapshot de ordens, negócios e posições ficam na trilha local. Estado desconhecido, parcial, pré-envio interrompido e evidência ainda incompleta podem ser reconsultados por `POST /api/trading/audit/reconcile`; `GET /api/trading/audit` lista os registros.
- A reconciliação é somente leitura. Sem marcador/ticket correlacionável ou se o histórico estiver indisponível, o registro permanece pendente; a aplicação não repete a ordem. Se o broker remover o comentário e a resposta tiver sido perdida, pode ser necessária revisão manual.
- No teste DEMO da instalação XM em 2026-09-24, o MT5 rejeitou `order_check` para comentário de fechamento com 30 e 31 caracteres. O conector passou a limitar o comentário a 29. A compra mínima de `EURUSD#` foi aberta uma vez; após a rejeição pré-envio do fechamento, a posição identificada foi fechada por uma ação individual auditada com retcode 10009. A busca por intervalo UTC não retornou linhas, pois os timestamps do histórico deste terminal ficaram cerca de três horas à frente do horário UTC registrado pela aplicação. A busca por ticket recuperou as duas ordens e, pelo `position_id`, os dois negócios; a auditoria foi atualizada para `reconciled`, com compra e fechamento de 0,01 e preço médio de saída 1,13716. Não houve nova ordem; posições e ordens pendentes ficaram vazias, e estratégia e Analista permaneceram parados.
- As consultas oficiais permitem filtrar ordens pelo ticket e negócios pela posição. A API retorna `None` em caso de erro; a implementação preserva a diferença entre falha de consulta e resultado vazio. Referências: [history_orders_get](https://www.mql5.com/en/docs/python_metatrader5/mt5historyordersget_py) e [history_deals_get](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py).

## Escopo já ativado no código nesta mudança

- Removido o bloqueio absoluto de conta REAL no início dos dois motores e na rota de API.
- Execução REAL passou a exigir conta REAL, confirmação textual específica, terminal autorizado, login/servidor constante, sinal válido, limite de 0,01 lote, limite de risco configurado, SL/TP, margem, pré-checagem MT5, nenhuma posição/ordem pendente anterior e reconciliação posterior.
- A operação continua sem reenvio automático quando o resultado é incerto. Armar um motor REAL não equivale a validar a estratégia nem o sistema para produção.
- Fechamento individual REAL exige armamento por sessão e confirmação por posição. Emergência REAL exige frase separada e tenta reconciliar todas as posições.
- Atualização de estado: a ponte local do calendário econômico MQL5 está implementada e pode fornecer contexto parcial quando o Service publica snapshot recente. Notícias e séries macroeconômicas externas continuam pendentes; a regra do Analista não equivale a uma análise fundamental completa.

## Condição para declarar o conector completo

Concluir etapas 1–7, manter as fontes/licenças documentadas, validar em DEMO com logs de auditoria, revisar limites por corretora e ativo e executar homologação supervisionada. A autorização do operador remove o bloqueio absoluto de código, mas não transforma automaticamente a conta/estratégia em validada nem limita a perda real.
