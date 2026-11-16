---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# Parâmetros de cabeçalho {#header-parameters}

A maioria dos servidores nunca precisa disso.

Um gateway ou balanceador de carga na frente do seu servidor só consegue rotear com base no que ele lê sem analisar o corpo. Marque um argumento de uma ferramenta (tool) com `x-mcp-header`, e os clientes na **[versão do protocolo](../protocol-versions.md)** `2026-07-28` também enviam o valor dele como um cabeçalho HTTP.

## Marque um argumento {#mark-an-argument}

A marca é uma chave a mais no JSON Schema do argumento. No `MCPServer`, o `Field` a coloca lá:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* Por Streamable HTTP na `2026-07-28`, o cliente envia `Mcp-Param-Region` junto com o corpo, e o servidor rejeita uma chamada em que os dois divergem.
* Um cliente que não listou a ferramenta nunca viu a marca: ele não envia cabeçalho nenhum, e a chamada é rejeitada. Nesse caso, o `Client` deste SDK lista as ferramentas e reenvia a chamada uma vez, então listar antes só economiza uma ida e volta.
* Todas as outras conexões ignoram a anotação.

Sua função não muda: `region` continua chegando como argumento.

## O que pode ser marcado {#what-can-be-marked}

Argumentos `str`, `int` e `bool`. Qualquer outra coisa é recusada no registro da ferramenta, com `InvalidSignature`.

Isso inclui `str | None`, que não tem um tipo único. Um argumento opcional precisa ter o schema escrito por extenso, com o `WithJsonSchema` do pydantic:

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## No `Server` de baixo nível {#on-the-low-level-server}

Lá você escreve o `input_schema` à mão, então a chave entra direto:

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* Nada verifica a anotação para você: uma anotação inválida é servida, e os clientes `2026-07-28` deixam a ferramenta fora da listagem deles.

### Schemas por nome {#schemas-by-name}

Para verificar o cabeçalho, o SDK precisa do schema de entrada da ferramenta antes de despachar a chamada. Sem `get_tool_input_schema`, ele obtém esse schema executando o seu handler `on_list_tools` em toda chamada que carrega argumentos, haja ou não alguma ferramenta marcada.

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* Passe a função para responder a partir do que você já tem.
* Retorne `None` para uma ferramenta sem nada a verificar.

## Resumo {#recap}

* `x-mcp-header` em um argumento de ferramenta faz os clientes `2026-07-28` repetirem esse argumento como um cabeçalho HTTP `Mcp-Param-*`.
* O servidor rejeita uma chamada cujo cabeçalho e corpo divergem.
* Só argumentos `str`, `int` e `bool` podem ser marcados. O `MCPServer` lança `InvalidSignature` para qualquer outra coisa.
* O `Server` de baixo nível não verifica nada, e os clientes descartam uma ferramenta cuja anotação é inválida.
* `get_tool_input_schema` evita que o `Server` de baixo nível execute `on_list_tools` em toda chamada.

O restante da API do `Server` escrita à mão está em **[O Server de baixo nível](low-level-server.md)**.
