---
translation:
  sections: [09defc170a0da89d]
  tool: 1
---
# Servidores {#servers}

Um `MCPServer` expõe três primitivas a um cliente conectado. O que as
distingue é quem decide usá-las:

* Uma **[ferramenta](tools.md)** (tool) é uma ação que o *modelo* escolhe e chama. Esta é
  a página que a maioria das pessoas procura primeiro, e
  **[Saída estruturada](structured-output.md)** é a referência que a acompanha:
  tudo sobre o formato do que uma ferramenta retorna.
* Um **[recurso](resources.md)** é um dado somente leitura que a *aplicação*
  escolhe ler. **[Templates de URI](uri-templates.md)** é a referência que o
  acompanha: a sintaxe completa de endereçamento e as regras de segurança de caminhos.
* Um **[prompt](prompts.md)** é um template de mensagem que uma *pessoa* invoca pelo
  nome, a partir de um menu ou de um comando de barra.

Em torno das três primitivas, o restante do que um servidor declara:

* **[Autocompletar](completions.md)** (completions) é o preenchimento automático, feito no
  servidor, dos argumentos de prompts e de templates de recurso.
* **[Imagens, áudio e ícones](media.md)** cobre tudo o que uma ferramenta pode
  retornar além de texto, e os ícones que um cliente mostra ao lado do seu servidor.
* **[Tratamento de erros](handling-errors.md)** explica a diferença entre um
  erro do qual o modelo consegue se recuperar e um que ele nunca deve ver.

Cada página aqui é independente; vá direto para a que você precisa. Se você ainda não
construiu um servidor, comece antes por **[Primeiros passos](../get-started/first-steps.md)**.

O que acontece *dentro* das funções que você registra (o `Context`, a injeção de dependência,
pedir mais informações ao usuário no meio de uma chamada) é o assunto da próxima seção,
**[Dentro do seu handler](../handlers/index.md)**.
