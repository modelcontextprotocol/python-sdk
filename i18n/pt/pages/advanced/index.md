---
translation:
  sections: [ca6988b7503cd2d3]
  tool: 1
---
# Avançado {#advanced}

Tudo o que um servidor ou cliente comum precisa tem seu lugar por assunto nas seções acima.
Esta seção reúne as saídas de emergência a que você recorre quando a camada de conveniência
do `MCPServer` atrapalha:

* **[O Server de baixo nível](low-level-server.md)**: a classe sobre a qual o `MCPServer` é construído.
  Schemas escritos à mão, handlers `on_*`, nada verificado para você e métodos JSON-RPC
  personalizados criados por você.
* **[Paginação](pagination.md)** e **[Middleware](middleware.md)**: duas coisas que você
  *só* consegue fazer no `Server` de baixo nível.
* **[Extensões](extensions.md)** e **[MCP Apps](apps.md)**: a superfície de
  extensão do protocolo. Componha pacotes de extensão em um servidor ou escreva os seus.

Algumas coisas que você poderia, com razão, procurar aqui ficam onde você de fato
as usaria:

* **Autorização** está em **[Executando seu servidor](../run/index.md)**, porque você
  protege um servidor onde faz o deploy dele.
* **OAuth**, **asserção de identidade**, conexão a **vários servidores** e o
  **cache** de respostas estão todos em **[Clientes](../client/index.md)**.
* **Requisições com várias idas e voltas** e **Assinaturas** estão em
  **[Dentro do seu handler](../handlers/index.md)**, porque ambas são coisas que um
  handler *faz*.
* **Templates de URI** está em **[Servidores](../servers/index.md)**, ao lado de Recursos.
* **[Versões do protocolo](../protocol-versions.md)** e
  **[Funcionalidades descontinuadas](../deprecated.md)** têm, cada uma, sua própria página de nível superior.

Se você não tem certeza de que precisa desta seção, não precisa.
