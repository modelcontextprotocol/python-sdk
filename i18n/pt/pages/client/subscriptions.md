---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# Assinaturas {#subscriptions}

O catálogo de um servidor não é fixo. Ferramentas (tools) aparecem em tempo de execução, e o conteúdo por trás da URI de um recurso muda. Um cliente fica sabendo disso por meio de `client.listen(...)`: uma única requisição `subscriptions/listen` cuja resposta *é* o stream. Ele fica aberto e carrega as notificações de mudança que o cliente pediu.

Esta página é a ponta do cliente: abrir o stream, observá-lo ao lado do seu fluxo principal e lidar com seus encerramentos. Publicar mudanças, filtrar e servir o método são o lado do servidor dessa história, contado em **[Assinaturas](../handlers/subscriptions.md)**, em *Dentro do seu handler*. Os exemplos aqui conversam com o servidor de quadro de sprint construído lá.

## Observando o stream {#watching-the-stream}

Uma assinatura é um único gerenciador de contexto. Entrar nele envia a requisição, com seus argumentos nomeados como filtro da assinatura, e espera a confirmação do servidor, então o stream já está ativo quando o bloco começa.

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

A iteração produz quatro eventos tipados: `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged` e `ResourceUpdated(uri=...)`.

Um evento diz *o que* mudou, nunca *como*. É por isso que `follow_board` chama `read_resource` e `list_tools`: o evento é uma deixa para buscar de novo. Leia `event.uri` em vez de presumir qual recurso mudou: um filtro pode nomear várias URIs, e um servidor pode reportar uma mudança em um sub-recurso de uma delas.

Eventos duplicados esperando para serem consumidos se fundem em um só, e buscar de novo ainda traz o estado atual para você. Só eventos idênticos se fundem: dois `ResourceUpdated` para URIs diferentes são dois eventos.

Mais duas propriedades do handle:

* `sub.honored` é o filtro que o servidor confirmou: um `SubscriptionFilter` com os campos que você passou, lidos como atributos (`sub.honored.prompts_list_changed`). O `MCPServer` honra todo tipo que você pede, então ele devolve sua requisição como eco. Um servidor que suporta menos tipos confirma menos, e um tipo honrado ainda pode nunca disparar. Um servidor também pode recusar a requisição inteira em vez de confirmá-la (veja [Decidindo quem pode observar](../handlers/subscriptions.md#deciding-who-may-watch) na página do servidor), o que aparece como o erro da requisição.
* `sub.subscription_id` é o id da requisição listen, aquele carimbado em cada frame deste stream. Várias assinaturas podem estar abertas ao mesmo tempo, cada uma demultiplexada pelo seu próprio id.

## Observando sem bloquear {#watching-without-blocking}

`follow_board` roda até o servidor fechar o stream, o que pode ser nunca, então sozinha ela toma conta do seu programa. Clientes reais querem o observador *ao lado* do fluxo principal: um agente chama ferramentas enquanto um observador mantém um cache ou uma UI atualizados.

Abra a assinatura primeiro, depois inicie o observador e siga com o seu trabalho.

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py` importa `BOARD` e `read_board` do primeiro exemplo, que este repositório guarda como
    `tutorial003.py`. Se você salvar os arquivos renderizados lado a lado como `client.py` e `app.py`,
    escreva `from client import BOARD, read_board` no lugar. O exemplo `watch.py` mais abaixo
    importa `read_board` do mesmo jeito.

A ordem é o ponto. Nada é reenviado, então um evento publicado antes de o seu stream existir se perde. Entrar em `client.listen(...)` espera a confirmação, então toda mudança daquele momento em diante chega ao seu observador, e o snapshot que você tira dentro do bloco não tem como perder nenhuma.

Requisições rodam livremente ao lado de um stream aberto, a partir da tarefa do observador ou de qualquer outra, no mesmo cliente. Como eventos *duplicados* não consumidos se fundem, um fluxo principal movimentado pode produzir uma nova busca em vez de três. Eventos diferentes não se fundem: um filtro que nomeia muitas URIs enfileira um evento pendente por URI.

Para parar de observar, saia do bloco: não existe chamada `unsubscribe`. Cancelar a tarefa que é dona do bloco faz isso por você, e o SDK cancela a requisição listen do jeito que o transporte espera: sobre Streamable HTTP, fechando o stream daquela requisição. Um observador que roda durante toda a vida do seu app nunca retorna sozinho, então cancele-o, ou o escopo do seu task group, no encerramento.

## Streams terminam {#streams-end}

Um stream termina de uma de duas maneiras, ambas fluxo de controle comum. Um fechamento gracioso do servidor encerra o `async for`; uma queda abrupta levanta `SubscriptionLost`.

A diferença é de diagnóstico, não uma diferença no que fazer a seguir: o stream se foi, nada foi reenviado, e um observador que ainda se importa escuta de novo e busca de novo.

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

Servidores fecham streams graciosamente por razões próprias, inclusive para se livrar de um assinante cujo backlog cresceu demais, então um fim limpo não é sinal para parar de observar. Espere um pouco (back off) antes de escutar de novo.

`SubscriptionLost` também tem uma causa local. O cliente guarda no máximo 1024 eventos não consumidos, e um consumidor que fica tão para trás assim perde a assinatura em vez de crescer sem limite. Mantenha o corpo do `async for` curto e faça o trabalho lento em outro lugar.

`keep_following` captura apenas `SubscriptionLost`. Entrar em `listen()` também pode levantar `MCPError` (a conexão falhou, ou o servidor não serve o método), `TimeoutError` (nenhuma confirmação chegou) e `ListenNotSupportedError` (uma conexão pré-2026). Decida quais desses o seu observador deve tentar de novo: o último nunca se resolve.

## Recapitulando {#recap}

* Entre em `async with client.listen(...)`; a entrada espera a confirmação, então nada publicado depois dela se perde.
* Itere com `async for event in sub`. Eventos são deixas para buscar de novo, nunca payloads.
* Abra a assinatura, depois rode o observador como uma tarefa, e as chamadas de ferramentas continuam fluindo ao lado dele.
* Um fim limpo para o loop; uma queda levanta `SubscriptionLost`. De qualquer forma: escute de novo, busque de novo, espere um pouco antes.
* Sair do bloco é o unsubscribe.

Publicar esses eventos, estreitar o filtro e escalar além de um processo são a história do servidor: **[Assinaturas](../handlers/subscriptions.md)**. Esses mesmos eventos também mantêm um cache do lado do cliente honesto, e **[Cache](caching.md)** é a próxima página.
