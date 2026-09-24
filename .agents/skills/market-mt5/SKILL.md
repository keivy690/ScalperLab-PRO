---
name: market-mt5
description: Desenvolva regras e integrações de estratégia para MetaTrader 5/MQL5, verificando especificações do terminal e da corretora. Use para sinais, posições, ordens e revisão de EAs; não use para recomendar ativos ou prometer resultados.
---

# Mercado financeiro e programação MT5

- Separe interpretação de mercado, hipótese de estratégia, validação histórica e decisão operacional. Registre os dados e custos que sustentam uma conclusão.
- Para integração, confira a documentação MetaQuotes e as propriedades do símbolo, conta, volume, stops, filling e tipo de margem no terminal conectado; não generalize regras entre corretoras.
- Distinga validação pré-envio, resposta da ordem, negócio e posição reconciliada. Timeout ou estado parcial é ambíguo: consulte posições e histórico antes de nova ação.
- Considere contas netting e hedging, execução parcial e múltiplos eventos de transação. Identifique ordens e negócios para permitir auditoria.
- Trate operações reais como bloqueadas até existir homologação explícita e critérios verificáveis. Não interprete uma estratégia aprovada como autorização para operar.
- Referência primária: https://www.mql5.com/en/docs/python_metatrader5
