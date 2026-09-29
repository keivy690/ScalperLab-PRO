# Validação de lote, risco, margem e integração MT5

**Atualização de 29/09/2026:** as pendências do Service descritas abaixo refletem a primeira rodada de 28/09. A validação posterior, incluindo 139 testes, prévia, replay, ordem DEMO de 0,02 lote com stop/alvo e retomada dos serviços após reinício do MT5, está registrada em [RELOGIO_INDEPENDENTE.md](RELOGIO_INDEPENDENTE.md). Os resultados desta primeira rodada permanecem como histórico do diagnóstico.

## Resultado desta rodada
Testes executados na conta DEMO XM, com autorização do usuário. Aplicativo executado como administrador. A validação completa permanece pendente do reinício do ScalperLabCalendarService pelo usuário.

### Automatizados e estáticos
- 136 testes aprovados, incluindo replay, relógio, migração, dimensionamento, execução, reconciliação e API.
- Adicionados casos de histórico de saldo revisado/incompleto, perfil alterado antes do envio, bloqueio diário compartilhado e cálculos de lucro/margem indisponíveis ou não finitos.
- Sintaxe JavaScript, compilação Python e git diff --check aprovados.
- Falhas de timeout, resposta incerta e preenchimento parcial são verificadas com simulação; não foram provocadas na conexão real.

### Integração com aplicativo e persistência
| Cenário | Resultado |
|---|---|
| Salvar risco percentual, monetário e lote fixo nos dois perfis | HTTP 200 |
| Alterar reserva de margem | HTTP 200 |
| Reserva negativa, 100% ou NaN | HTTP 400 |
| Gravação sem autenticação | HTTP 403 |
| Iniciar observação | HTTP 200 |
| Salvar risco com Analista em observação | HTTP 409 |
| Parar observação | HTTP 200 |
| Solicitar REAL com confirmação inválida | HTTP 409; sem envio |
| Perfis preservados após reinício | Confirmado |
| Replay sem confirmação de custos | HTTP 400 |

Os perfis originais foram restaurados. Analista: risco 0,3%, máximo 0,02 lote; Estratégias: risco 0,25%, máximo 0,01 lote; reserva 20%; limite diário 2%. A versão aumentou devido aos salvamentos de teste. Os motores foram deixados parados.

### Ordem DEMO real pelo fluxo de teste do aplicativo
- Símbolo: EURUSD#; compra de 0,01 lote.
- Ordem de abertura: 1002729399; negócio: 989336841; retcode 10009.
- Preço de abertura: 1,13779.
- Ordem de fechamento: 1002729402; negócio: 989336844; retcode 10009.
- Preço de fechamento: 1,13766; volume restante: zero.
- Posições abertas e ordens pendentes após conferência: zero.
- Variação observada de saldo: USD -0,13 (9437,97 para 9437,84).

Esse teste dedicado de conectividade abre e fecha imediatamente o lote mínimo e não representa um sinal do Analista. Ele não comprova o fluxo de análise automática, aplicação de stops ou envio de 0,02 lote pelos motores. Essas etapas continuam pendentes da validação do relógio MQL5.

### Dimensionamento com cálculos reais do MT5, sem envio
Para EURUSD#, com stop a 0,001 do preço de entrada:
- 0,01 lote: perda estimada USD 1,00; margem aproximada USD 1,14.
- 0,02 lote: perda estimada USD 2,00; margem aproximada USD 2,28.
- Orçamento USD 3,00: lote calculado 0,03.
- Orçamento de 0,1% do patrimônio: lote calculado 0,09, arredondado para baixo.
- Lote 0,015: recusado por incompatibilidade com passo 0,01.
- Reserva 99,99% e lote 0,02: recusado por margem insuficiente para preservar a reserva.
- Orçamento abaixo da perda do lote mínimo: recusado, sem aumentar o lote.

Esses testes chamaram o dimensionador com o SDK real; não equivalem à aprovação da prévia completa, que também verifica o relógio.

## Pendências e problema identificado
O Windows passou na validação, sem erro de permissão. O snapshot do Service MQL5 permaneceu com captura de 27/09/2026 01:11:19 UTC, mais de 40 horas atrás nesta rodada. A prévia completa e os replays EURUSD# M15 e BTCUSD# M5 foram corretamente recusados por dados de relógio desatualizados. Não foi removido esse controle nem fabricado snapshot.

Os replays tentados usaram custos hipotéticos apenas para teste funcional; nenhum resultado de rentabilidade foi gerado ou validado. O replay existente ainda não reproduz automaticamente os novos perfis de risco.

Após o Service publicar novamente: repetir prévia, replay com histórico do broker, envio controlado de 0,02 lote com stop/alvo, confirmação no servidor, fechamento e reconciliação; depois restaurar os perfis. Uma aprovação desta rodada não deve ser anunciada como homologação completa.

## Evidências locais
- backups/qa-live-risk-results.json
- backups/qa-live-sizing.json
- backups/qa-demo-smoke.json
- backups/qa-live-controls.json (a primeira tentativa de observação usou modo inválido; corrigida na evidência seguinte)
- backups/qa-live-active-lock.json
- backups/qa-replay-EURUSD.json
- backups/qa-replay-BTCUSD.json
- backups/risk-before-live-qa.json
