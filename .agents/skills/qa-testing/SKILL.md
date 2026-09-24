---
name: qa-testing
description: Valide fluxos desktop, conectores e controles por risco, incluindo falhas e reconciliação. Use para regressão, homologação demo e avaliação de prontidão.
---

# QA e testes

- Priorize consequências. Cubra interface, API, persistência, reinício e conexão real apenas quando autorizada.
- Use fakes para conta demo, ordens rejeitadas, timeout, preenchimento parcial e mudança de identidade; nunca valide controles enviando ordens reais.
- Teste entradas malformadas, arquivo grande, script com efeitos laterais, URL local/redirecionada, fonte indisponível e ausência de segredo.
- Separe validação estática, teste unitário, integração simulada, integração MT5 demo e verificação visual.
- Homologação exige critérios mensuráveis e evidência real. Testes aprovados não provam rentabilidade nem funcionamento em todas as corretoras.
