---
translation:
  sections: [9e7b9a1710e5aeba, b74ca4c1d2ddddee, fa8714e61bf90c5a, 04db67a886b7271c, 857690fb8f876800]
  tool: 1
---
# Dicas de cache {#caching-hints}

Todo resultado que um servidor retorna para `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` e `server/discover` carrega dois campos no protocolo 2026-07-28: `ttlMs`, por quantos milissegundos um cliente pode tratar o resultado como fresco, e `cacheScope`, se um resultado em cache pode ser compartilhado entre usuários (`"public"`) ou pertence a um único contexto de autorização (`"private"`).

O servidor não faz cache de nada. Os campos são uma *declaração*: "esta lista de ferramentas é a mesma para todo mundo e não vai mudar por um minuto." Um cliente (ou um gateway na sua frente) pode então pular a viagem de ida e volta. Respeitar as dicas é escolha do cliente; emiti-las é trabalho do servidor, e o SDK faz isso por você.

Por padrão, todo resultado diz `ttlMs: 0, cacheScope: "private"`: obsoleto imediatamente, nunca compartilhado. Isso é sempre seguro e sempre conforme. Se as suas listas realmente são estáveis e idênticas para todos os chamadores, diga isso na construção:

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* O mapa é indexado pelo **nome do método**, e os seis métodos cacheáveis são as únicas chaves válidas. O parâmetro é tipado como `Mapping[CacheableMethod, CacheHint]`, então o seu editor autocompleta as chaves e aponta um erro de digitação antes de você executar; qualquer coisa que escape do verificador de tipos levanta exceção na construção.
* Um método que você não menciona mantém os padrões. O mapa é um conjunto de sobrescritas, não um manifesto.
* `CacheHint(ttl_ms=5_000)` deixou `scope` sem definir, então ele continua `"private"`: cinco segundos de frescor, por chamador. Escopo e TTL são decisões independentes.
* `"server/discover"` também é uma chave válida, já que o resultado de descoberta é cacheável como qualquer lista.

!!! warning
    `cacheScope: "public"` significa que *qualquer um* pode receber a sua resposta em cache. Um
    gateway compartilhado vai entregar sem hesitar o resultado de um usuário a outro, mesmo quando a
    requisição foi autenticada. Marque um resultado como `"public"` apenas quando ele é idêntico para
    todo chamador, e nunca use `cacheScope` como controle de acesso: é um rótulo, não um cadeado.

## Sobrescrita por handler {#per-handler-override}

No `Server` de baixo nível, os handlers montam seus resultados à mão, e `ttl_ms` / `cache_scope` são apenas campos nos modelos de resultado. Um handler que os define explicitamente sempre vence o mapa do construtor, campo a campo:

```python title="server.py" hl_lines="10 16"
--8<-- "docs_src/caching/tutorial002.py"
```

O handler disse `ttl_ms=1_000` e nada sobre escopo. No fio: `ttlMs: 1000` (o do handler, não o `60_000` do mapa) e `cacheScope: "public"` (o do mapa, porque o handler o deixou sem definir). Explícito vence configurado, e configurado vence o padrão. Isso vale por campo, então um handler pode fixar um campo e deixar o outro para a política do servidor inteiro.

Essa também é a saída de emergência para dinâmicas que o construtor não tem como conhecer: um handler que filtra `resources/read` por usuário pode retornar `cache_scope="private"` para uma URI de um servidor que, de resto, é público.

Uma ressalva sobre listas paginadas: o protocolo exige o **mesmo `cacheScope` em todas as páginas** de uma lista. O mapa do construtor satisfaz isso por construção, já que é indexado por método, não por página. Mas um handler que sobrescreve o escopo assume ele mesmo essa consistência: sobrescreva em *todas* as páginas, nunca apenas quando há um cursor presente, ou a página um e a página dois vão discordar.

## O que o cliente vê {#what-the-client-sees}

Numa sessão 2026-07-28, o `Client` respeita as dicas por você: ele tem um cache de respostas embutido, ligado por padrão. Um resultado que chega carregando um `ttlMs` é armazenado, e uma chamada idêntica dentro desse TTL é servida do cache sem viagem de ida e volta. Um resultado que não carrega *nenhuma* dica não é armazenado: resultados sem dica recebem `CacheConfig.default_ttl_ms`, cujo padrão é `0` (obsoleto imediatamente), então um servidor que não declara nada vê exatamente o mesmo tráfego chamada a chamada de sempre.

```python title="client.py" hl_lines="33 35 38"
--8<-- "docs_src/caching/tutorial003.py"
```

Quatro chamadas, três buscas. A segunda chamada encontrou uma entrada fresca e nunca chegou ao servidor; avançar o relógio (injetado) além do TTL fez a terceira buscar de novo; a quarta disse `cache_mode="refresh"`. Esse argumento nomeado existe nos cinco verbos com cache (`list_tools`, `list_prompts`, `list_resources`, `list_resource_templates`, `read_resource`):

* `"use"` (o padrão) serve uma entrada fresca se houver uma, e armazena a busca se não houver.
* `"refresh"` nunca serve: busca e armazena o resultado, substituindo o que quer que estivesse em cache.
* `"bypass"` faz a viagem de ida e volta sem tocar no cache: sem leitura, sem escrita.

Uma regra fica acima de `"use"`: **chamadas que carregam `meta` sempre chegam ao servidor.** Uma requisição com `meta` definido (um token de progresso, campos de rastreamento) espera uma requisição no fio, então sob `cache_mode="use"` ela é tratada como `"refresh"`: a leitura do cache é pulada, e o resultado buscado ainda substitui a entrada em cache. `"bypass"` e um `"refresh"` explícito se comportam como sempre.

Para desligar o cache por completo, construa com `Client(server, cache=None)`: toda chamada volta a ser uma viagem de ida e volta, e `cache_mode`, embora ainda aceito, não faz nada.

O escopo também é respeitado automaticamente: entradas `"private"` são indexadas pela *partição* do cache (abaixo), enquanto as `"public"` podem optar por um compartilhamento mais amplo. E **notificações vencem o TTL** para as entradas exatas que nomeiam: uma notificação `list_changed` remove a listagem em cache correspondente, e `resources/updated` remove a leitura em cache armazenada sob exatamente a sua URI, por mais frescas que estivessem. Numa conexão 2026-07-28 essas notificações chegam num stream `subscriptions/listen` que você abre com `client.listen(...)`, e a remoção se completa antes de o seu observador ver o evento; **[Assinaturas](subscriptions.md)** é essa página.

Uma ressalva sobre `resources/updated`: a remoção é apenas por URI exata. O contrato do store não tem operação de enumeração nem de varredura (igual à implementação de referência em TypeScript), então uma notificação carregando a URI de um *sub*-recurso não remove a leitura em cache do seu pai. Se o seu servidor sinaliza sub-recursos dessa forma, busque o pai de novo com `cache_mode="refresh"`.

### Configurando: `CacheConfig` {#configuring-it-cacheconfig}

```python
from mcp.client import CacheConfig

client = Client("https://api.example.com/mcp", cache=CacheConfig(default_ttl_ms=5_000))
```

* `store`: onde as entradas vivem. O padrão é um store em memória novo por cliente; passe a sua própria implementação de `ResponseCacheStore` (apoiada em Redis, digamos) para compartilhar um cache entre clientes ou processos. Os tipos do contrato (`ResponseCacheStore`, `CacheKey`, `CacheEntry` e o padrão `InMemoryResponseCacheStore`) são importáveis de `mcp.client`. Uma consulta pode emitir até dois `get`s sequenciais ao store (o braço privado, depois o público), então dimensione as expectativas de latência de um store remoto de acordo. Um store personalizado **exige** uma `partition` explícita.
* `partition`: o rótulo de contexto de autorização que impede que as entradas `"private"` de um principal sejam servidas a outro dentro de um store compartilhado.
* `target_id`: identidade explícita do servidor, para transportes personalizados e servidores no mesmo processo (abaixo).
* `default_ttl_ms`: TTL aplicado a resultados que não carregam dica `ttlMs`. O padrão `0` deixa resultados sem dica fora do cache.
* `share_public`: servir entradas marcadas como `"public"` pelo servidor entre partições (abaixo). Desligado por padrão.
* `clock`: a fonte de relógio de parede, em segundos da época. Injete uma, como o exemplo acima faz, e testes de expiração não precisam dormir.

!!! warning "Partição = principal verificado"
    Derive `partition` de uma **credencial verificada**, como o sujeito de um token validado. Nunca a derive de dados fornecidos pela requisição, e nunca da URL do servidor (a identidade do servidor é um eixo de chave separado). O SDK é uma biblioteca sem autenticação própria: a âncora de confiança é quem constrói o `CacheConfig`, que é o deploy, não o tenant. Um gateway multi-tenant emite um `CacheConfig` por principal autenticado.

    A partição também é fixa pelo tempo de vida do `Client`. Se o contexto de autorização da conexão mudar no meio da sessão (uma reautenticação como um principal diferente, digamos), o cache não acompanha; construa um novo `Client` para o novo principal.

As chaves de cache também carregam a **identidade do servidor**: a string de URL que você discou, com qualquer userinfo `user:pass@` removido e, de resto, exata byte a byte. Sem normalização de maiúsculas, sem reordenação de query, sem limpeza de barra final. Normalizar de menos só custa compartilhamento, enquanto normalizar demais poderia fundir dois tenants (`?tenant=a` versus `?tenant=b`), então URLs superficialmente diferentes simplesmente não compartilham entradas. Quando não há URL (um servidor no mesmo processo, ou uma instância de `Transport`), o cliente recebe uma identidade aleatória por instância; defina `CacheConfig.target_id` para nomear o servidor (com um store personalizado isso é obrigatório, e a construção avisa). A identidade passa por hash sha256 antes de entrar no material da chave, então uma URL carregando segredos na query string nunca aparece nas chaves do store. Também não registre em log a forma pré-hash por conta própria.

!!! warning "`share_public` confia no servidor, para a frota inteira"
    Por padrão, até entradas `"public"` ficam dentro da sua partição. `share_public=True` serve entradas que o servidor marcou como `cacheScope: "public"` a **todas** as partições que usam o store, confiando na classificação do servidor em nome de todas elas. Um servidor que carimba `"public"` em dados por tenant (por bug ou por malícia) então vaza a resposta de um tenant para os outros. A flag é deliberadamente apenas de nível de construtor: o `cache_mode` por chamada pode restringir o cache, mas nada por chamada pode ampliar o compartilhamento.

### O que o cache nunca faz {#what-the-cache-never-does}

* **Chamadas da camada de sessão o contornam.** `client.session.list_tools()` e companhia sempre fazem a viagem de ida e volta; o cache vive nos verbos do `Client`.
* **`server/discover` fica de fora.** O resultado de descoberta é entregue uma vez, na conexão, e nunca entra no cache de respostas, mesmo quando carrega um `ttlMs`. Se você persiste um por conta própria para pular a sondagem de reconexão ([`prior_discover`](../protocol-versions.md#reconnecting-with-prior_discover)), o frescor dele é contabilidade sua: `DiscoverResult` carrega `ttl_ms` e `cache_scope`, já parseados, exatamente para isso.
* **Páginas de continuação nunca são armazenadas.** Apenas chamadas sem cursor participam. Uma página de continuação rejeitada por cursor expirado *remove*, sim, a listagem em cache, porque a listagem mudou por baixo dela.
* **Leituras de múltiplas viagens nunca são armazenadas.** Um `read_resource` semeado com `input_responses`/`request_state`, ou um que se resolve por rodadas de entrada, nunca entra no cache (um MUST da especificação).
* **Remoção por notificação precisa de notificações.** A remoção é tão boa quanto a entrega do transporte, e o caminho moderno no mesmo processo (`Client(server)` com o padrão `mode="auto"`) hoje não entrega notificações avulsas.
* **A remoção é eventual, não instantânea.** Notificações pelo fio são despachadas a partir de tarefas iniciadas em paralelo, então uma chamada correndo contra a chegada de uma notificação pode receber a entrada pré-remoção mais uma vez; a janela é limitada pela latência de despacho, e a remoção ainda acontece.
* **Sem stale-if-error.** Uma entrada expirada nunca é servida porque a nova busca falhou; o erro se propaga.
* **Sem busca antecipada.** Uma entrada armazenada é servida até o TTL expirar, e a próxima chamada depois disso paga a viagem de ida e volta; nada se atualiza em segundo plano.
* **Sem coalescência.** Duas chamadas idênticas concorrentes são duas buscas.
* **Sem TTL acima de 24 horas.** Um `ttlMs` maior, seja enviado pelo servidor ou configurado, é reduzido ao armazenar (`mcp.client.caching.MAX_TTL_MS`), limitando por quanto tempo qualquer entrada, por mais generosa que seja a dica, pode ser servida.
* Num **store compartilhado**, os clientes correm uns contra os outros. Cada cliente descarta a própria escrita quando uma remoção ultrapassou a busca em andamento, mas um cliente *co-tenant* ainda pode escrever de volta uma entrada que uma remoção que ele nunca viu havia removido; e essa contabilidade de corrida é ela própria limitada: acima de 4096 chaves rastreadas, a guarda da chave mais antiga é descartada primeiro. Ambas as janelas são aceitas, e fechadas pelo limite de TTL acima.
* **Sem servir entre eras do protocolo.** As entradas têm escopo na versão de protocolo negociada: num store persistente compartilhado, uma sessão nunca serve uma entrada escrita sob uma versão negociada diferente (a mesma listagem difere de verdade por era, já que o SDK remove os campos de 2026 para sessões mais antigas). A remoção igualmente só toca as entradas da era atual; as entradas de outra era simplesmente envelhecem pelo TTL.

### Lendo as dicas por conta própria {#reading-the-hints-yourself}

As dicas também são campos simples em todo resultado cacheável (`result.ttl_ms` e `result.cache_scope`, já parseados), caso você queira acrescentar a sua própria contabilidade em cima do cache embutido (ou no lugar dele).

Contra um **servidor mais antigo** (protocolo pré-2026), os campos simplesmente não existem no fio, e os modelos mostram seus padrões conservadores: `ttl_ms == 0` e `cache_scope == "private"`, obsoleto e não compartilhado, a suposição certa para um servidor que não declarou nada. O cache trata uma sessão legada do mesmo jeito: as dicas nunca são consultadas ali (quaisquer que sejam as chaves que apareçam no fio), só `default_ttl_ms` se aplica, e seu padrão de `0` não armazena nada, então uma conexão pré-2026 se comporta exatamente como antes de o cache existir. Se você precisa distinguir "o servidor disse 0" de "o servidor não disse nada", verifique `"ttl_ms" in result.model_fields_set`: só é definido quando o campo realmente chegou.

## Clientes mais antigos {#older-clients}

Clientes em versões de protocolo pré-2026 nunca veem nenhum dos dois campos; o SDK os remove na serialização para essas conexões. Configure as suas dicas uma vez; não há nada específico de versão para escrever.

## Recapitulando {#recap}

* Seis métodos carregam `ttlMs`/`cacheScope`; o SDK os define por padrão como `0`/`"private"`, obsoleto e não compartilhado, sempre seguro.
* `cache_hints={method: CacheHint(...)}` na construção (tanto `MCPServer` quanto `Server`) define valores do servidor inteiro por método.
* Um handler que define os campos no seu resultado sobrescreve o mapa, por campo.
* `"public"` é uma promessa de que o resultado é idêntico para todo chamador. Não é controle de acesso.
* O `Client` respeita as dicas automaticamente: seu cache de respostas fica ligado por padrão, serve entradas frescas em vez de buscar de novo, e não armazena nada para servidores (ou sessões) que não fornecem dicas.
* Por chamada, `cache_mode="refresh"` busca de novo e `"bypass"` pula o cache; `cache=None` na construção o desliga por completo.
