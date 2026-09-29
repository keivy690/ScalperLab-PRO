# Relógio independente do calendário

## Causa adicional identificada na validação
Os publicadores anteriores não declaravam `#property service`: apesar do nome e da pasta, eram compilados como scripts vinculados a gráficos. Os logs reais mostravam símbolo/timeframe ao lado do nome. A declaração foi adicionada aos dois arquivos, com registro de `PROGRAM_SERVICE` no início e verificação obrigatória no build. Compilar sem erros, isoladamente, não comprovava que o tipo do programa estava correto.

ScalperLabClockService 2.00 publica a cada 10 segundos em MQL5/Files/ScalperLab_clock_v2.json, dentro da pasta do terminal. Não consulta calendário, não envia ordens e impede duas instâncias publicadoras no mesmo terminal por bloqueio exclusivo de arquivo.

O leitor confere conta, servidor, pasta do terminal, versão, conexão e coerência dos horários. Publicações com mais de 45 segundos deixam de ser aceitas. Após instalação do novo serviço, uma falha não autoriza retorno ao arquivo legado do calendário. A publicação usa arquivo temporário e substituição; uma falha de leitura é tratada como indisponibilidade recuperável.

O serviço é incluído no pacote e no instalador de componentes MT5. Primeira ativação: Navegador → Serviços → atualizar → iniciar ScalperLabClockService. O MT5 documenta a inicialização de serviços previamente iniciados ao abrir o terminal; essa retomada precisa ser conferida na instalação do usuário. O aplicativo não reinicia o terminal nem rearma motores automaticamente.

Configurações mostra a idade e a identidade da publicação, renovadas com a consulta normal do estado. A verificação NTP/Windows e a confirmação por tick recente continuam obrigatórias para iniciar a execução. Ausência de relógio e ausência de cotação agora têm mensagens distintas. O monitor UTC existente tenta revalidar após falhas transitórias; a retomada de execução suspensa mantém a exigência de início manual.

O replay offline reproduz o último conjunto histórico salvo, conferindo o hash de barras, contrato e parâmetros. Não consulta o MT5 nem exige relógio atual. Uma nova coleta continua exigindo relógio e histórico válidos. O replay conserva as premissas de custo originais e ainda não reproduz os novos perfis de dimensionamento.

Referências: https://www.metatrader5.com/en/terminal/help/algotrading/trade_robots_indicators e https://www.mql5.com/en/docs/calendar/calendarvaluehistory.

## Validação de 28/09/2026
- 139 testes Python aprovados; os dois publicadores compilaram sem erros ou avisos.
- Relógio independente e validação Windows/MT5 confirmados na integração real.
- Prévia real de 0,02 lote: perda estimada USD 2,00, margem USD 2,27 no instante consultado.
- Ordem DEMO EURUSD# 1002882579, negócio 989485292: 0,02 lote, entrada 1,13722, SL 1,13622, TP 1,13922. Stops e volume conferidos no servidor.
- Fechamento 1002882583, negócio 989485296, preço 1,13707; zero posições e zero ordens pendentes após reconciliação.
- Replays EURUSD# e BTCUSD# M5 com 220 candles e reprodução offline passaram. Custos hipotéticos para teste funcional, sem validação de rentabilidade.
- Corrigido NameError no baseline do replay (importação ausente de _true_ranges) e acrescentado teste do cruzamento real, sem substituir a regra por mock.
- Replays de 1.200 candles seguem bloqueados pela restrição de conversão histórica de fuso; não foi aplicado o offset atual a histórico antigo.
- A primeira ativação após a recompilação ainda executou a instância antiga como `PROGRAM_SCRIPT`. Às 19:55:02, o terminal registrou a nova instância como `PROGRAM_SERVICE`. No reinício do MT5, o diário registrou parada às 19:59:29 e início automático às 19:59:38; o log MQL5 confirmou novamente `PROGRAM_SERVICE`.
- Às 07:39 de 29/09/2026, o relógio publicava com idade de 1 segundo, sequência 2524, conta DEMO configurada e offset de 10.800 segundos. O calendário também publicava: 435 eventos, `status=available`, arquivo atualizado havia menos de 1 minuto. Os executáveis instalados no terminal têm o mesmo hash dos artefatos do projeto.
- A retomada dos dois serviços foi observada nesta instalação. Uma instalação nova ainda requer a primeira ativação em **Navegador → Serviços**; o aplicativo não deve presumir que um serviço não iniciado esteja ativo.
- Na aplicação aberta em 29/09/2026, `/api/state` confirmou conector MT5 conectado à mesma conta DEMO, `clock_bridge.ok=true`, publicação com cerca de 3 segundos, prova UTC `verified` por 10 de 11 ativos e ambos os motores parados. O terminal retornou zero posições. O pacote piloto `dist/ScalperLab-Pilot-onedir.zip` inclui os dois serviços e seu SHA-256 corresponde ao arquivo `.sha256` gerado.

Evidências: backups/qa-clock-recovery.json e backups/qa-replay-recent.json. A falha inicial em um teste de morte de processo foi uma disputa entre o próprio teste e o monitor pelo handle Windows; o teste agora usa o lock do conector durante terminate/join.
