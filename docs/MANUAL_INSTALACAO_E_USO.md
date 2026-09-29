# Manual de instalação e uso — ScalperLab PRO

**Versão documentada:** ScalperLab 1.0  
**Plataforma:** Windows, Python 3.12, terminal desktop MetaTrader 5  
**Estado de negociação:** o código permite envio automático condicionado em DEMO e REAL. Cada início REAL exige conta REAL identificada e confirmação textual específica; CONTEST é recusada. A operação REAL não concluiu homologação independente e não deve ser considerada pronta apenas porque o caminho existe.

## 1. O que o aplicativo faz

O ScalperLab é um aplicativo desktop local. A interface consulta o terminal MetaTrader 5 aberto no mesmo Windows, permite pesquisar fontes públicas, guardar estratégias para revisão, acompanhar posições abertas e iniciar motores em observação, DEMO ou REAL com confirmação explícita e verificações do backend.

O aplicativo não autentica diretamente no broker e não armazena senha do MT5. Você abre o terminal, entra na conta desejada e o conector Python consulta a sessão ativa. O caminho REAL está implementado com confirmação explícita e verificações técnicas; a operação ainda precisa de homologação técnica e operacional independente antes de ser tratada como pronta.

O cabeçalho do aplicativo mostra conexão do terminal, conta/modo, servidor e modo atual da automação. Ao clicar em **Iniciar execução DEMO/REAL** no Analista, o aplicativo confere automaticamente, somente por leitura, o Windows Time e ticks recentes do MT5 quando ainda não houver confirmação UTC válida. Depois apresenta uma única confirmação textual com conta, ativos e limites de risco. O backend repete as verificações antes de armar o motor. Se o relógio precisar de correção, o início é recusado e você pode usar **Verificar horário UTC** na lateral; essa ação manual pode solicitar confirmação UAC. A checagem automática do início não ajusta o relógio nem envia ordens. Observação permanece disponível. Não ajuste manualmente o fuso ou a hora para contornar a validação.

O cartão **Estado operacional** e o cabeçalho resumem o Analista e o motor de estratégias. “Analista · DEMO” ou “Estratégias · DEMO” quer dizer que o respectivo modo está ativo e pode avaliar entradas; não confirma que uma ordem foi enviada. A decisão só aparece como confirmada quando o ScalperLab encontra a posição correspondente no MT5 e verifica os níveis de stop e alvo. Se o relógio UTC vencer durante a execução, o backend suspende novas entradas e mostra **Execução bloqueada**; posições que já existirem permanecem no terminal e devem ser conferidas por você.

## 2. Requisitos

- Windows com ambiente desktop.
- Python **3.12** instalado. O instalador automático usa o Python Launcher (`py -3.12`).
- MetaTrader 5 desktop instalado pelo broker, aberto e conectado. Para validar ordens, comece por uma conta DEMO.
- A opção global de negociação algorítmica do terminal deve estar habilitada para envio DEMO. As regras do broker e do símbolo também se aplicam.
- Conexão com a internet na primeira instalação e para provedores de pesquisa/IA que forem usados.

Use o mesmo usuário do Windows para abrir o MT5 e o ScalperLab. Se houver mais de uma instalação/instância do terminal, confira no cabeçalho do ScalperLab o servidor, modo e login identificados antes de qualquer ação.

## 3. Instalação

O projeto fica em:

`C:\ScalperLab 1.0`

### Instalação recomendada

1. Instale Python 3.12 e o terminal MT5, se ainda não estiverem instalados.
2. Abra o terminal MT5, entre na conta DEMO e confirme que os preços estão atualizando.
3. Abra a pasta `C:\ScalperLab 1.0` no Explorador de Arquivos.
4. Dê duplo clique em `Iniciar-ScalperLab.bat` e aceite o pedido do Windows (UAC) para executar como administrador. O inicializador solicita essa elevação porque a validação/correção do serviço de horário do Windows pode precisar dela.
5. Na primeira execução, o script cria o ambiente `.venv` e instala as dependências do projeto. Isso pode levar alguns minutos.
6. A janela do ScalperLab deve abrir. Confira no cabeçalho se terminal, conta, servidor e modo DEMO estão corretos.

Não feche a janela de terminal do processo enquanto estiver usando o aplicativo. Para encerrar, feche normalmente a janela do ScalperLab; o programa desarma os motores ao sair.

### Inicialização pelo PowerShell

Use esta alternativa se preferir executar manualmente; abra o PowerShell com **Executar como administrador** antes:

```powershell
Set-Location 'C:\ScalperLab 1.0'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe run.py
```

Se o ambiente `.venv` já foi criado pelo arquivo `.bat`, não é necessário recriá-lo; instale/atualize dependências somente se o inicializador indicar falha.

## 4. Conexão com o MT5

1. Abra o MT5 e faça login nele primeiro.
2. Mantenha o terminal aberto e conectado ao servidor do broker.
3. Inicie o ScalperLab.
4. Confira o modo (`DEMO` ou `REAL`), login e servidor mostrados no cabeçalho. Se a conta apresentada não for a esperada, não inicie nenhum motor; corrija a sessão no MT5 e atualize o painel.
5. Use o ícone de atualização ou aguarde a atualização automática do painel. A tela consulta o estado geral a cada 9 segundos; o Analista calcula um novo ciclo a cada 30 segundos.

O conector chama a API Python oficial do MT5 e depende do terminal disponível no computador. O aplicativo não oferece seletor de caminho/instância de terminal nem campo de login/senha. Não considere a indicação “conectado” suficiente sem conferir conta, servidor e modo.

## 5. Áreas do aplicativo

### Painel principal

Mostra saldo, patrimônio, resultado flutuante, quantidade de posições abertas, resumo das estratégias cadastradas e os últimos resultados do Analista por ativo. As informações financeiras vêm do MT5; se o terminal não fornecer os dados, o painel deve mostrar indisponibilidade em vez de valores fictícios.

O cartão do Analista resume a leitura técnica, quantitativa e fundamental. Use **Ver análise completa** para abrir a área de configuração e ver detalhes/regras do sinal.

### Estratégias

Você pode cadastrar uma descrição ou importar `.mq5`, `.py` e `.txt` de até 1 MB. O arquivo é guardado como material para revisão e recebe verificações estáticas. O aplicativo **não executa nem compila** o código importado e não o converte automaticamente em regra de negociação.

O fluxo do catálogo é: criar rascunho → revisar manualmente → aprovar ou rejeitar. Aprovar um item não inicia um motor.

O motor declarativo reconhece somente estas regras pelo nome exato:

- Momentum cross-sectional de moedas (literatura)
- Momentum de séries temporais em futuros (literatura)
- Carry trade FX com controle fora da amostra
- Reversão de gap de fim de semana em FX
- Rompimento da faixa de abertura de Londres (ORB FX)

Elas são adaptações operacionais, não reproduções exatas dos estudos nem estratégias com rentabilidade comprovada. Para operar pelo motor declarativo, a ficha precisa ser compatível, aprovada, configurada e iniciada separadamente.

### Pesquisa de fontes

- **GitHub:** consulta repositórios públicos pela API oficial.
- **Busca web:** depende da variável `SCALPERLAB_BRAVE_API_KEY`.
- **YouTube:** depende de `SCALPERLAB_YOUTUBE_API_KEY`.
- **Feeds RSS/Atom:** cadastre uma URL HTTPS pública para importar fontes do feed.
- **Importar URL:** salva metadados e trechos de páginas públicas que permitam coleta.
- **Analisar seleção com IA:** depende de `OPENAI_API_KEY` e envia ao provedor somente os itens selecionados (título, URL, origem e trecho). O resumo não gera uma ordem nem aprova uma estratégia.

As fontes respeitam disponibilidade, quotas, termos e direitos dos provedores. Indisponibilidade de chave, quota ou site não significa que a pesquisa tenha sido concluída.

### Ordens e posições

Exibe **posições abertas** consultadas no MT5. O conector atual não lista ordens pendentes nem histórico completo de ordens/negócios fechados. Fechar posição individual é restrito à conta DEMO, após armar o fechamento e confirmar a ação.

### Risco e segurança

Esta área contém o Analista de mercado e o motor declarativo. Eles são independentes; o backend impede que ambos estejam armados para envio DEMO ao mesmo tempo.

#### Analista de mercado

1. Clique em **Atualizar lista do MT5**. O conector consulta os ativos visíveis no Market Watch da sessão conectada; use a busca e marque de 1 a 12 símbolos. Para adicionar um ativo, primeiro torne-o visível no próprio Market Watch do MT5 e atualize a lista no ScalperLab. O nome e o sufixo do broker são mantidos.
2. Selecione o timeframe. M15 é a recomendação inicial; outros períodos expostos pelo MT5 também podem ser selecionados.
3. Salve o perfil.
4. Use **Iniciar observação** para calcular e mostrar leituras sem enviar ordens.
5. Para envio automático em DEMO, confira cuidadosamente conta, servidor e ativos e clique **Iniciar execução DEMO**. Se o Analista estiver em observação, confirme a troca; se o perfil mudou, ele será salvo. Quando o horário UTC não estiver validado, o aplicativo perguntará se pode fazer a verificação antes de prosseguir. Digite exatamente `INICIAR ANALISTA SOMENTE DEMO` e confirme o diálogo.
6. Para execução REAL, conecte primeiro no MT5 a conta REAL correta e confirme o modo da conta, servidor, ativos e limites. Clique **Iniciar execução REAL**, leia os avisos, digite exatamente `AUTORIZO ANALISTA EM CONTA REAL` e confirme. A execução REAL só é aceita quando o terminal identifica uma conta REAL e a negociação está habilitada; a tela não converte nem trata uma sessão DEMO como REAL.
7. Acompanhe o estado no painel. O motor reinicia parado quando o aplicativo fecha ou reinicia.

O botão de execução conduz a validação de horário UTC quando ela estiver pendente. O aplicativo pode pedir confirmação antes de consultar/sincronizar o serviço Windows Time; essa etapa não envia ordens. Na troca de observação para execução, o backend para a observação e espera o ciclo em andamento terminar antes de iniciar o novo modo. Se a fonte NTP não permitir medição independente ou não houver tick MT5 recente para calibrar UTC, o aplicativo mantém o envio bloqueado. A confirmação vale por até 15 minutos; enquanto o aplicativo desktop estiver aberto, o monitor tenta renová-la em segundo plano a cada 4 minutos e repete uma tentativa temporariamente falha após 45 segundos. A renovação não ajusta o relógio nem rearma o motor. Durante a execução, os motores conferem a validade e a conta/terminal no começo de cada ciclo e antes de enviar uma ordem. Se a fonte mostrar desvio real, a conta mudar ou a confirmação expirar sem renovação, o motor suspende novas entradas; verifique posições no MT5, corrija o horário se necessário e inicie o motor novamente.

A regra atual opera no modo explícito **Técnica + quantitativa**: heurística de pullback com tendência e momentum alinhados, candle fechado retomando a SMA 21, spread dentro do limite, stop derivado da estrutura recente, alvo de 1,5R, risco estimado de até 0,10% do equity e volume máximo de 0,01 lote. Antes de iniciar, o backend confere se os ativos configurados correspondem a símbolos visíveis no Market Watch. Uma entrada também depende dos bloqueios de conta, cotação, posição, pré-verificação e reconciliação do MT5. Isso é experimental, não evidência de vantagem estatística.

##### Replay e validação cronológica

O painel **Replay e validação cronológica** compara a regra de pullback SMA 21 com um baseline simples de cruzamento do retorno de 20 candles. Ambos usam a mesma gestão simulada (stop ATR14, alvo 1,5R e premissas de spread/slippage/comissão/swap). O replay é somente leitura: não envia, modifica nem fecha ordens. O backend recusa a consulta enquanto o Analista ou o motor declarativo estiverem executando, pois compartilham o conector MT5.

1. Pare os motores e confirme no cabeçalho que não há execução DEMO/REAL ativa.
2. Escolha um ativo visível no Market Watch, timeframe e pelo menos 200 candles fechados. São solicitados até 2.500 candles OHLC do histórico carregado no terminal; os horários retornados pela API Python do MT5 são interpretados como UTC e o offset do tick atual não é subtraído deles.
3. Informe slippage por lado, comissão total de ida e volta por lote e swap assinado por lote por virada de data UTC, com base na tabela da conta/corretora. Zero só deve ser informado quando o custo realmente for zero.
4. Marque a confirmação de custos e clique **Executar replay somente leitura**.
5. Compare os segmentos: os 70% iniciais mostram contexto de desenvolvimento; os 30% finais são o holdout cronológico. Observe as operações e métricas de cada regra, período, amostra e hash SHA-256. O snapshot dos candles/contrato e os parâmetros ficam guardados localmente por até 50 execuções.

O holdout não deve ser usado repetidamente para ajustar parâmetros. O resultado mostra “amostra insuficiente” quando qualquer regra tem menos de 30 operações fechadas no holdout. Isso impede uma conclusão descritiva mínima, mas 30 operações não são um critério de aprovação estatística. Toda execução permanece **triagem OHLC não homologada**: entrada na abertura do candle seguinte; spread por barra; stop primeiro se stop e alvo couberem no mesmo candle; custos e slippage informados; conversão monetária usa valores atuais do contrato. Não são usados ticks reais, Strategy Tester, histórico integral de custos, rolagem tripla ou execução intrabar. Posições abertas no fim do segmento são censuradas. Antes de qualquer homologação, compare com ticks reais do broker ou Strategy Tester “Every tick based on real ticks”, defina critérios prévios e mantenha uma janela futura intocada. Nenhum resultado comprova rentabilidade ou autoriza operação REAL.

A análise fundamental passa a exibir `PARCIAL` quando o Service de calendário MQL5 publica um snapshot recente da mesma conta e servidor. Ela lista eventos relacionados às moedas do ativo, importância e horário no fuso informado pelo MT5. Sem a ponte, com snapshot atrasado ou com conta divergente, o calendário aparece indisponível. No modo atual, eventos são informativos: não mudam o lado do sinal nem bloqueiam ordens. Notícias, séries de juros e fundamentos por classe ainda não foram conectados; portanto este modo **não é uma análise fundamental completa**. A opção futura de três camadas deverá exigir fonte atual e adequada ao ativo antes de permitir entradas.

##### Ativar o calendário econômico nativo do MT5

O calendário é exposto a programas MQL5, mas não à API Python direta usada pelo ScalperLab. Para iniciar a ponte local:

1. Na versão empacotada, execute `Instalar-Servico-Calendario-MT5.bat` ao lado de `ScalperLab.exe`. A ferramenta detecta pastas de dados MT5 comuns e pede que você escolha uma; se necessário, abra **Arquivo → Abrir pasta de dados** no terminal e informe aquela pasta.
2. O instalador copia `ScalperLabCalendarService.mq5` e `ScalperLabCalendarService.ex5` para `MQL5\Services`. Se já houver uma versão diferente, ela é preservada com backup antes da atualização. No projeto aberto pelo código-fonte, execute `tools\install-mt5-calendar-service.bat`.
3. No Navegador do MT5, atualize **Services**, localize `ScalperLabCalendarService` e inicie uma instância. Se o terminal rejeitar o arquivo `.ex5`, abra o `.mq5` no MetaEditor pelo MT5, compile e corrija qualquer erro antes de iniciar.
4. Confirme no Diário/Experts a mensagem `ScalperLab Calendar Service: ... status disponivel`.
5. Deixe o terminal conectado. O ScalperLab só aceita snapshots recentes vinculados ao mesmo login e servidor.

O conector Python de mercado e ordens está embutido em `ScalperLab.exe`; não há um EA separado para enviar ordens. O Service MQL5 descrito aqui só exporta dados do calendário e não negocia.

O Service consulta a janela de 2 dias anteriores e 7 dias futuros a cada 60 segundos. O snapshot fica em `Terminal\Common\Files\ScalperLab_calendar_v1.json`. O timestamp de cada evento permanece no fuso do servidor da corretora; a interface identifica esse fuso e não o trata como UTC. O Service só consulta e exporta dados e não chama funções de negociação. Depois de iniciar uma instância no MT5, confira se ela continua ativa após reiniciar o terminal.

Se a corretora/servidor não fornecer o calendário, o Service publica estado indisponível e o ScalperLab não apresenta a lista como vazia nem como válida.

#### Motor de estratégias cadastradas

1. Selecione uma estratégia compatível e aprovada.
2. Configure símbolos/universo, parâmetros de sessão e limites disponíveis para a regra.
3. Use **Iniciar observação** antes de considerar envio.
4. Para execução DEMO, confira conta e configuração, clique **Iniciar execução DEMO**, digite `INICIAR MOTOR SOMENTE DEMO` e confirme.

Tetos do motor incluem 0,01 lote, risco por operação de até 0,25% e limite diário configurável de até 1%. A perda calculada não cobre comissão, swap, spread variável, slippage, gaps ou execução pior; o prejuízo real pode ultrapassar a estimativa.

#### Parar e emergência

- **Parar analista/motor** impede novas entradas; não fecha posições que já estejam abertas.
- A **parada de emergência** desarma os dois motores e pede fechamento das posições da conta DEMO. Digite exatamente `FECHAR TODAS AS POSIÇÕES DEMO` e confirme.
- Depois da parada, confira manualmente no MT5 se não restaram posições. Em falha, timeout ou resultado desconhecido, não repita às cegas: atualize posições e histórico diretamente no terminal e investigue primeiro.

O botão **Teste · 0,01 EURUSD** pode enviar uma compra a mercado no menor lote permitido (limitado a 0,01) e solicitar fechamento imediato. O teste é somente DEMO, é recusado se houver qualquer posição preexistente e pode gerar spread, comissão ou slippage. Use-o somente quando compreender esse efeito.

### Configurações

Mostra a disponibilidade dos provedores. Para adicionar uma chave opcional no Windows:

1. Abra **Editar as variáveis de ambiente para sua conta** no menu Iniciar.
2. Em **Variáveis de usuário**, escolha **Novo**.
3. Cadastre o nome da variável (`SCALPERLAB_BRAVE_API_KEY`, `SCALPERLAB_YOUTUBE_API_KEY` ou `OPENAI_API_KEY`) e o valor obtido diretamente do respectivo provedor.
4. Salve e feche completamente o ScalperLab; inicie novamente pelo `.bat`.

Não coloque chaves dentro dos arquivos do projeto, em estratégias importadas, capturas de tela ou mensagens. Sem essas chaves, pesquisa GitHub e feeds RSS/Atom continuam disponíveis conforme as fontes cadastradas.

## 6. O conector fornece todos os dados necessários?

**Não para toda a finalidade pretendida.** Hoje o conector lê:

- conta: login, servidor, empresa, moeda, saldo, equity, resultado e alavancagem;
- terminal: nome/build, conexão e permissão geral de negociação;
- posições abertas, ordens pendentes e histórico de ordens/negócios por consultas do conector; o painel visual atual prioriza posições abertas e a auditoria conserva evidências de tentativas e reconciliações;
- símbolo: dígitos, ponto, tamanho/valor de tick, tamanho do contrato, moedas base/lucro/margem, setor/país, swap, volume mínimo/máximo/passo, nível de stops e modos de preenchimento/execução;
- mercado: candles OHLC fechados, tick volume/volume real disponível, spread de candle e tick atual de compra/venda com horário.

Esses dados são suficientes para mostrar estado e posições abertas e formar as regras técnicas/quantitativas que já existem, com validação de lote baseada no cálculo de lucro/perda fornecido pelo MT5.

Ainda faltam, entre outros:

- calendário econômico, notícias, taxas e fundamentos atuais e estruturados por classe de ativo;
- leitura de ordens pendentes e histórico completo de ordens/negócios pelo aplicativo;
- validação de margem e custos totais projetados integrada a cada sinal, além do risco estimado atual; o replay usa custos configurados e ainda não corresponde a uma simulação por ticks ou ao Strategy Tester;
- fonte e normalização de dados para análise fundamentalista e avaliação de eventos;
- comparação do replay com baseline simples, holdout cronológico, walk-forward e validação forward documentada;

Logo, **o sistema não recebe hoje todas as informações necessárias para atuar como analista fundamentalista completo nem para homologar execução financeira de produção**. A disponibilidade de campos também depende do broker, símbolo, histórico carregado no terminal e configurações de barras máximas.

## 7. Conta REAL: capacidade técnica e homologação

O conector pode identificar uma sessão REAL já aberta no terminal e ler estado da conta, posições abertas, cotações, candles e metadados que o broker disponibiliza. Isso é conexão de leitura, não autorização para operar.

Os motores possuem caminhos de envio REAL condicionados a confirmação textual específica, identificação de conta e servidor, permissões do terminal, sinal elegível, risco dentro do limite, stop/alvo válidos, ausência de posições/ordens pendentes e reconciliação após o envio. Fechamentos REAL também exigem armamento e confirmação. A conta CONTEST é recusada. Verifique sempre o modo e a identidade da conta no MT5 e no ScalperLab antes de qualquer armamento.

**Conclusão: capacidade de envio REAL existe no código, mas não há homologação suficiente para qualificá-la como pronta para operação.** O replay atual é uma triagem reproduzível em OHLC: usa a regra atual, entrada estimada no candle seguinte, spread por candle e hipóteses informadas de comissão, swap e slippage. Ele não usa ticks reais, não reproduz integralmente custos históricos e execução intrabar do broker, e não demonstra vantagem estatística. Ainda são necessários, no mínimo, política fundamental definida, replay mais fiel aos ticks/custos do broker com validação cronológica, forward test DEMO com critérios objetivos, cenários de falha e recuperação, limites de risco/exposição aprovados e revisão independente de segurança/execução. As confirmações explícitas são controles técnicos, não substituem essas evidências.

## 8. Onde ficam os dados e como fazer cópia

Banco local, perfis, estratégias, fontes e logs ficam em:

`%USERPROFILE%\ScalperLabData\scalperlab.sqlite3`

Para criar uma cópia consistente sem copiar arquivos do banco manualmente, execute no PowerShell dentro da pasta do projeto:

`\.venv\Scripts\python.exe -m scalperlab.database_backup`

O arquivo SQLite é gravado em `%USERPROFILE%\ScalperLabData\backups` e passa por `integrity_check`. Para restaurar, feche o ScalperLab e execute:

`\.venv\Scripts\python.exe -m scalperlab.database_backup --restore "CAMINHO_DO_BACKUP.sqlite3"`

A restauração exige digitar `RESTAURAR BANCO LOCAL` e guarda uma cópia automática do banco atual antes de substituí-lo. Guarde os backups em local privado e protegido: o banco pode conter código importado e material de pesquisa. As chaves de provedores não são armazenadas nesse banco.

## 9. Solução de problemas

| Sintoma | O que verificar |
|---|---|
| Terminal desconectado no painel | Abra o MT5, confirme login/rede e atualize. Verifique se o terminal correto está aberto. |
| Conta ou servidor incorreto | Não inicie motores. Corrija a sessão no MT5 e confira novamente o cabeçalho. |
| Envio DEMO bloqueado | Confirme modo DEMO, botão global de negociação do MT5 ativo, símbolo negociável e perfil salvo. |
| Nenhuma análise aparece | Salve ao menos um símbolo exato, inicie observação ou DEMO e aguarde o próximo ciclo (até cerca de 30 segundos). Confira se o terminal carregou histórico suficiente. |
| Há análise, mas não há entrada | Isso pode ser normal: confirme candle fechado, alinhamento dos vieses, pullback, spread, posição existente, cotação e limites de risco. O status e os motivos são mostrados no cartão. |
| Símbolo não encontrado ou sem histórico | Confira sufixo do broker (por exemplo, `.a`), Market Watch, timeframe e histórico disponível. |
| Busca web/YouTube/IA indisponível | Confira a variável de ambiente, a chave/quota do provedor e reinicie o aplicativo após alterar variáveis. GitHub e feeds não exigem essas chaves. |
| Falha de instalação | Confirme Python 3.12 acessível por `py -3.12`, internet, permissões para criar `.venv` e mensagens mostradas pela janela do `.bat`. |
| Envio com status incerto ou rejeitado | Não clique repetidamente. Inspecione posições e histórico no MT5; o aplicativo evita reenviar um envio ambíguo. |

## 10. Rotina operacional recomendada

1. Abra MT5 e confira o login, servidor e modo DEMO.
2. Abra ScalperLab e confira os mesmos dados na interface.
3. Confira se as posições abertas no painel correspondem ao terminal.
4. Configure o Analista ou um motor cadastrado e inicie em observação primeiro.
5. Só inicie DEMO se compreender a regra, o ativo, timeframe, risco e consequências de deixar o processo aberto.
6. Monitore logs, posições e estado do terminal; o aplicativo não substitui supervisão humana.
7. Ao terminar, pare o motor e confira posições diretamente no MT5. Fechar o ScalperLab não encerra automaticamente posições abertas.


## Lote e risco — Configurações (28/09/2026)

1. Abra **Configurações → Lote e risco** e selecione Analista ou Estratégias.
2. Escolha automático por percentual, automático por valor monetário, ou lote fixo. O lote fixo continua sujeito ao teto percentual de risco, ao máximo por ordem e ao contrato do ativo.
3. Defina lote máximo e reserva da margem livre. A reserva de 20% permite consumir no máximo 80% da margem livre disponível no momento. O limite percentual diário é compartilhado pelos dois motores.
4. Pare os motores para salvar. Alterar valores não inicia operações, não altera SL/TP existentes e não apaga um bloqueio diário já atingido.
5. Em **Prévia de lote e margem**, escolha um ativo real do Market Watch, compra/venda e o preço do stop. A cotação atual é usada como entrada. Salve alterações antes de calcular. A prévia não envia ordens e precisa ser refeita se o mercado mudar.
6. Confira lote calculado, perda estimada, margem necessária e margem livre restante. Se o volume não respeitar mínimo/passo, risco ou reserva, a prévia informa o motivo. Não há aumento automático até o lote mínimo.
7. Volte a **Risco e segurança** para iniciar o motor no modo desejado. O resumo e a confirmação exibem o perfil salvo. O envio reconfirma cotação, volume, risco, margem e identidade da conta.

O dia de risco é UTC, independente da sessão da estratégia. A referência mostra o horário real da primeira leitura; não representa automaticamente o patrimônio de meia-noite. Reinício/troca de motor preservam consumo e bloqueio no mesmo dia. Depósitos/saques e crédito são reconciliados por identidade dos negócios de saldo; histórico indisponível ou revisado bloqueia novas entradas. O limite considera variação de patrimônio da conta inteira e não garante uma perda máxima executada.

Informações sobre chaves, procedência e validação de arquivos ficam no grupo recolhível **Integrações de pesquisa e informações do aplicativo**, no fim de Configurações. Os custos do replay pertencem ao painel de replay e o alvo das estratégias continua no perfil da regra. O replay existente ainda não usa automaticamente estes novos perfis de dimensionamento.

## Pesquisa de zonas S/R Quant (29/09/2026)

1. Abra **Risco e segurança → Pesquisa de zonas S/R**. Pare o Analista e o motor de estratégias antes de iniciar; eles compartilham o conector MT5.
2. Escolha um ou dois símbolos exatos trazidos do Market Watch e clique em **Iniciar pesquisa**. O módulo lê H1, M15 e M5 fechados, sem enviar ordens. Ele começa desligado após cada reinício.
3. Leia por ativo o regime, as zonas, os candidatos e os motivos de rejeição. Um candidato indica apenas uma hipótese em pesquisa; não equivale a uma ordem solicitada ou executada.
4. Abra **Replay histórico S/R**, escolha um ativo, a amostra M5 e custos da corretora, confirme-os e execute. O relatório separa desenvolvimento e holdout, compara as três famílias com um baseline e salva o conjunto de dados e o hash. **Reproduzir último salvo (offline)** recalcula o último estudo sem consultar o MT5.
5. Se o MT5 não confirmar que o histórico H1/M15/M5 está em UTC, a pesquisa ou o replay recusa os dados. Não altere o fuso manualmente para forçar resultado. Falta de histórico ou menos de 30 trades fechados no holdout implica amostra inconclusiva.

No terminal XMGlobal-MT5 7 consultado em 29/09/2026, H1 estava no horário do servidor e foi recusado. O serviço de relógio confirma o offset **atual**, mas não a regra histórica de mudança de horário. Enquanto essa regra não for documentada e conferida para o servidor, a pesquisa S/R mostrará dados insuficientes nesse terminal. O Analista SMA21 anterior não depende desta pesquisa.

Esta pesquisa permanece separada da execução DEMO/REAL. A regra antiga do Analista continua disponível; nenhuma família S/R foi habilitada para envio nesta etapa. Consulte `docs/IMPLEMENTACAO_SR_QUANT_2026-09-29.md` para critérios de promoção.
