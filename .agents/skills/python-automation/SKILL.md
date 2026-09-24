---
name: python-automation
description: Implemente automações Python desktop e conectores locais com estados observáveis e falhas recuperáveis. Use em coleta, tarefas agendadas e integração com serviços ou o terminal MT5.
---

# Automações Python

- Inspecione contratos entre interface, serviço, persistência e terminal antes de acrescentar um fluxo.
- Use timeouts, limites de tamanho, validação de esquema e erros que expliquem se o resultado está indisponível, parcial ou confirmado.
- Mantenha tarefas longas fora da thread da interface e impeça atualizações concorrentes conflitantes.
- Nunca execute código importado no processo principal. Análise estática e execução são capacidades distintas; processo filho comum não deve ser tratado como sandbox completa.
- Evite persistir senhas e tokens. Leia segredos de mecanismos apropriados do ambiente e nunca os exponha em logs ou respostas.
- Em ações externas, use identificadores de correlação e não repita automaticamente um envio de resultado desconhecido.
