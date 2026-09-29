# Lote e risco em Configurações

## Implementado
- Perfis persistentes para Analista e Estratégias: risco percentual, valor monetário ou lote fixo; teto de lote e reserva da margem livre.
- Limite diário compartilhado pela conta, persistente entre reinícios. Referência desde a primeira leitura registrada, com reconciliação de depósitos e saques.
- Dimensionamento e validação final no backend usando especificações e cálculos do MT5. O lote fixo também respeita o orçamento de risco.
- Prévia sem envio de ordem, com seleção dos símbolos exatos do Market Watch.
- Conteúdo de pesquisa e informações auxiliares recolhidos em uma seção expansível de Configurações. Resumos dos perfis aparecem nos motores.

## Verificação
- 133 testes passaram; sintaxe JavaScript, compilação Python e verificação de diferenças passaram.
- Executável iniciado como administrador. Interface conferida em 1440 e 960 pixels, sem transbordamento horizontal ou erros JavaScript.
- Salvamento do perfil pela interface confirmado, preservando os valores carregados.
- A prévia consultou o backend, mas o cálculo com cotação real ficou impedido por snapshot de relógio MQL5 desatualizado. A interface apresentou a causa; o sucesso desse fluxo com o Service atualizado ainda precisa ser confirmado.
- Nenhuma ordem enviada nesta etapa.

## Limitações
- O replay ainda não reproduz automaticamente estes novos perfis de risco.
- A perda estimada até o stop não garante a perda realizada: execução e custos podem aumentá-la.
- O limite diário impede novas entradas; não encerra posições existentes.
- Preservados os controles de conta, relógio, reconciliação e execução já existentes.
