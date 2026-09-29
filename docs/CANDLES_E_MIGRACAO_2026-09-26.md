# Candles e armazenamento unificado

**Registro histórico de 26/09/2026.** A regra de conversão de caudas intradiárias recentes continua relevante, mas não comprova o fuso do histórico longo H1/M15/M5 do broker. A pesquisa S/R Quant recusa essa lacuna; veja [estado atual](ESTADO_ATUAL.md).

## Conversão isolada

`bar_time.py` trata somente timestamps de barras. Os controles de Windows/NTP, `normalize_tick_time`, referência MQL5 e renovação do relógio não foram alterados nesta etapa.

A documentação MetaQuotes descreve [histórico em UTC](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py). Na consulta real desta instalação, a barra M1 de BTCUSD# e ETHUSD# coincidiu com o tick bruto do servidor, +10.800 segundos em relação ao tick UTC já validado. Esse comportamento observado exige identificar a codificação do fluxo por símbolo, sem assumir uma regra para todos os brokers.

O conector compara a barra M1 em formação ao tick UTC validado. Se a barra já está em UTC, preserva os timestamps. Se a correspondência é única no horário do servidor, aplica o offset validado apenas a séries M1–M30 contínuas das últimas 24 horas. Preserva `raw_time` e publica a evidência, offset aplicado e contagem de barras recebidas/utilizadas. A barra em formação serve somente à verificação temporal; os indicadores continuam recebendo barras fechadas.

Na análise ao vivo, uma interrupção descarta o trecho anterior à última lacuna. Nenhum candle artificial é criado. As regras analíticas continuam exigindo a quantidade mínima de barras. No replay, não há esse recorte: séries longas, descontínuas ou de períodos maiores no horário do servidor exigem uma regra histórica de fuso. Este mecanismo recente não comprova regras sazonais do broker nem valida historicamente estratégias.

### Evidência real

BTCUSD#, ETHUSD#, Crypto_10# e ETCUSD# retornaram 198 candles M2 válidos de 300 solicitados. Foi identificada uma lacuna de 1.800 segundos; as 102 barras anteriores foram descartadas para a análise ao vivo. USDCHF#, sem tick recente, continuou rejeitado. As quantidades mudam conforme chegam novas barras.

## Migração concluída

Destino único: `%USERPROFILE%\ScalperLabData`. Pode ser alterado explicitamente por `SCALPERLAB_DATA_DIR`, com caminho absoluto, igual em todas as formas de inicialização.

Origem adotada: banco do Python da Microsoft Store, em `AppData/Local/Packages/PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0/LocalCache/Local/ScalperLab`. O diretório `AppData/Local/ScalperLab`, usado pelo piloto anterior, continha apenas diagnóstico e configuração operacional inicial.

Foram preservadas 6 estratégias, 24 fontes, 11 símbolos selecionados, 10 auditorias e a configuração de terminais. O banco foi copiado pela API de backup SQLite, conferido por integridade, relações e hashes de todas as tabelas. Apenas os campos de execução em `engine_runtime` foram explicitamente parados. UTC e armamentos não foram restaurados.

Backups dos dois diretórios anteriores:

`C:\ScalperLab 1.0\backups\storage-migration\20260926T141346Z-fa993460`

Inventários e hashes: `migration-report.json` nessa pasta e no destino. Originais permanecem intactos. Registros exclusivos de diagnóstico do piloto anterior permanecem em seu backup, sem serem mesclados ao histórico principal.

## Verificação do pacote

O novo pacote `dist/ScalperLab-Pilot-onedir.zip` foi gerado em 26/09/2026. SHA256: `8560B7D13C803B8E36C82D8D5AE12761A991B92EF30D994046DD94FBDA510339`.

A bateria completa passou com 123 testes; sintaxe JavaScript, compilação Python e verificação de diferenças também passaram. Os arquivos centrais da correção UTC anterior foram comparados por hash ao backup e permaneceram iguais.

O executável foi iniciado como administrador e carregou 6 estratégias, 24 fontes e 11 ativos do novo diretório. Às 14:19:42 UTC, confirmou o relógio com quatro criptomoedas recentes e ignorou sete ativos sem cotação recente. No ciclo de observação de 14:20:40 UTC, BTCUSD#, ETHUSD#, Crypto_10# e ETCUSD# foram analisados com 203 candles M2 cada, sem erro de candles futuros. Os demais aguardaram cotação recente. Não houve sinal elegível nem envio de ordens. A observação foi parada após a verificação; a aplicação permaneceu aberta.

## Procedimento de reversão

1. Fechar todas as instâncias e confirmar que nenhum motor está executando.
2. Fazer uma nova cópia do destino para preservar atividade posterior à migração.
3. Para reverter somente o armazenamento, apontar `SCALPERLAB_DATA_DIR` para uma cópia verificada do backup escolhido; nunca abrir duas instâncias com bancos diferentes na mesma conta.
4. Para reverter o código desta etapa, a cópia anterior está em `C:\ScalperLab 1.0\backups\before-candles-migration-20260926-110907.zip`. Ela inclui a correção UTC anterior. Restaurar somente após comparar eventuais alterações posteriores.
5. Confirmar cadastros e horário novamente antes de iniciar qualquer execução.
