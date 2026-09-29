# Plano de entrega do executável — ScalperLab PRO

**Estado em 29/09/2026:** plano de aceitação ainda aberto. O build script atual chama o instalador `Instalar-Servico-Calendario-MT5.bat/.ps1` embora ele copie **ClockService e CalendarService**. Renomeá-lo para representar os dois componentes continua uma melhoria pendente; o nome atual é o mostrado na estrutura real abaixo. O piloto anterior não contém necessariamente S/R Quant; [estado atual](ESTADO_ATUAL.md).

## Decisão de formato

Gerar um pacote Windows `onedir`: `ScalperLab.exe` acompanhado de `_internal`, do validador de scripts e de um instalador assistido dos dois Services MQL5. O aplicativo depende de um MetaTrader 5 instalado e conectado; o pacote não contém o terminal nem credenciais da corretora. Entregar também um ZIP e um SHA-256. O instalador Windows tradicional fica para uma etapa posterior, após validação do pacote em outra instalação.

Estrutura esperada:

```text
ScalperLab/
  ScalperLab.exe
  ScalperLabStrategyValidator.exe
  Instalar-Servico-Calendario-MT5.bat
  Instalar-Servico-Calendario-MT5.ps1
  LEIA-ME-PRIMEIRO.txt
  BUILD-MANIFEST.json
  _internal/
    MT5/ScalperLabClockService.mq5
    MT5/ScalperLabClockService.ex5
    MT5/ScalperLabCalendarService.mq5
    MT5/ScalperLabCalendarService.ex5
    ... bibliotecas Python, interface e recursos ...
```

## Responsabilidade de cada peça

| Peça | Instalação | Função | Confirmação exigida |
| --- | --- | --- | --- |
| `ScalperLab.exe` | Pasta extraída do pacote | Interface, API local, armazenamento, motores e conector Python em processo separado | Janela abre, API somente em loopback, conector lê a conta e o Market Watch corretos |
| `ScalperLabClockService` | `MQL5/Services` da pasta de dados do MT5 escolhido | Publica relógio a cada 10 segundos em `MQL5/Files` do próprio terminal | Log `PROGRAM_SERVICE`, identidade correta e publicação com menos de 45 segundos |
| `ScalperLabCalendarService` | Mesmo diretório `MQL5/Services` | Publica calendário no diretório comum do MT5 | Log `PROGRAM_SERVICE`, conta/servidor corretos e exportação recente |
| `ScalperLabStrategyValidator.exe` | Ao lado do aplicativo | Analisa sintaxe de `.py` importado em processo isolado | Retorno válido e erro de sintaxe tratados sem executar o script |

## Etapas antes do build

1. **Congelar a entrada:** registrar arquivos, versões e hash dos dois `.ex5`, dependências e estado Git no manifesto. Confirmar que `#property service` consta dos dois `.mq5`, que ambos compilam sem erro e que os binários do projeto correspondem aos instalados no terminal de referência.
2. **Revisar o instalador MT5:** dar-lhe nome que represente os dois componentes; pedir ao usuário a pasta de dados aberta por **Arquivo → Abrir pasta de dados**, mostrando o terminal e a conta detectados. Não escolher automaticamente uma pasta entre vários MT5. Confirmar o destino antes de copiar, preservar versões anteriores, verificar hash após a cópia e informar quando for preciso parar/iniciar uma instância em execução. A instalação não altera gráficos, credenciais ou configurações de negociação.
3. **Revisar a execução congelada:** conferir `multiprocessing.freeze_support()`, criação do processo do conector, carregamento da biblioteca `MetaTrader5`, WebView2, ícone, recursos HTML/CSS/JS, validador externo e gravação em `%USERPROFILE%\ScalperLabData`. Havendo mais de um MT5, exigir seleção explícita do executável e da pasta de dados correspondentes; não depender da escolha implícita de `mt5.initialize()`. Conferir a identidade da conta em cada ação crítica. Como o piloto pede elevação, confirmar que o UAC não mudou o usuário Windows e, com ele, o banco ou terminal vistos pelo aplicativo.
4. **Preparar recuperação:** copiar o banco e `terminals.json` antes do primeiro uso do novo pacote, com o aplicativo fechado; manter o pacote anterior e os backups dos Services. Na abertura, os motores começam parados e exigem nova confirmação UTC.

## Geração

5. Executar o build limpo com Python 3.12 e dependências fixadas em uma pasta de preparação separada, sem sobrescrever o piloto anterior ou um `.exe` em execução. Incluir os dois pares `.mq5/.ex5`, os recursos da interface e o validador. Publicar pasta `dist/ScalperLab`, ZIP, SHA-256 e manifesto somente depois da validação, com data, versões, revisão Git e indicação de alterações locais.
6. Conferir o conteúdo real do ZIP, hashes, tamanho e legibilidade do guia. Uma falha de arquivo obrigatório ou hash interrompe a entrega.

## Validação do pacote pronto

7. **Inicialização em pasta extraída:** abrir `ScalperLab.exe` como administrador no piloto, confirmar uma única janela e ausência de erro de importação ou processo filho duplicando a interface. A aplicação deve abrir sem iniciar automaticamente motores nem enviar ordens.
8. **Conector:** conferir terminal, conta, servidor, modo DEMO/REAL, símbolos exatos do Market Watch, saldo, posições e ordens pendentes. Trocar ou desconectar o MT5 em ensaio controlado e verificar que a interface informa a falha e bloqueia novas entradas.
9. **Services:** em terminal DEMO de teste, instalar na pasta de dados escolhida, atualizar **Navegador → Serviços** e iniciar cada componente uma vez. Verificar `PROGRAM_SERVICE` nos logs, publicação recente, conta e servidor, e leitura no aplicativo. Fechar e abrir o MT5 uma vez e confirmar retomada automática. Calendar indisponível deve aparecer como tal, sem fabricar contexto fundamental; relógio ausente ou vencido deve bloquear novas ordens.
10. **Fluxos locais:** importar `.py` válido e inválido, abrir Configurações, conferir persistência após reiniciar o `.exe` e reproduzir um replay salvo offline. Em DEMO, fazer somente a verificação de ordem estritamente necessária para confirmar o pacote congelado: prévia, envio pequeno com stop/alvo, confirmação no servidor, fechamento e reconciliação. Não executar teste em conta REAL.
11. **Instalação separada:** repetir abertura, conector e instalação dos Services em outra pasta/perfil Windows ou máquina limpa, com MT5 e WebView2 presentes. A validação no computador de desenvolvimento não substitui essa etapa.

## Critérios para liberar o ZIP

- `ScalperLab.exe` e conector congelado iniciam e encerram sem processos órfãos.
- Os dois Services são instaláveis no terminal correto, identificados como `PROGRAM_SERVICE` e retomam após reinício do MT5.
- O relógio é recente, vinculado ao terminal/conta e não depende do calendário; ambos exibem estado real quando indisponíveis.
- Banco e configuração existentes permanecem íntegros; nenhuma operação começa apenas ao abrir o programa.
- A ordem DEMO de validação, se necessária, termina reconciliada e sem posição residual.
- ZIP e manifesto correspondem aos binários testados; SHA-256 publicado junto do pacote.

## Retorno em caso de falha

Se o novo pacote falhar, encerrar o aplicativo, manter os dados originais, reabrir o pacote anterior e restaurar cada Service a partir do backup feito pelo instalador quando houver incompatibilidade. Não alterar conta, risco ou proteções do motor para contornar falha de empacotamento.

## Estado na data deste plano

Já existe um piloto `onedir` em `dist`, gerado em 28/09/2026. Ele contém os dois Services e um ZIP com SHA-256 válido. Os Services foram observados como `PROGRAM_SERVICE` na instalação atual e retomaram após reinício do MT5; o ScalperLab leu relógio recente e confirmou UTC. O piloto existente ainda não passou pela validação de inicialização e conector em uma instalação Windows separada. Este plano orienta o próximo build e sua aceitação; não considera o ZIP anterior uma entrega definitiva.

Em 29/09/2026 a branch ganhou o S/R Quant em pesquisa somente leitura. Um novo build e a validação do item 10 são necessários para afirmar que o `.exe` inclui essa função. O script `build-windows-pilot.ps1` empacota o código Python pela especificação PyInstaller e verifica os dois Services; ele não executa por si só os ensaios operacionais desta lista.
