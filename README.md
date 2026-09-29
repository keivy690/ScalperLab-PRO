# ScalperLab PRO

Aplicativo desktop Windows para pesquisar estratégias, acompanhar o MetaTrader 5 (MT5), analisar o mercado e executar regras experimentais sob controles de conta e risco. **Documentação revisada em 29/09/2026 para a branch `feature/sr-quant-engine`.** A implementação na branch não significa que o executável piloto já tenha sido reconstruído.

## Começar

1. Abra o terminal MT5 e confira conta, servidor e cotações.
2. Em `C:\ScalperLab 1.0`, execute `Iniciar-ScalperLab.bat`. Na primeira abertura, ele prepara Python 3.12 e as dependências fixadas.
3. Confira no cabeçalho do aplicativo a conta e o servidor efetivamente conectados.
4. Consulte o [manual de instalação e uso](docs/MANUAL_INSTALACAO_E_USO.md) antes de iniciar qualquer modo de envio.

Alternativa pelo PowerShell, com Python 3.12 instalado:

```powershell
Set-Location 'C:\ScalperLab 1.0'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe run.py
```

O conector de mercado e ordens usa a biblioteca Python `MetaTrader5` e o terminal local. `ScalperLabClockService` e `ScalperLabCalendarService` são serviços MQL5 **somente de leitura**, instalados separadamente no MT5 para relógio e calendário; nenhum deles envia ordens. O banco fica em `%USERPROFILE%\ScalperLabData\scalperlab.sqlite3`, fora do código e do pacote.

## O que está disponível

- **Analista de mercado:** regra experimental técnica e quantitativa de pullback na SMA 21. Observação não envia ordens; DEMO e REAL têm caminhos de envio condicionados a confirmação e preflight. Disponibilidade técnica de REAL não é homologação.
- **Estratégias cadastradas:** cinco adaptações declarativas executáveis; arquivos `.mq5`, `.py` e `.txt` importados são material de revisão e não são executados automaticamente.
- **Pesquisa S/R Quant:** três famílias de hipóteses em H1/M15/M5, avaliação persistida e replay cronológico, sempre `research_only` e **sem caminho de ordens**. No MT5 XMGlobal consultado em 29/09/2026, o histórico ainda não tinha a base UTC verificada; pesquisa e replay reais ficaram bloqueados por qualidade temporal.
- **Pesquisa pública e IA opcional:** GitHub e feeds; Brave, YouTube e resumo via OpenAI dependem de chaves de ambiente. O calendário MT5 é contexto parcial; notícias e séries macro estruturadas não estão integradas ao gatilho atual.
- **Risco:** perfis separados de Analista e Estratégias para dimensionamento por percentual, valor ou lote fixo com teto, reserva de margem e limite diário compartilhado. O teste de integração DEMO permanece limitado a 0,01 lote.

O aplicativo inicia com motores parados. Uma tela indicando “DEMO ativo” informa armamento, não ordem executada. Só a reconciliação com o MT5 confirma uma posição. Nenhuma regra atual tem vantagem estatística demonstrada nesta instalação.

## Documentação

| Documento | Finalidade |
| --- | --- |
| [Estado atual e pendências](docs/ESTADO_ATUAL.md) | Referência de capacidade, evidência e lacunas por módulo |
| [Manual de instalação e uso](docs/MANUAL_INSTALACAO_E_USO.md) | Instalação, MT5, Services, telas, risco, replay, recuperação |
| [Arquitetura](docs/ARCHITECTURE.md) | Componentes, contratos, dados, tempo e execução |
| [Referência técnica](docs/REFERENCIA_TECNICA.md) | Rotas locais, armazenamento, Services e diagnóstico |
| [Segurança e limites](docs/SAFETY_AND_LIMITS.md) | Condições de envio, suspensão e limitações |
| [Pacote piloto Windows](docs/BUILD_WINDOWS_PILOT.md) | Conteúdo do `onedir`, início e aceitação do pacote |
| [Pesquisa S/R Quant](docs/IMPLEMENTACAO_SR_QUANT_2026-09-29.md) | Entrega e critérios antes de considerar promoção a DEMO |

Os demais arquivos em `docs/` são especificações, planos e relatórios datados. Leia seu estado no início de cada arquivo; eles preservam a decisão e a evidência da época, enquanto [Estado atual e pendências](docs/ESTADO_ATUAL.md) orienta o uso da branch.

## Estrutura

- `scalperlab/`: backend, conector, motores, pesquisa, armazenamento e controles.
- `templates/` e `static/`: interface local.
- `MT5/` e `tools/`: fontes dos Services e ferramenta assistida para instalá-los.
- `.agents/skills/`: nove especialidades do projeto.
- `tests/`: verificações automatizadas do repositório.

O pacote Windows pode ser gerado por `build-windows-pilot.ps1` com dependências de desenvolvimento instaladas. Antes de distribuí-lo, confira o manifesto e valide o novo executável em uma instalação Windows separada. O [plano de empacotamento](docs/PLANO_PACOTE_EXECUTAVEL.md) registra os critérios ainda pendentes.
