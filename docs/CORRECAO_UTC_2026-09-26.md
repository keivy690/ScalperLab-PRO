# Correção de divergência UTC entre ativos

## Causa e mudança

O código anterior arredondava a diferença entre o último tick e o Windows para deduzir o fuso. Uma cotação antiga por um múltiplo de 15 minutos podia aparentar outro fuso e tornar-se falsamente recente. Isso provocava divergências entre ativos de mercados fechados e criptomoedas com negociação recente.

A conversão agora exige referência independente do Service MQL5. O leitor valida conta/servidor, idade de até 300 segundos, offset inteiro até 14 horas e coerência entre captura e relógio do servidor. Aceita no máximo cinco segundos de diferença do offset publicado para o múltiplo de 15 minutos, pois as leituras MQL5 são sequenciais. Valores fora dessa tolerância são rejeitados. Não há fallback para deduzir fuso pelo último preço.

O arquivo legado identifica conta/servidor e é compartilhado em Common/Files: não comprova uma instalação exclusiva. O gateway corrobora a referência com cotação do terminal conectado e confere identidade antes/depois da leitura. Se a ponte publicar terminal_data_path, o leitor exige correspondência. Múltiplos Services simultâneos publicando para o mesmo arquivo continuam sendo uma limitação da ponte: divergência de identidade é rejeitada.

Cada ativo informa timestamp bruto, offset, idade e motivo da aceitação/rejeição na API e em registros DEBUG compactos. Cotações com mais de 120 segundos são ignoradas na confirmação global; sem cotações recentes, a mensagem informa indisponibilidade de preços. Validação Windows/NTP e limites existentes continuam necessários. A renovação do relógio não inicia motores ou envia ordens.

## Evidência

- 110 testes automatizados aprovados, incluindo 39 da bateria focada em tempo, ponte e API.
- Regressões cobrem cotações antigas de 900, 10.800, 46.800 e 86.400 segundos; mistura de ativos atuais e antigos; ausência de ticks recentes; snapshot ausente, expirado, futuro, inválido e de outra conta; mudança de offset sazonal.
- Leitura do terminal XM em 2026-09-26: Service recente, offset +10.800 segundos; BTCUSD#, ETHUSD#, Crypto_10# e ETCUSD# aceitos; outros sete ativos selecionados rejeitados como cotações antigas. Nenhuma divergência de offset.
- Windows Time ativo e automático, medição NTP de -0,505 segundo nesta consulta.
- Nenhuma ordem enviada por esta validação. Histórico de candles mantém sua regra própria de UTC; este ajuste não aplica o offset atual indiscriminadamente ao histórico.
- Instância desktop iniciada como administrador: API de sincronização retornou HTTP 200, status synchronized, 11 diagnósticos por ativo e desvio NTP de -0,400 segundo. Os seis cadastros de estratégias e os 11 ativos permaneceram disponíveis.

## Limitações encontradas na implantação

- O pacote onedir foi reconstruído. A primeira execução revelou ausência de NumPy, dependência carregada pela extensão nativa MetaTrader5. A especificação passou a incluí-la explicitamente; após novo build o executável conectou ao MT5.
- Python da Microsoft Store usa armazenamento redirecionado em `AppData/Local/Packages/PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0/LocalCache/Local/ScalperLab`. O executável usa `AppData/Local/ScalperLab`. Não foi feita migração desses dados; a instância com cadastros foi reaberta pelo Python existente. Antes de trocar definitivamente para o executável, preparar backup e migração do banco e da configuração de terminais.
- A consulta real de candles M2 de BTCUSD# ainda retornou "Histórico MT5 permanece no futuro após a normalização UTC". É uma pendência distinta da referência de relógio e exige validar a base temporal dos candles, inclusive mudanças sazonais, antes de converter histórico. A aprovação da verificação UTC não resolve essa pendência nem comprova envio de ordens.

## Uso

Manter ScalperLabCalendarService em execução no MT5 da conta utilizada. Após carregar esta versão, usar Verificar horário UTC. Se só houver ativos sem cotações recentes, aguardar atualização de mercado ou selecionar ativos que estejam recebendo preços. Iniciar o motor continua sendo ação explícita.
