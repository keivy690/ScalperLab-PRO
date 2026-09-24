# Plano completo — provedores de calendário, notícias e fundamentos

**Status:** atualizado com calendário nativo do MT5 e ponte MQL5 somente de leitura. A conexão só será considerada operacional depois de iniciar o Service e observar um snapshot fresco associado à conta atual.

## 1. Decisão recomendada

O ScalperLab deve adotar uma composição de fontes por tipo de dado, em vez de depender de um único feed ou inferir fundamentos de notícias não estruturadas:

| Camada | Provedor recomendado | Uso no ScalperLab | Limite/decisão |
|---|---|---|---|
| Calendário macro global (primeira fonte) | Calendário econômico embutido no MT5, via MQL5 Service local | Agenda, país/moeda, evento, importância, horário do servidor MT5 e valores anteriores/consenso/realizado quando fornecidos | Cobertura e atualização dependem do calendário disponível no terminal. Horários usam o fuso do servidor da corretora. A ponte local é somente leitura; não transforma evento em viés direcional. |
| Calendário macro global (expansão/fallback) | Trading Economics API | Cobertura adicional, consenso e histórico quando necessários | Integrar se a cobertura/cadência do MT5 for insuficiente; confirmar cotação, campos, licença e distribuição antes de contratação. |
| Notícias de FX e mercado | Financial Modeling Prep (FMP), endpoint Forex News | Manchetes, URLs, ativos/códigos e contexto noticioso por símbolo | A documentação informa cadência de atualização de 5 minutos para Forex News. Adequado como contexto para ciclos M15, não como feed de notícia de baixa latência. Confirmar plano, direito de exibição/armazenamento e cobertura antes da contratação. |
| Macro EUA | Federal Reserve/FRED + ALFRED | Taxas e séries macro de EUA com observações, metadados e vintages/revisões | Oficial e rastreável, mas várias séries são diárias/mensais/trimestrais; não são sinal intradiário. Exige chave individual FRED. |
| Macro da zona do euro | ECB Data Portal (SDMX REST) | Séries oficiais de taxas, câmbio e outros indicadores publicados pelo BCE | Consultas programáticas com metadados; usar horário/período, unidade e eventuais revisões corretamente. |
| Calendário de decisões monetárias | Calendários oficiais Fed/FOMC e BCE | Confirmar datas/decisões, validar eventos do agregador e manter links oficiais | Tratar páginas oficiais como verificação e evidência. Para ingestão automatizada recorrente, começar pelo calendário estruturado do provedor comercial, pois as páginas institucionais não oferecem o mesmo contrato de API do feed agregado. |
| Ouro (XAUUSD) | Primeiro: macro EUA, notícias Forex/metais e CFTC COT; depois avaliar World Gold Council/LBMA | Contexto de dólar, juros reais e posicionamento em futuros; futuramente oferta/demanda, reservas/fluxos | COT é semanal e de futuros, não equivale a posição em ouro spot/CFD do broker. Dados detalhados de mercado de ouro podem exigir licença própria. |
| Ações, se adicionadas | SEC EDGAR (EUA), dados abertos/documentos CVM (Brasil) | Demonstrações, filings, comunicados e fatos de empresas | Aplicar somente a ações/empresas mapeadas. São fontes por jurisdição, com esquemas e calendários de publicação diferentes. |
| Energia, se adicionada | EIA Open Data | Indicadores de petróleo, gás e energia | Específico de energia; não é substituto de dados de ouro nem de macro geral. |

### Escolha para o MVP

1. **Calendário MT5 via Service MQL5 para o piloto inicial**, condicionado à validação do feed no terminal XM aberto. Trading Economics fica como fallback/expansão caso cobertura, consenso ou histórico sejam insuficientes.
2. **FMP Forex News para notícias**, condicionado à confirmação expressa do plano para nosso uso e seus direitos de exibição/armazenamento. Sua cadência documentada é de 5 minutos.
3. **FRED/ALFRED para EUA e ECB SDMX para euro**, como camada de séries oficiais de contexto, sem tratá-las como feed de consenso nem como dado de tick.
4. **CFTC COT para XAUUSD somente como indicador semanal complementar**. Não anunciar análise completa de oferta/demanda de ouro até contratar ou integrar fonte especializada e documentar cobertura/licença.
5. **SEC/CVM/EIA ficam fora do MVP FX + XAUUSD**; entram somente ao adicionar, respectivamente, ações dos EUA/Brasil ou energia.

As páginas públicas de provedores não provam, sozinhas, que um plano específico autoriza redistribuir ou exibir dados no aplicativo. Acesso pessoal/desenvolvimento e distribuição comercial são direitos distintos. A contratação e a licença devem ser confirmadas antes da distribuição do ScalperLab a terceiros.

### Descoberta no terminal aberto (23/09/2026)

- A API Python instalada (`MetaTrader5` 5.0.6180) não expõe funções calendar/news/economic. O MT5 XM Global build 6182 estava conectado a uma conta DEMO USD durante a consulta; nenhum pedido de negociação foi enviado.
- O calendário pode ser consultado por MQL5 com `CalendarValueHistory`, `CalendarEventById` e `CalendarCountryById`, usando `MqlCalendarValue`, `MqlCalendarEvent` e `MqlCalendarCountry`.
- As notas oficiais do build 2005 descrevem MQL5 Services, que não dependem de gráficos e podem iniciar junto com o terminal. A ponte está em `mt5/ScalperLabCalendarService.mq5`; ainda requer compilação, inclusão/inicialização no terminal e confirmação de snapshot atual.
- O serviço preserva horário de evento no fuso de negociação do MT5. A aplicação não o rotula como UTC e não converte surpresa macro em recomendação direcional.
- A plataforma tem feed de notícias na interface, mas a referência MQL5 consultada não documenta API de leitura para esse feed. Notícias continuam dependendo de provedor externo ou API específica do broker.
- Calendário nativo não substitui notícias, séries macro com vintages, fundamentos empresariais, dados COT ou oferta/demanda de commodities. A análise continua `PARCIAL`.

## 2. O que “completa” significa por classe de ativo

- **FX:** diferencial e trajetória de juros, inflação, emprego, crescimento/atividade, decisões e comunicações de bancos centrais, risco geopolítico/notícias e calendário para ambas as moedas. Não há demonstração financeira de “EURUSD” como se fosse uma empresa.
- **XAUUSD:** contexto de dólar e juros reais, inflação/expectativas, bancos centrais, fluxos/posicionamento e oferta/demanda de ouro. O MT5 pode mostrar um CFD/spot do broker; isso não é o mesmo instrumento que o futuro de ouro acompanhado no COT.
- **Índice:** calendário macro relacionado às economias e setores/empresas componentes, além de notícias e eventos corporativos relevantes. O mapeamento precisa respeitar composição e pesos do índice.
- **Ação:** demonstrações financeiras, filings, guidance, eventos de resultados, proventos, governança e eventos materiais do emissor, identificados por CNPJ/CIK e ticker correto.
- **Commodities não energéticas/energia:** séries de estoque, produção, consumo, exportação/importação, posicionamento e eventos específicos da mercadoria; fonte e frequência próprias.

Não se deve rotular um instrumento como “fundamental completo” se a fonte não cobre sua classe ou se faltam dimensões críticas. O estado precisa ser `completo_para_perfil`, `parcial`, `atrasado` ou `indisponível`, acompanhado da lista de lacunas.

## 3. Impactos esperados

| Área | Efeito positivo | Custo ou risco introduzido | Controle planejado |
|---|---|---|---|
| Qualidade contextual | Eventos e publicações relacionados ao instrumento deixam de depender de pesquisa manual | Feeds podem atrasar, revisar valores, errar associação ticker/moeda ou ficar indisponíveis | Origem, idade, confiança de associação, versão e status visíveis; reconciliação com fonte oficial |
| Decisões do motor | Pode evitar entradas perto de eventos e distinguir contexto macro de gatilho técnico | Blackouts reduzem frequência de operações; notícia pode ser ambígua e consenso pode divergir entre provedores | Regra versionada por classe/timeframe; primeiro observação/replay; IA não envia ordens nem decide sozinha |
| Operação M15 | Calendário e contexto macro ajudam a interpretar riscos que candles não mostram | FMP declara atualização de notícias Forex a cada 5 min; não é adequado a execução sensível a milissegundos ou a “breaking news” imediata | MT5 permanece fonte de execução/preço; notícias servem como contexto e bloqueio, não para timing de tick |
| Resultado do backtest | Dados históricos com “as-of” podem permitir replay sem usar informação futura | Revisões posteriores e datas de divulgação mal normalizadas causam look-ahead e resultados falsos | Guardar horário de publicação, horário de coleta, vintage/revisão e valor conhecido na data do replay |
| Infraestrutura | Cache local reduz chamadas repetidas e torna análise auditável | Mais APIs, chaves, quota, dependência de rede, erros 429/5xx e manutenção de esquemas | Adaptadores independentes, limites/rate limiter, cache, retry só para leitura, circuit breaker, estado stale explícito |
| Custo/licença | Dados consistentes e suporte de fornecedor podem acelerar o desenvolvimento | Assinaturas, limites de uso, retenção e exibição/redistribuição variam; custo atual não deve ser presumido | Levantar cotações por endpoint/usuário/distribuição; aprovar licença antes de habilitar display fora do ambiente pessoal |
| Interface | Analista pode mostrar agenda próxima, fonte e nível de cobertura | Mais informação pode poluir a tela e parecer uma recomendação | Resumo compacto; drill-down por evidência, impacto e horário UTC/local |
| Segurança | Segredos ficam fora do banco e da interface | Chaves em query strings podem aparecer em logs/proxy; terceiros recebem consultas de símbolos | Preferir cabeçalho de autenticação quando disponível, redigir logs, armazenar via Credential Manager/DPAPI ou variável protegida |

Impacto comportamental esperado: a análise fundamental opera principalmente como **contexto de horizonte maior e filtro de risco de evento**. Não se deve prometer que ela aumenta acerto ou lucro. Ao ativar um filtro de alto impacto, o sistema poderá aguardar mais vezes e reduzir entradas em determinadas janelas.

## 4. Contrato de dados que todos os adaptadores devem cumprir

Cada observação/evento normalizado deve conter, no mínimo:

- `provider`, `provider_record_id`, `source_url`, `license_profile`;
- `asset_class`, `instrument`, `related_currencies`, `country`, `issuer_id` quando aplicável;
- `event_type`/`series_id`, `title`, `value`, `unit`, `period`, `frequency`;
- `scheduled_at_utc`, `published_at_utc`, `received_at_utc`, `updated_at_utc`;
- `previous`, `consensus`, `actual`, `revision`, `vintage` quando o provedor oferecer esses campos;
- `importance` e definição/escala do próprio provedor, sem converter escalas incompatíveis como se fossem iguais;
- `freshness_seconds`, `coverage_status`, `mapping_confidence`, `quality_flags`;
- hash/versão do payload bruto e versão do normalizador para reproduzir a análise.

Preservar valor bruto do provedor e valor normalizado em campos separados. Nenhum valor ausente vira zero. Consenso ausente permanece ausente. Datas são armazenadas em UTC; a interface converte para o fuso escolhido e mostra claramente qual é.

## 5. Plano de ação por etapas

### Fase 0 — escolha comercial e aceite das fontes

1. Confirmar ativos alvo do primeiro piloto (proposta: EURUSD e XAUUSD, sem transformar isso em compromisso de cobertura para todos os símbolos MT5).
2. Solicitar a Trading Economics uma proposta que discrimine calendário: países/moedas, histórico, consenso/realizado, atualizações em tempo real, limites, atraso, armazenamento local e distribuição dentro de aplicação desktop.
3. Confirmar com FMP se o plano pretendido libera Forex News para uso no ScalperLab, exibição na interface, cache/histórico local e eventual distribuição. A página pública de preços lista recursos por plano; isso não substitui confirmação do endpoint e licença.
4. Criar chaves separadas para desenvolvimento e implantação; registrar validade/rotação e procedimento de revogação.
5. Definir política por tipo de falha: nunca emitir viés quando provedor estiver stale. Antes de ativar filtro de ordens, usar `AGUARDAR` em caso de calendário de alta relevância sem resposta, sujeito à política de cobertura aprovada.

**Saída/aceite:** quadro de provedor, endpoints e campos realmente autorizados, custos/cotas, retenção, licença e latência medida. Sem essa saída, não codificar dependência comercial no motor.

### Fase 1 — contrato, cadastro de instrumentos e armazenamento

1. Criar cadastro `symbol -> asset_class -> underlying -> currencies/country -> provider identifiers`; suportar sufixos/prefixos de broker via perfil explícito, não heurística cega.
2. Versionar o envelope canônico da seção 4 e migração local de banco para payload bruto, observação normalizada, cursor de coleta e health por provedor.
3. Guardar timestamps de evento versus publicação versus recebimento; armazenar alterações/revisões de calendário em vez de sobrescrever silenciosamente.
4. Cobrir segredos com proteção local do Windows e excluir chaves de logs, backup não criptografado e respostas de erro.

**Saída/aceite:** replay de fixture gravada reconstitui a mesma observação normalizada e deixa claro o que o sistema sabia em cada instante.

### Fase 2 — adaptadores de fonte

1. Implementar adaptador de calendário para Trading Economics: janela temporal limitada, moeda/país, prioridade, consensos, paginação, atualização, duplicatas e cancelamento/revisão.
2. Implementar FMP Forex News: consulta por par/moeda quando suportada, cursor/paginação, URL original, origem/editor, horário, categoria/símbolos e deduplicação por id/hash.
3. Implementar FRED/ALFRED para lista allowlist de séries EUA selecionadas: Fed funds, inflação e yields relevantes, com frequency/units/realtime vintage. Não fazer busca arbitrária de todas as séries no ciclo de trade.
4. Implementar ECB SDMX para séries equivalentes da zona do euro, com dataflow e codelists explícitos.
5. Adicionar adaptadores SEC/CVM/EIA ou fornecedor de ouro somente quando classes correspondentes entrarem no escopo e a licença for registrada.
6. Adicionar cache e frequência por endpoint. Séries mensais/diárias não precisam ser baixadas a cada 30 segundos; agenda de evento e notícias têm intervalo separado.

**Saída/aceite:** contrato uniforme, stale detectado, fonte/URL visível, erro por provedor isolado e ausência de secret nos logs.

### Fase 3 — normalização e associação

1. Mapear EURUSD para EUR e USD; validar mapping para nomes de broker como `EURUSD.a`, `EURUSDm` sem assumir sufixo.
2. Mapear XAUUSD para ouro spot/CFD e moedas de cotação; marcar dados COT como futuro COMEX e semanal, portanto proxy relacionado, nunca a mesma exposição.
3. Converter importância somente com tabela de correspondência documentada. Preservar rótulo original.
4. Normalizar artigos repetidos/sindicados, separar publicação e atualização, associar moeda/empresa com evidência e limiar. Correspondência ambígua não afeta ordem.
5. Comparar eventos críticos do agregador com calendário oficial Fed/ECB e medir diferenças de horário/alteração.

**Saída/aceite:** conjunto revisado manualmente de instrumentos/eventos, sem símbolos confundidos e sem timezone/DST incorreto.

### Fase 4 — interface e observabilidade

1. Na área Analista, exibir calendário próximo (janela configurável), fatos publicados recentes e painel macro por moeda.
2. Mostrar badge de cobertura de cada camada, “atualizado em”, idade da observação, provedor e link de evidência.
3. Diferenciar `sem evento`, `sem cobertura`, `atrasado` e `provedor indisponível`.
4. Criar tela/console de saúde: último sucesso, latência observada, quota quando disponível, erros, número de registros e cursor.
5. Mostrar o resumo da IA separado dos dados determinísticos, com trechos/URLs; nunca representar interpretação como valor oficial do provedor.

**Saída/aceite:** operador identifica se dado é observado, projetado, revisado, atrasado ou indisponível sem ler logs técnicos.

### Fase 5 — construção da camada fundamental

1. Começar com fatos, não sinal: trajetória de juros e diferencial por moeda, inflação/atividade e evento agendado.
2. Construir features versionadas com janela e normalização (ex.: surpresa atual menos consenso somente quando ambos existem; tendência de série com vintage disponível; tempo até evento).
3. Criar contexto de horizonte: evento intradiário; série macro lenta; posicionamento semanal. Não agregar horizontes em uma única nota sem justificativa.
4. Adicionar notícias como evento evidenciado. Classificação por LLM deve guardar modelo, prompt/version, score de incerteza e documento original; baixa confiança, manchete contraditória ou ausência de fonte = neutro/indisponível.
5. Não criar “probabilidade de compra/venda” até calibração fora da amostra. Primeiro mostrar fatores individuais e conflitos entre fontes.

**Saída/aceite:** relatório explica cada fator, timeframe, evidência, data disponível à época e discordâncias; revisão humana consegue refazer o cálculo.

### Fase 6 — integração com decisão e política de risco de evento

1. Separar saídas `DIRECIONAL`, `RISCO_DE_EVENTO`, `COBERTURA` e `TÉCNICA_QUANTITATIVA`.
2. Na primeira versão, evento só informa e pode acionar espera em janelas definidas por política, sem criar entrada sozinho.
3. Calibrar janelas pré/pós-evento por classe e timeframe em replay; não adotar janelas universais sem evidência.
4. Se a fonte necessária estiver stale/indisponível, a regra de execução associada ao filtro fundamental para e apresenta o motivo. Modo sem filtro deve ser nomeado “técnica/quantitativa”; não pode aparecer como análise completa.
5. Registrar o snapshot de todos os provedores usado na decisão junto da versão das regras e evento do MT5.

**Saída/aceite:** mesmas entradas + mesmo snapshot + mesmo pacote de regras reproduzem decisão idêntica, inclusive `AGUARDAR`.

### Fase 7 — replay, DEMO e homologação

1. Criar replay “as-of” sem look-ahead: notícia/evento/série só existe depois do seu `published_at`/disponibilidade real; revisões futuras não aparecem no passado.
2. Comparar regra sem fundamental, regra com bloqueios de eventos e regra com features macro separadamente.
3. Incluir spread, comissão, swap, slippage, gaps, sessão e execução do broker; comparar quantidade de operações, exposição, DD e sensibilidade, não apenas lucro bruto.
4. Operar observação DEMO e comparar sinais com o snapshot que chega no horário real. Armazenar atrasos e falhas.
5. Só após aceite de dados/replay/risco, habilitar DEMO automática para uma lista controlada de símbolos. REAL requer homologação separada e autorização vigente.

**Saída/aceite:** pacote de evidências revisado; não se aprova estratégia por acurácia de sentimento, período retrospectivo escolhido ou resultado bruto isolado.

### Fase 8 — operação, custo e manutenção

1. Dashboard de custo mensal estimado, chamadas/quota, latência p50/p95, disponibilidade, erros e cobertura por ativo.
2. Alertar alteração de schema, falha de feed, licença vencendo, chave exposta, calendário revisado e ausência de dados.
3. Planejar fallback: calendário oficial para reuniões do Fed/ECB e indicadores macro oficiais para contexto, mas não fingir que isso substitui calendário agregado completo.
4. Documentar rotação/revogação de chaves, retenção/exclusão de artigos, backup e recuperação.
5. Revisar custo/licença antes de compartilhar/distribuir builds; validar se a distribuição exige contrato de display ou redistribution.

**Saída/aceite:** operação conhecida e auditável, rota de degradação testada e possibilidade de desligar cada fornecedor sem quebrar candles, leitura da conta ou motor em observação.

## 6. Critérios globais de aceite

- Nenhuma tela ou decisão chama fundamentos de “completos” com cobertura parcial.
- Evento/news sem fonte, horário, símbolo/moeda relacionada ou condição de licença é somente informativo e não influencia execução.
- Dados stale, revisão/cancelamento, 429, 5xx, chave inválida, relógio incorreto, DST e ausência de consenso são estados tratados explicitamente.
- Testes de replay provam que dados publicados depois do sinal não vazam para trás.
- Nenhum segredo é gravado no SQLite, console, relatório ou código-fonte.
- Ordens continuam passando pelas checagens MT5 e limites do motor; provedor fundamental não pode enviar uma ordem diretamente.
- Usuário consegue ver exatamente quais fontes mudaram a decisão e qual regra causou `AGUARDAR`.

## 7. Dependências e decisões ainda necessárias

1. Cotação do Trading Economics e confirmação de cobertura/latência/licença do endpoint de calendário para os símbolos alvo.
2. Confirmação por escrito do plano e direitos FMP para desktop pessoal versus qualquer distribuição futura.
3. Escolher perfil inicial de símbolos: recomendação de piloto `EURUSD` e `XAUUSD`; demais símbolos ficam sem fundamental até existir mapping e feed compatível.
4. Aprovar se indisponibilidade do calendário de alto impacto sempre bloqueia entradas ou apenas bloqueia estratégias que usem especificamente essa camada. Recomendação: fail-closed para estratégias declaradas como fundamentalmente filtradas; não mascarar o modo técnica/quantitativa como completo.
5. Confirmar janela de evento a estudar no replay; não fixar minutos pré/pós-evento antes da análise por evento e timeframe.

## Fontes primárias consultadas

- Trading Economics API: escopo de calendário, dados e preço de assinatura condicionado a recurso/volume/distribuição: https://tradingeconomics.com/analytics/api.aspx
- FMP preços e direitos: planos e observação explícita sobre acordo de licença para exibição/redistribuição: https://site.financialmodelingprep.com/developer/docs/pricing
- FMP ciclo de atualização: Economic Data Releases Calendar e Forex News com cadência publicada pelo fornecedor: https://site.financialmodelingprep.com/developer/docs/cycle-times-stable
- FRED/ALFRED: API, séries e períodos/vintages para revisões: https://fred.stlouisfed.org/docs/api/fred/
- ECB Data Portal: API SDMX REST para dados/metadados: https://data.ecb.europa.eu/help/api/overview
- Calendários oficiais Fed e BCE: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm e https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
- MT5 análise fundamental: https://www.metatrader5.com/pt/trading-platform/fundamental-analysis
- MetaTrader 5 build 2005: https://www.metatrader5.com/pt/releasenotes/terminal/1920
- MQL5 Economic Calendar API: https://www.mql5.com/en/docs/calendar
- MQL5 CalendarValueHistory e fuso do servidor: https://www.mql5.com/en/docs/calendar/calendarvaluehistory
- MQL5 Calendar structures: https://www.mql5.com/en/docs/constants/structures/mqlcalendar
- MQL5 FileMove: https://www.mql5.com/en/docs/files/filemove
- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- CVM DFP de companhias abertas: https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp
- EIA Open Data API: https://www.eia.gov/opendata/documentation.php
