# Referência técnica e de manutenção

**Código consultado:** branch `feature/sr-quant-engine`, 29/09/2026. A interface usa estas rotas locais; não são uma API pública de rede. Para fluxo de usuário, consulte o [manual](MANUAL_INSTALACAO_E_USO.md); para estado de validação, [ESTADO_ATUAL.md](ESTADO_ATUAL.md).

## Execução e fronteiras

- `run.py` inicia `scalperlab.desktop`; pywebview abre a interface. O serviço Flask escuta em `127.0.0.1`, porta dinâmica, com token por processo, verificação de host/origin e CSP. Não publique essa porta na rede.
- `web.py` compõe backend, motores, pesquisa, risco e relógio. `TradingPort` é a fronteira dos motores; `MT5Gateway`/conector worker isolam o SDK `MetaTrader5` e as chamadas ao terminal. Símbolos enviados conservam o nome exato do broker, inclusive sufixo.
- `ClockService` e `CalendarService` são programas MQL5 `#property service`, instalados em `MQL5\Services` do terminal escolhido. O primeiro publica relógio atual; o segundo publica agenda econômica. Ambos apenas escrevem snapshots para leitura pelo Python.
- O armazenamento padrão é `%USERPROFILE%\ScalperLabData`; `SCALPERLAB_DATA_DIR` aceita um caminho **absoluto** alternativo. O banco é `scalperlab.sqlite3`. Alterar o diretório sem migrar dados cria uma instalação lógica separada.

## Rotas locais principais

| Grupo | Rotas | Uso |
| --- | --- | --- |
| Estado | `GET /api/state`, `GET /api/mt5/market-watch`, `GET /api/logs` | Conta/terminal, motores, relógio, posições, símbolos e registro |
| Risco | `GET/POST /api/settings/risk`, `POST /api/settings/risk/preview` | Perfil persistido e prévia sem envio; salvar exige motores parados |
| Relógio | `POST /api/system/clock/synchronize` | Leitura ou sincronização manual conforme parâmetro; mutação de horário é recusada durante execução |
| Analista SMA21 | `GET/POST /api/analyst/profile`; `POST /api/analyst/start`, `/api/analyst/stop`, `/api/analyst/replay`, `/api/analyst/replay-saved` | Perfil, modos e replay próprio |
| Estratégias | `GET/POST /api/engine/profile`; `POST /api/engine/start`, `/api/engine/stop`; `/api/strategies` | Motor declarativo e catálogo revisado |
| S/R Quant | `POST /api/sr-quant/start`, `/api/sr-quant/stop`, `/api/sr-quant/replay`, `/api/sr-quant/replay-saved`, `/api/sr-quant/time-sample`; `GET /api/sr-quant/evaluations`, `/api/sr-quant/data-events`, `/api/sr-quant/replays` | Pesquisa, replay e coleta bruta somente leitura; nenhuma rota de envio. A amostra requer motores parados e não libera conversão histórica sem evidência |
| Ordens e auditoria | `GET /api/orders`, `GET /api/trading/audit`, `POST /api/trading/audit/reconcile`, rotas de armamento/fechamento | Estado real, tentativas e reconciliação; consulta de auditoria não reenvia ordens |
| Fontes | `/api/research/search`, `/import-url`, `/feeds`, `/summarize` | Coleta e resumo opcional de material público |

Os caminhos de início/ordens são protegidos por token de sessão e confirmações específicas; chamados externos não devem contornar a interface. Respostas de erro ou timeout de `order_send` não autorizam repetição automática: confira posições, ordens e histórico no MT5.

## Dados e tabelas relevantes

- `risk_settings` guarda versão e perfis separados; `risk_days` guarda referência e bloqueio diário por hash de conta e dia UTC. O início da referência é a primeira leitura verificada do dia, não uma estimativa da meia-noite.
- O catálogo de estratégias, pesquisa, logs e auditoria de ordens ficam no SQLite local. Arquivos importados são texto de revisão, não módulos executáveis.
- `sr_evaluations` guarda avaliações causais por conta/símbolo/versão/candle; `sr_data_events` preserva falhas de qualidade; `sr_replay_runs` guarda o dataset, parâmetros, resultado e hash para reprodução offline. A pesquisa S/R não cria ordens.
- Backups consistentes usam `python -m scalperlab.database_backup`; restauração exige o aplicativo fechado e confirmação textual. Guarde também os arquivos de configuração de terminal quando migrar entre instalações.

## Quando há dados insuficientes

- **Relógio operacional:** precisa de Windows Time/NTP mensurável, snapshot recente do ClockService da conta/terminal corrente e tick recente de símbolo selecionado. A renovação em segundo plano não rearma motores.
- **Candles para S/R:** H1/M15/M5 fechados e com base UTC histórica comprovada. O offset publicado hoje pelo ClockService não autoriza converter toda a série; transição sazonal pode produzir erro. A resposta correta é `DADOS_INSUFICIENTES`.
- **Calendário:** falha ou ausência de eventos deve ser apresentada conforme estado da fonte, sem fabricar sinal fundamental. Notícias e macro externas ainda não entram na decisão.
- **Risco/envio:** identidade de conta, preço, contrato, volume, limite diário, margem, SL/TP, ordem pendente/posição e `order_check` são conferidos novamente perto do envio. Resultado aceito sem posição correlacionada é pendente, não execução confirmada.

## Empacotamento

`build-windows-pilot.ps1` usa `ScalperLab.spec` e verifica aplicativo, validador externo, recursos de interface e os dois pares MQL5. O conector Python está dentro do aplicativo e usa o mesmo executável no worker congelado; não se gera um `conector.exe`. O script copia `Instalar-Servico-Calendario-MT5.bat/.ps1` (nome histórico, instala os dois Services), gera `BUILD-MANIFEST.json`, ZIP e SHA-256. O MT5 e o WebView2 continuam pré-requisitos da máquina.

O build deve ser feito após fechar uma revisão e repetido em instalação Windows separada. O manifesto permite conferir qual commit foi empacotado; um pacote piloto de data anterior não recebe automaticamente novos módulos ou migrações.
