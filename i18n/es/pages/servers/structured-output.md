---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, 91be9b73602abcf1, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c7eff2a5698225fa, c851964bb3301907, 8f296f1f09e4c400, d715db6f8dccc9cc, a0c344a48450dbe4]
  tool: 1
---
# Salida estructurada {#structured-output}

Una herramienta que devuelve un simple `str` produce el resultado dos veces: como texto en `content` y como `{"result": "..."}` en `structured_content`.

Esta página trata de ese segundo canal: de dónde sale, todas las formas que puede tomar y cómo el SDK garantiza que sea fiel.

La versión corta: **la anotación del tipo de retorno es el esquema de salida**. Ya la escribiste.

## El esquema de salida {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

La línea que importa es la firma: `-> int`.

Gracias a ella, la herramienta que el SDK envía durante `tools/list` lleva un `output_schema` junto al esquema de entrada que construye a partir de tus parámetros (de ese se ocupa **[Herramientas](tools.md)**):

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

Un `int` suelto no es un objeto JSON, así que el SDK lo **envuelve** en `{"result": ...}`. Llama a la herramienta y se llenan los dos canales:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

Todos los escalares reciben el mismo envoltorio: `str`, `int`, `float`, `bool`, `bytes`, `None`.

## Dos canales {#two-channels}

¿Por qué enviar el mismo valor dos veces?

* `content` es para el **modelo**. Un modelo de lenguaje lee texto; es la única parte del resultado que ve.
* `structured_content` es para la **aplicación** dentro de la que se ejecuta el modelo: código que quiere `17`, no una frase que contenga "17".
* `output_schema` es el contrato entre ambos, publicado antes de que la herramienta se llame por primera vez.

Devuelves un único valor de Python. El SDK rellena los tres.

## Devolver un modelo {#return-a-model}

Declara la forma como un `BaseModel` de Pydantic y devuelve una instancia:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

Ahora `WeatherData` **es** el esquema. Sin envoltorio, sin clave `result`:

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

`structured_content` es el objeto, campo por campo:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

Y el modelo no se queda fuera. El SDK serializa el mismo objeto como texto JSON para `content`:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

Fíjate en que el `Field(description=...)` de `temperature` y `humidity` acabó en el esquema. El mismo `Field` que describía tus **entradas** describe tus salidas.

!!! info
    Si has usado el `response_model` de FastAPI, esto ya lo conoces: un modelo de Pydantic como respuesta
    declarada, serializado y documentado por ti. La única diferencia es que aquí la anotación de retorno
    es toda la declaración.

## Un `TypedDict` {#a-typeddict}

No todas las formas merecen una clase. Un `TypedDict` produce el mismo esquema:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

Un `TypedDict` es un `dict` normal en tiempo de ejecución, así que eso es lo que construyes y devuelves. El esquema, la validación y `structured_content` siguen las mismas reglas que la versión con `BaseModel`: añade un docstring a la clase o `Annotated[..., Field(description=...)]` y se convierten en las descripciones, y una clave `NotRequired` que dejes fuera del dict se queda fuera de `structured_content`.

## Una dataclass {#a-dataclass}

Las dataclasses también funcionan, igual que cualquier clase normal cuyos atributos tengan anotaciones de tipo. El SDK construye internamente un modelo de Pydantic a partir de las anotaciones.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

Tres formas de escribirlo, un solo esquema. Usa la que ya tenga tu código.

## Listas {#lists}

Un `list[...]` tampoco es un objeto JSON, así que recibe el envoltorio `{"result": ...}`, con tu tipo de elemento dentro como referencia en `$defs`:

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

Pide un pronóstico de dos días y `structured_content` es `{"result": [{...}, {...}]}`. `content` se convierte en **dos** bloques `TextContent`, uno por elemento: una lista se aplana para el modelo en lugar de volcarse como una sola cadena.

`tuple[...]`, las uniones y `Optional[...]` se envuelven de la misma manera.

## Diccionarios {#dictionaries}

`dict[str, ...]` es el único genérico que ya *es* un objeto JSON, así que no se envuelve:

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

Las claves deben ser `str`. Un `dict[int, float]` no puede ser un objeto JSON, así que recurre al envoltorio `{"result": ...}`.

## Validación {#validation}

`output_schema` no es documentación. Lo que devuelva tu función **se valida contra él** antes de salir del servidor.

No lo notas mientras construyes el valor a mano: Pydantic ya se aseguró de que tu `WeatherData` fuera un `WeatherData`. Lo notas el día que los datos vienen de algún sitio que no controlas:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

La anotación promete `WeatherData`. La respuesta del servicio externo dejó de enviar `humidity`.

!!! check
    Llama a `get_weather` y no le entrega al cliente en silencio un objeto medio vacío. La llamada falla:
    el cliente recibe `is_error=True` con `Error executing tool get_weather`, así que el modelo sabe que la
    llamada falló en lugar de leer con toda confianza un tiempo que no existe. El nombre del campo es para ti,
    en el log del servidor con nivel `ERROR`:

    ```text
    Tool 'get_weather' raised an unexpected exception
    ...
    pydantic_core._pydantic_core.ValidationError: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

Por cierto, devolver un `dict` normal desde una herramienta `-> WeatherData` está bien. Es exactamente lo que produjo `json.loads`. La validación se aplica al valor, no al tipo de Python.

## Desactivarlo {#opting-out}

A veces la anotación de retorno es para tu verificador de tipos, no para el protocolo. Pasa `structured_output=False` y la herramienta es solo texto:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

Sin `output_schema`, sin envoltorio, sin validación. `structured_content` es `None` y `content` es la cadena que devolviste.

Lo contrario, `structured_output=True`, convierte la detección automática en un requisito: una herramienta cuyo tipo de retorno no pueda producir un esquema lanza una excepción al importar el módulo en lugar de recurrir al texto.

## Bloques de contenido y medios {#content-blocks-and-media}

Los bloques de contenido y los medios (`TextContent`, `EmbeddedResource`, `Image`, `Audio` y compañía, ya sea solos, como elementos de un `list`, `tuple` o `Sequence`, o como ramas de una unión) quedan excluidos sin que hagas nada: son para que los lea el modelo, así que la detección automática no deriva ningún esquema de ellos (**[Imágenes, audio e iconos](media.md)** se ocupa de `Image` y `Audio`). `structured_output=True` sigue forzando uno para las clases de bloques de contenido.

## Una clase sin anotaciones de tipo {#a-class-without-type-hints}

Hay una forma de acabar sin salida estructurada sin haberlo pedido: devolver una clase que **no tiene anotaciones en su cuerpo**.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` asigna `name` y `online` dentro de `__init__`, pero la *clase* no declara nada. El SDK lee las anotaciones de la clase, no encuentra ninguna y desiste.

!!! warning
    Desiste **en silencio**. `output_schema` es `None`, `structured_content` es `None` y el texto
    que lee el modelo es el `repr` del objeto:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    Ni error, ni aviso: una herramienta inútil. Mueve las anotaciones al cuerpo de la clase o pasa
    `structured_output=True`, que convierte esto en un error inmediato en cuanto se importa el módulo:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    ¿Necesitas control total (construir el `CallToolResult` tú mismo o adjuntar un `_meta` que la
    aplicación pueda ver pero el modelo no)? Eso es **[El Server de bajo nivel](../advanced/low-level-server.md)**.

## Resumen {#recap}

* La **anotación del tipo de retorno** es el esquema de salida. Se publica en `tools/list` como `output_schema`.
* Los escalares, las listas, las tuplas y las uniones se envuelven en `{"result": ...}`. Los modelos, los `TypedDict`, las dataclasses, las clases con anotaciones y `dict[str, ...]` ya son objetos y se quedan como están.
* Cada resultado lleva `content` (texto, para el modelo) **y** `structured_content` (datos, para la aplicación).
* Lo que devuelves se valida contra el esquema. Una discrepancia es un error de herramienta, no un resultado corrupto.
* `structured_output=False` excluye una herramienta. Los bloques de contenido, `Image` y `Audio` quedan excluidos por defecto; una clase sin anotaciones de tipo queda excluida en silencio, así que vigílalo.

Ahora dominas todo lo que una herramienta puede responder. A continuación, la segunda primitiva: **[Recursos](resources.md)**.
