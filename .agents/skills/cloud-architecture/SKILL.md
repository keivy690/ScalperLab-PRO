---
name: cloud-architecture
description: Avalie fronteiras locais e remotas, responsabilidades de serviços e requisitos de disponibilidade/custo para sistemas que podem evoluir para nuvem. Use em decisões de arquitetura híbrida ou cloud.
---

# Arquitetura de soluções em nuvem

- Comece pelos requisitos de dados, latência, disponibilidade, recuperação, privacidade e custo; justifique cada dependência remota.
- Preserve operação local como padrão do ScalperLab. Um serviço em nuvem não deve se tornar uma ponte de execução financeira sem decisão explícita do usuário.
- Defina contratos, autenticação, propriedade de dados, retenção e comportamento quando a rede ou o serviço externo estiver indisponível.
- Separe plano de controle, busca/IA e conector MT5; não exponha o terminal nem uma API local à internet.
- Compare pelo menos a opção local e uma alternativa gerenciada quando os requisitos realmente justificarem nuvem.
