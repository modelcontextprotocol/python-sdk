---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# Amostragem e roots {#sampling-and-roots}

Um handler pode pedir mais duas coisas ao cliente conectado: uma completion do próprio modelo do cliente (**amostragem**, sampling), e as pastas de workspace do cliente (**roots**).

As duas continuam funcionando, em todas as versões do protocolo que o SDK fala. Mas leia o aviso antes de projetar algo em cima delas:

!!! warning "Descontinuado pela especificação 2026-07-28"
    Amostragem e roots estão descontinuados a partir de `2026-07-28` ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)). Eles continuam totalmente funcionais e permanecem na especificação por pelo menos doze meses antes de se tornarem elegíveis para remoção, mas novas implementações não devem se apoiar neles. As migrações sugeridas: integre diretamente com a API do seu provedor de LLM em vez de usar amostragem, e passe diretórios via parâmetros de ferramenta, URIs de recurso ou configuração do servidor em vez de roots. A lista de todo o SDK está em **[Funcionalidades descontinuadas](../deprecated.md)**.

## Amostragem: pegue emprestado o modelo do cliente {#sampling-borrow-the-clients-model}

Um resolvedor retorna `Sample(...)` e a ferramenta recebe a completion, pelo mesmo mecanismo de dependência que executa `Elicit` em **[Dependências](dependencies.md)**:

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)` espelha os parâmetros de `sampling/createMessage`. O valor injetado é o `CreateMessageResult` do cliente; passe `tools` ou `tool_choice` e ele vira um `CreateMessageResultWithTools`.
* O cliente precisa ter declarado a capacidade `sampling` (`sampling.tools` se você passar `tools` ou `tool_choice`). Se não declarou, a chamada falha com um erro de protocolo `-32021` em vez de enviar uma requisição que o cliente não consegue tratar. Uma sessão pré-2026 sem canal de retorno (back-channel) falha com o erro habitual de ausência de canal de retorno, já que não há por onde enviar.
* Em `2026-07-28` a requisição é entregue dentro do fluxo de múltiplas idas e voltas (**[Requisições com múltiplas idas e voltas](multi-round-trip.md)**); em `2025-11-25` ela é uma requisição independente para o cliente. O código é o mesmo nos dois casos, mas atenção à regra das múltiplas idas e voltas: a requisição precisa ser gerada de forma idêntica em todas as rodadas de retry, então construa-a apenas a partir dos argumentos da ferramenta e de outros dados estáveis.
* Deixe `include_context` quieto: valores diferentes de `"none"` também estão descontinuados (SEP-2596) e exigem uma capacidade que quase nenhum cliente declara.

## Roots: onde isso deve ir? {#roots-where-should-this-go}

Roots são as pastas sobre as quais o cliente diz que o servidor pode operar. São uma orientação informativa, não um mecanismo de controle de acesso. Um resolvedor retorna `ListRoots()`:

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* O `ListRootsResult` injetado traz uma lista de `Root`s: uma URI `file://` e um nome de exibição opcional.
* A barreira é a mesma da amostragem: sem uma capacidade `roots` declarada, a chamada falha com `-32021` em vez de enviar a requisição.

Do outro lado da conexão, o cliente responde às duas requisições com os callbacks que já tem: `sampling_callback` e `list_roots_callback`, tratados em **[Callbacks do cliente](../client/callbacks.md)**.

## Em conexões da era 2025 {#on-2025-era-connections}

`ctx.session.create_message(...)` e `ctx.session.list_roots()` ainda existem para código que controla a sessão diretamente. Eles só funcionam onde existe um canal de retorno (conexões da era 2025, não stateless), e chamá-los dispara um aviso de descontinuação. Os marcadores de resolvedor acima são a forma suportada: eles escolhem a entrega conforme a versão negociada e não emitem aviso.

## Recapitulando {#recap}

* Retorne `Sample(...)` ou `ListRoots()` de um resolvedor; a ferramenta recebe o `CreateMessageResult` ou o `ListRootsResult` como qualquer outra dependência.
* O cliente precisa declarar a capacidade correspondente, ou a chamada falha com `-32021` em vez de uma requisição ser enviada.
* As duas funcionalidades estão descontinuadas em `2026-07-28`: totalmente funcionais por enquanto, erradas para novos projetos. Prefira APIs de provedor à amostragem e parâmetros explícitos aos roots.

Para informar o andamento de uma ferramenta lenta: **[Progresso](progress.md)**.
