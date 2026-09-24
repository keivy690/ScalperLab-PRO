# Manual de instalação e uso — ScalperLab PRO

**Versão documentada:** ScalperLab 1.0  
**Plataforma:** Windows, Python 3.12, terminal desktop MetaTrader 5  
**Estado de negociação:** o código permite envio automático condicionado em DEMO e REAL. Cada início REAL exige conta REAL identificada e confirmação textual específica; CONTEST é recusada. A operação REAL não concluiu homologação independente e não deve ser considerada pronta apenas porque o caminho existe.

## 1. O que o aplicativo faz

O ScalperLab é um aplicativo desktop local. A interface consulta o terminal MetaTrader 5 aberto no mesmo Windows, permite pesquisar fontes públicas, guardar estratégias para revisão, acompanhar posições abertas e iniciar motores em observação ou DEMO com confirmação explícita.

O aplicativo não autentica diretamente no broker e não armazena senha do MT5. Você abre o terminal, entra na conta desejada e o conector Python consulta a sessão ativa. O caminho REAL existe no backend, mas ainda requer homologação técnica e operacional independente; consulte a seção 7 antes de avaliar esse uso.

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
4. Dê duplo clique em `Iniciar-ScalperLab.bat`.
5. Na primeira execução, o script cria o ambiente `.venv` e instala as dependências do projeto. Isso pode levar alguns minutos.
6. A janela do ScalperLab deve abrir. Confira no cabeçalho se terminal, conta, servidor e modo DEMO estão corretos.

Não feche a janela de terminal do processo enquanto estiver usando o aplicativo. Para encerrar, feche normalmente a janela do ScalperLab; o programa desarma os motores ao sair.

### Inicialização pelo PowerShell

Use esta alternativa se preferir executar manualmente:

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

1. Informe de 1 a 12 símbolos exatamente como aparecem no Market Watch.
2. Selecione o timeframe. M15 é a recomendação inicial; outros períodos expostos pelo MT5 também podem ser selecionados.
3. Salve o perfil.
4. Use **Iniciar observação** para calcular e mostrar leituras sem enviar ordens.
5. Para envio automático em DEMO, confira cuidadosamente conta e ativos, clique **Iniciar execução DEMO**, digite exatamente `INICIAR ANALISTA SOMENTE DEMO` e confirme o diálogo.
6. Acompanhe o estado no painel. O motor reinicia parado quando o aplicativo fecha ou reinicia.

A regra atual é uma heurística de pullback: tendência e momentum alinhados, candle fechado retomando a SMA 21, spread dentro do limite, stop derivado da estrutura recente, alvo de 1,5R, risco estimado de até 0,10% do equity e volume máximo de 0,01 lote. Antes de iniciar, o backend confere se os ativos configurados correspondem a símbolos visíveis no Market Watch. Uma entrada também depende dos bloqueios de conta, cotação, posição, pré-verificação e reconciliação do MT5. Isso é experimental, não evidência de vantagem estatística.

A análise fundamental passa a exibir `PARCIAL` quando o Service de calendário MQL5 publica um snapshot recente da mesma conta e servidor. Ela lista eventos relacionados às moedas do ativo, importância e horário no fuso informado pelo MT5. Sem a ponte, com snapshot atrasado ou com conta divergente, o calendário aparece indisponível. Eventos ainda são contexto informativo: não mudam o lado do sinal nem bloqueiam ordens. Notícias, séries de juros e fundamentos por classe ainda não foram conectados; portanto o Analista **não confirma uma análise fundamental completa**.

##### Ativar o calendário econômico nativo do MT5

O calendário é exposto a programas MQL5, mas não à API Python direta usada pelo ScalperLab. Para iniciar a ponte local:

1. No MT5 conectado à conta que o ScalperLab usará, escolha **Arquivo → Abrir pasta de dados**.
2. Dentro da pasta aberta, acesse `MQL5\Services` e copie para lá `C:\ScalperLab 1.0\mt5\ScalperLabCalendarService.mq5`.
3. Abra o MetaEditor pelo MT5, localize o arquivo em Services e compile-o. Corrija qualquer erro antes de iniciar.
4. No Navegador do MT5, atualize **Services**, localize `ScalperLabCalendarService` e inicie uma instância.
5. Confirme no Diário/Experts a mensagem `ScalperLab Calendar Service: ... status disponivel`.
6. Deixe o terminal conectado. O ScalperLab só aceita snapshots recentes vinculados ao mesmo login e servidor.

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
- posições abertas: ticket, ativo, lado, volume, preços, SL/TP, resultado, horário e identificadores;
- símbolo: dígitos, ponto, tamanho/valor de tick, tamanho do contrato, moedas base/lucro/margem, setor/país, swap, volume mínimo/máximo/passo, nível de stops e modos de preenchimento/execução;
- mercado: candles OHLC fechados, tick volume/volume real disponível, spread de candle e tick atual de compra/venda com horário.

Esses dados são suficientes para mostrar estado e posições abertas e formar as regras técnicas/quantitativas que já existem, com validação de lote baseada no cálculo de lucro/perda fornecido pelo MT5.

Ainda faltam, entre outros:

- calendário econômico, notícias, taxas e fundamentos atuais e estruturados por classe de ativo;
- leitura de ordens pendentes e histórico completo de ordens/negócios pelo aplicativo;
- validação de margem e custos totais projetados integrada a cada sinal, além do risco estimado atual;
- fonte e normalização de dados para análise fundamentalista e avaliação de eventos;
- homologação por broker, símbolo, sessão e timeframe, bem como replay/backtest e validação forward documentados.

Logo, **o sistema não recebe hoje todas as informações necessárias para atuar como analista fundamentalista completo nem para homologar execução financeira de produção**. A disponibilidade de campos também depende do broker, símbolo, histórico carregado no terminal e configurações de barras máximas.

## 7. Conta REAL: capacidade técnica e homologação

O conector pode identificar uma sessão REAL já aberta no terminal e ler estado da conta, posições abertas, cotações, candles e metadados que o broker disponibiliza. Isso é conexão de leitura, não autorização para operar.

Os motores possuem caminhos de envio REAL condicionados a confirmação textual específica, identificação de conta e servidor, permissões do terminal, sinal elegível, risco dentro do limite, stop/alvo válidos, ausência de posições/ordens pendentes e reconciliação após o envio. Fechamentos REAL também exigem armamento e confirmação. A conta CONTEST é recusada. Verifique sempre o modo e a identidade da conta no MT5 e no ScalperLab antes de qualquer armamento.

**Conclusão: capacidade de envio REAL existe no código, mas não há homologação suficiente para qualificá-la como pronta para operação.** Ainda são necessários, no mínimo, política fundamental definida, replay sem look-ahead com custos do broker, forward test DEMO com critérios objetivos, cenários de falha e recuperação, limites de risco/exposição aprovados e revisão independente de segurança/execução. As confirmações explícitas são controles técnicos, não substituem essas evidências.

## 8. Onde ficam os dados e como fazer cópia

Banco local, perfis, estratégias, fontes e logs ficam em:

`%LOCALAPPDATA%\ScalperLab\scalperlab.sqlite3`

Para criar uma cópia consistente sem copiar arquivos do banco manualmente, execute no PowerShell dentro da pasta do projeto:

`\.venv\Scripts\python.exe -m scalperlab.database_backup`

O arquivo SQLite é gravado em `%LOCALAPPDATA%\ScalperLab\backups` e passa por `integrity_check`. Para restaurar, feche o ScalperLab e execute:

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
