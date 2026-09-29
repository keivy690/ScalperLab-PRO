# ScalperLab PRO — pacote piloto Windows

Esta pasta contém um pacote de validação `onedir`, ainda não um instalador de produção.

## Requisitos

- Windows 10/11 de 64 bits.
- MetaTrader 5 de 64 bits instalado, aberto e conectado à conta desejada.
- Microsoft Edge WebView2 Runtime instalado.
- A conta precisa ser confirmada na tela do ScalperLab antes de qualquer operação DEMO/REAL.

## Iniciar

1. Extraia a pasta `ScalperLab` para um local gravável pelo usuário.
2. Abra `ScalperLab.exe`.
3. Confirme a solicitação do UAC. Este pacote piloto solicita elevação porque o fluxo atual do projeto valida/ajusta o horário do Windows.
4. Mantenha o MT5 aberto. O ScalperLab não instala o terminal nem armazena a senha da conta.
5. Consulte o estado do conector, da conta e do relógio antes de armar qualquer motor.

O console será aberto junto com a janela nesta versão piloto para que erros de inicialização fiquem visíveis.
Os dados locais do usuário são gravados em `%USERPROFILE%\ScalperLabData`, fora da pasta do pacote.

## Componentes e limites

- `ScalperLab.exe`: interface desktop e backend local.
- `ScalperLabStrategyValidator.exe`: verificador isolado de sintaxe para arquivos Python importados. Ele compila/inspeciona o texto; não executa a estratégia importada.
- O conector Python do MT5 está dentro de `ScalperLab.exe` e usa a API oficial `MetaTrader5` incluída no diretório `_internal`; não há um segundo `conector.exe` para instalar no terminal.
- O relógio e o calendário são componentes MQL5 separados e somente de leitura. O pacote inclui `ScalperLabClockService` e `ScalperLabCalendarService` em formatos `.mq5` e `.ex5` dentro de `_internal\MT5`. Execute `Instalar-Servico-Calendario-MT5.bat` para copiar os dois à instalação escolhida. O instalador pede confirmação da pasta detectada ou permite informar a aberta em **Arquivo > Abrir pasta de dados** no MT5. Versões diferentes são preservadas com backup. Depois, atualize **Serviços** no Navegador do MT5 e inicie cada componente uma vez. Uma instância iniciada aparece sob o nome do serviço; confira as publicações no ScalperLab. Nesta instalação, os dois serviços retomaram a publicação após o reinício do terminal.
- O serviço de calendário não envia ordens e não substitui o conector Python de negociação.
- O pacote usa o estado do código registrado no `BUILD-MANIFEST.json`. Neste piloto o build pode incluir alterações locais ainda não publicadas.

## Validação piloto

Faça o primeiro teste em uma máquina Windows limpa, com uma conta DEMO, e sem iniciar os motores automaticamente. Confirme:

1. abertura da janela e carregamento de CSS/JavaScript;
2. estado real do terminal, conta e lista do Market Watch via conector Python;
3. instalação assistida e leitura do calendário pelo serviço MQL5, se habilitado;
4. importação de um `.py` válido e de outro com erro de sintaxe;
5. que o aplicativo continua bloqueando decisões quando os dados ou a confirmação UTC não são válidos;
6. que nenhuma ordem é criada apenas por abrir o executável.

O sucesso do build demonstra apenas que o pacote foi montado. Ele não comprova homologação do broker, rentabilidade, funcionamento em todos os terminais ou prontidão para conta REAL.
