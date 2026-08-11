---
translation:
  sections: [424930166c4bc6f3]
  tool: 1
---
# Dentro do seu handler {#inside-your-handler}

Os argumentos de um handler vêm do cliente. Todo o *resto* que ele pode ler, e
tudo o que ele pode fazer enquanto executa, está aqui.

O que ele pode ler:

* **[O Context](context.md)** é o único parâmetro extra que qualquer handler
  pode pedir: a requisição em andamento, seus cabeçalhos, sua sessão e os
  verbos de progresso e de notificação de mudanças.
* **[Dependências](dependencies.md)** são parâmetros que o modelo nunca vê,
  preenchidos pelas suas próprias funções com `Resolve`.
* **[Lifespan](lifespan.md)** trata do estado que seu servidor monta uma única
  vez na inicialização e de como um handler chega até ele por meio do
  `Context`.

O que ele pode fazer enquanto executa:

* Pedir mais informações ao usuário com **[Elicitação](elicitation.md)**
  (elicitation) e com **[Requisições de múltiplas idas e voltas](multi-round-trip.md)**,
  o padrão de 2026-07-28 que a transporta.
* Pedir ao cliente uma completion de LLM ou as pastas do seu workspace com
  **[Amostragem (sampling) e roots](sampling-and-roots.md)**, obsoletos, mas
  ainda atendidos.
* Informar o **[Progresso](progress.md)** de algo demorado.
* Escrever logs (na saída de erro padrão, para quem opera o servidor) com
  **[Logging](logging.md)**.
* Avisar os clientes assinantes de que algo mudou com
  **[Assinaturas](subscriptions.md)**.

Se você ainda não registrou um handler, comece por
**[Ferramentas](../servers/tools.md)**. Todas as páginas aqui pressupõem que
você já tem um.
