---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# Saída estruturada {#structured-output}

Uma ferramenta (tool) que retorna uma `str` simples produz o resultado duas vezes: como texto em `content` e como `{"result": "..."}` em `structured_content`.

Esta página trata desse segundo canal: de onde ele vem, todas as formas que ele pode assumir e como o SDK garante que ele seja confiável.

A versão curta: **a anotação do tipo de retorno é o schema de saída**. Você já a escreveu.

## O schema de saída {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

A linha que importa é a assinatura: `-> int`.

Por causa dela, a ferramenta que o SDK envia durante `tools/list` carrega um `output_schema` ao lado do schema de entrada que ele monta a partir dos seus parâmetros (**[Ferramentas](tools.md)** cobre esse):

```json
{
  "properties": {
    "result": {"title": "Result", "type": "integer"}
  },
  "required": ["result"],
  "title": "get_temperatureOutput",
  "type": "object"
}
```

Um `int` sozinho não é um objeto JSON, então o SDK o **envolve** em `{"result": ...}`. Chame a ferramenta e os dois canais vêm preenchidos:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

Todo escalar recebe o mesmo wrapper: `str`, `int`, `float`, `bool`, `bytes`, `None`.

## Dois canais {#two-channels}

Por que enviar o mesmo valor duas vezes?

* `content` é para o **modelo**. Um modelo de linguagem lê texto; essa é a única parte do resultado que ele vê.
* `structured_content` é para a **aplicação** dentro da qual o modelo roda: código que quer `17`, não uma frase contendo "17".
* `output_schema` é o contrato entre os dois, publicado antes mesmo de a ferramenta ser chamada.

Você retorna um único valor Python. O SDK preenche os três.

## Retorne um modelo {#return-a-model}

Declare a forma como um `BaseModel` do Pydantic e retorne uma instância:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

`WeatherData` agora **é** o schema. Sem wrapper, sem chave `result`:

```json
{
  "properties": {
    "temperature": {"description": "Degrees Celsius.", "title": "Temperature", "type": "number"},
    "humidity": {"description": "Relative humidity, 0 to 1.", "title": "Humidity", "type": "number"},
    "conditions": {"title": "Conditions", "type": "string"}
  },
  "required": ["temperature", "humidity", "conditions"],
  "title": "WeatherData",
  "type": "object"
}
```

`structured_content` é o objeto, campo por campo:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

E o modelo não fica de fora. O SDK serializa o mesmo objeto como texto JSON para `content`:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

Repare que o `Field(description=...)` em `temperature` e `humidity` foi parar no schema. O mesmo `Field` que descrevia as suas **entradas** descreve as suas saídas.

!!! info
    Se você já usou o `response_model` do FastAPI, já conhece isso: um modelo Pydantic como a resposta
    declarada, serializado e documentado para você. A única diferença é que aqui a anotação de retorno
    é a declaração inteira.

## Um `TypedDict` {#a-typeddict}

Nem toda forma merece uma classe. Um `TypedDict` produz o mesmo schema:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

Um `TypedDict` é um `dict` comum em tempo de execução, então é isso que você monta e retorna. O schema, a validação e o `structured_content` são idênticos aos da versão com `BaseModel` (menos as descrições, para as quais o `TypedDict` não tem lugar).

## Uma dataclass {#a-dataclass}

Dataclasses também funcionam, assim como qualquer classe comum cujos atributos tenham anotações de tipo. O SDK monta um modelo Pydantic a partir das anotações por baixo dos panos.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

Três formas de escrever, um schema só. Use a que a sua base de código já tem.

## Listas {#lists}

Uma `list[...]` também não é um objeto JSON, então ela recebe o wrapper `{"result": ...}`, com o tipo dos seus itens como uma referência `$defs` dentro dele:

```python title="server.py" hl_lines="15"
--8<-- "docs_src/structured_output/tutorial005.py"
```

```json
{
  "$defs": {
    "WeatherData": {
      "properties": {
        "temperature": {"title": "Temperature", "type": "number"},
        "humidity": {"title": "Humidity", "type": "number"},
        "conditions": {"title": "Conditions", "type": "string"}
      },
      "required": ["temperature", "humidity", "conditions"],
      "title": "WeatherData",
      "type": "object"
    }
  },
  "properties": {
    "result": {"items": {"$ref": "#/$defs/WeatherData"}, "title": "Result", "type": "array"}
  },
  "required": ["result"],
  "title": "get_forecastOutput",
  "type": "object"
}
```

Peça uma previsão de dois dias e `structured_content` vem como `{"result": [{...}, {...}]}`. `content` vira **dois** blocos `TextContent`, um por item: uma lista é achatada para o modelo em vez de ser despejada como uma única string.

`tuple[...]`, uniões e `Optional[...]` são envolvidos da mesma forma.

## Dicionários {#dictionaries}

`dict[str, ...]` é o único genérico que já *é* um objeto JSON, então ele não é envolvido:

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial006.py"
```

```json
{
  "additionalProperties": {"type": "number"},
  "title": "get_temperaturesDictOutput",
  "type": "object"
}
```

```python
result.structured_content  # {"London": 16.2, "Reykjavik": 4.4}
```

As chaves precisam ser `str`. Um `dict[int, float]` não pode ser um objeto JSON, então ele recai no wrapper `{"result": ...}`.

## Validação {#validation}

`output_schema` não é documentação. O que quer que a sua função retorne é **validado contra ele** antes de sair do servidor.

Você não percebe enquanto monta o valor à mão: o Pydantic já garantiu que o seu `WeatherData` era um `WeatherData`. Você percebe no dia em que os dados vêm de algum lugar que você não controla:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

A anotação promete `WeatherData`. A resposta do serviço upstream parou de enviar `humidity`.

!!! check
    Chame `get_weather` e ela não entrega discretamente ao cliente um objeto pela metade. A chamada falha,
    e as primeiras linhas do erro dão o nome do campo:

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    Esse texto volta como o resultado da ferramenta com `is_error=True`, então o modelo sabe que a chamada
    falhou em vez de ler, com toda a confiança, um clima que não existe.

Retornar um `dict` comum de uma ferramenta `-> WeatherData` não tem problema, aliás. É exatamente isso que `json.loads` produziu. A validação é feita sobre o valor, não sobre o tipo Python.

## Desativando {#opting-out}

Às vezes a anotação de retorno é para o seu verificador de tipos, não para o protocolo. Passe `structured_output=False` e a ferramenta fica só com texto:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

Sem `output_schema`, sem wrapper, sem validação. `structured_content` é `None` e `content` é a string que você retornou.

O oposto, `structured_output=True`, transforma a detecção automática em exigência: uma ferramenta cujo tipo de retorno não consegue produzir um schema levanta uma exceção no momento do import em vez de recair para texto.

## Uma classe sem anotações de tipo {#a-class-without-type-hints}

Existe um jeito de acabar sem estrutura sem ter pedido por isso: retornar uma classe que **não tem anotações no corpo**.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` define `name` e `online` dentro de `__init__`, mas a *classe* não declara nada. O SDK lê as anotações da classe, não encontra nenhuma e desiste.

!!! warning
    Ele desiste **em silêncio**. `output_schema` é `None`, `structured_content` é `None`, e o texto
    que o modelo lê é o `repr` do objeto:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    Nenhum erro, nenhum aviso, uma ferramenta inútil. Mova as anotações para o corpo da classe, ou passe
    `structured_output=True`, que transforma isso em um erro de verdade no momento em que o módulo é importado:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    Precisa de controle total (montar o `CallToolResult` você mesmo, ou anexar um `_meta` que a
    aplicação enxerga mas o modelo não)? Isso está em **[O Server de baixo nível](../advanced/low-level-server.md)**.

## Recapitulando {#recap}

* A **anotação do tipo de retorno** é o schema de saída. Ela é publicada em `tools/list` como `output_schema`.
* Escalares, listas, tuplas e uniões são envolvidos em `{"result": ...}`. Modelos, `TypedDict`s, dataclasses, classes anotadas e `dict[str, ...]` já são objetos e ficam como estão.
* Todo resultado carrega `content` (texto, para o modelo) **e** `structured_content` (dados, para a aplicação).
* O que você retorna é validado contra o schema. Uma divergência vira um erro de ferramenta, não um resultado corrompido.
* `structured_output=False` deixa uma ferramenta de fora. Uma classe sem anotações de tipo fica de fora em silêncio; fique atento a isso.

Agora você domina tudo o que uma ferramenta pode dizer de volta. A seguir, a segunda primitiva: **[Recursos](resources.md)**.
