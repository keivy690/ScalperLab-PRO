# Estado atual do ScalperLab PRO

**Referência:** código da branch `feature/sr-quant-engine` em 29/09/2026. Este documento separa capacidade implementada, evidência observada no terminal de desenvolvimento e trabalho pendente. O executável piloto anteriormente gerado pode representar outra revisão; consulte seu `BUILD-MANIFEST.json` antes de atribuir-lhe uma função desta branch.

## Mapa de capacidades

| Área | Implementado nesta branch | Evidência e limite atual |
| --- | --- | --- |
| Desktop e conector | pywebview e backend local; conector Python MT5 em worker isolado; identidade de conta/terminal, catálogo e Market Watch, ticks, candles, posições, ordens, metadados e pré-verificações | Leitura local DEMO foi observada em 29/09; sessão, broker e disponibilidade devem ser conferidos a cada instalação |
| Relógio | ClockService MQL5 independente, Windows Time/NTP, validação de conta e offset atual, renovação automática e bloqueio de novas entradas quando a prova perde validade | Offset **atual** não define o calendário histórico de mudança sazonal do broker |
| Calendário | CalendarService MQL5 publica eventos recentes vinculados à conta/servidor | Contexto parcial e informativo no modo técnico/quantitativo; não é feed de notícias nem viés fundamental completo |
| Analista | Heurística SMA21 com leitura técnica/quantitativa, observação, execução condicionada DEMO/REAL e replay OHLC próprio | Regra experimental; replay ainda não equivale a ticks reais ou validação estatística; REAL não homologado |
| Estratégias | Cinco adaptadores declarativos; revisão/aprovação; observação e envio condicionado | Arquivos importados são revisados, nunca executados automaticamente; estudos originais não validam a adaptação |
| S/R Quant | Pesquisa H1/M15/M5 opcional de pullback em tendência, breakout com reteste e falso rompimento lateral; avaliações persistidas; replay 70/30 e reprodução offline; coleta bruta e arquivo progressivo de horário adicionados em 30/09 | Sempre `research_only`, `order_eligible=false`; sem envio. Na leitura XMGlobal de 29/09, H1 e a base histórica UTC não foram confirmados. A coleta/arquivo novos ainda não foram verificados contra um terminal aberto nesta revisão; não liberam replay real |
| Lote, risco e ordens | Perfis persistidos por motor, três modos de dimensionamento, margem reservada, limite diário por conta/dia UTC, `order_check`, auditoria e reconciliação | Estimativas não capturam todos os custos/gaps. Status de modo armado não confirma ordem; confirmação requer posição correlacionada no MT5 |
| Pesquisa de fontes | GitHub, RSS/Atom, importação de URL; Brave/YouTube/IA opcionais por chave | Conteúdo público exige revisão humana. Notícias e séries macro estruturadas não alimentam as decisões atuais |
| Pacote | Script PyInstaller `onedir` e instalação assistida de ClockService/CalendarService | O piloto datado anteriormente não foi reconstruído nem aceito nesta revisão; não afirmar que contém S/R Quant sem novo manifesto/build |

## Fluxo de uma decisão que pode enviar ordem

1. O operador abre o MT5, confere conta/servidor, salva perfil e arma **um** motor após confirmação explícita. Todos começam parados após reinício.
2. O motor de ordem lê dados reais pelo `TradingPort`, usa candles fechados e avalia a regra implementada. `AGUARDAR` ou falta de dado não vira ordem.
3. O backend confirma conta/mode, horário, cotação fresca, contrato do símbolo, posições/ordens pendentes, limite diário, lote, margem, SL/TP e `order_check`.
4. Havendo sinal elegível e preflight aceito, o gateway envia a intenção ao MT5. A auditoria associa a tentativa à resposta e busca posição/histórico. Timeout ou resultado ambíguo suspende sem reenvio automático.
5. O painel diferencia **observando**, **modo DEMO/REAL armado**, **ordem solicitada**, **posição confirmada** e **execução bloqueada**. Parar o motor não fecha posições existentes.

O S/R Quant participa apenas de pesquisa e replay. Não entra no passo 3 nem no gateway de ordens.

## Pendências com efeito prático

1. **Histórico temporal do broker:** a [coleta e o arquivo progressivo](VALIDACAO_TEMPO_HISTORICO_SR.md) já estão implementados; ainda falta obter e validar a regra histórica do servidor e confrontar H1/M15/M5 e ticks nas transições. O ClockService publica apenas o offset corrente. Até lá, manter falha fechada do S/R Quant.
2. **Evidência estatística:** executar replay S/R com histórico do broker confiável, custos base/adversos e janela reservada; comparar com baseline e, depois, ticks reais ou Strategy Tester. A implementação em código e testes sintéticos não demonstram rentabilidade.
3. **Dados fundamentais:** contratar/ligar provedores de notícias e séries macro adequados à classe de ativo, com licença, proveniência, timestamp, cobertura, revisão e estado de indisponibilidade. Calendário sozinho é parcial.
4. **Pacote atualizado:** reconstruir o `onedir` a partir da revisão aprovada e validar o manifesto, os dois Services, o conector e persistência em outra instalação Windows. Não confundir código atualizado com executável já distribuível.
5. **REAL:** capacidade técnica existe sob confirmações, mas falta homologação independente de estratégia, falhas de execução, custos e operação. Nenhuma conclusão de prontidão decorre de um botão habilitado.

## Fonte de verdade e documentos históricos

- [Manual](MANUAL_INSTALACAO_E_USO.md): ações do operador.
- [Arquitetura](ARCHITECTURE.md): contratos e caminho de dados.
- [Segurança e limites](SAFETY_AND_LIMITS.md): condições de bloqueio e envio.
- [Implementação S/R Quant](IMPLEMENTACAO_SR_QUANT_2026-09-29.md): o que foi observado na entrega.
- [Validação do tempo histórico S/R](VALIDACAO_TEMPO_HISTORICO_SR.md): coleta bruta, arquivo progressivo e critérios para uma futura conversão versionada.
- Planos, estudos e relatórios com data conservam o estado daquela data. Um item marcado “proposta” ou “pendente” não vira recurso apenas por constar de um plano.
