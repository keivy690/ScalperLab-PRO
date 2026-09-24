---
name: information-security
description: Revise e implemente controles de segurança para APIs locais, fontes remotas, segredos e arquivos de estratégia no ScalperLab.
---

# Segurança da informação

- Mapeie ativos, fronteiras de confiança, entradas e efeitos privilegiados. Verifique host/origin, CSRF, token local, CSP e binding somente em loopback.
- Trate busca por URL como risco SSRF: permita HTTPS público, valide redirects e endereço efetivo de conexão, limite bytes, tempo e tipo de resposta.
- Valide extensão, tamanho e conteúdo de arquivos; não execute nem compile entradas não confiáveis no processo principal.
- Minimize segredos e identificadores em logs, banco e respostas. Uma chave mascarada continua sensível se uma API a devolver.
- Em ações financeiras com erro ou timeout ambíguo, conserve trilha e bloqueie repetição automática até reconciliar o estado.
- Relate o alcance real dos controles. Teste localmente não é certificação de segurança.
