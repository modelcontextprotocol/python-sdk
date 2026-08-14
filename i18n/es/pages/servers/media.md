---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# Multimedia {#media}

El texto no es lo único que puede devolver una herramienta.

El SDK incluye dos utilidades para resultados binarios (**`Image`** y **`Audio`**) y un tipo **`Icon`** para darles a tu servidor, herramientas, recursos y prompts una cara visible en la interfaz del cliente.

## Devolver una imagen {#returning-an-image}

Anota el tipo de retorno como `Image`, apúntalo a un archivo y devuélvelo:

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` acepta exactamente uno de los dos: `path` (un archivo que leer) o `data` (bytes en bruto).
* El tipo MIME que ve el cliente se deduce del sufijo: `logo.png` se anuncia como `image/png`.
* No hay nada especial en que sea un logo. Cualquier PNG junto a `server.py` sirve: una gráfica que generó tu código, un diagrama, una foto.

`Image` es una comodidad del SDK, no un tipo del protocolo. En lo que se transmite, el valor devuelto se convierte en un bloque **`ImageContent`** (los bytes del archivo codificados en base64, más el tipo MIME):

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

Dos cosas que notar:

* `data` está en base64. Nunca tocaste los bytes; el SDK leyó el archivo e hizo la codificación.
* `structured_content` es `None`. Un `Image` es contenido para que lo mire el modelo, no datos para que los analice la aplicación: no hay esquema de salida. (Compara con **[Salida estructurada](structured-output.md)**, donde la anotación de retorno *es* el esquema.)

!!! info
    `ImageContent` y `AudioContent` viven en `mcp.types`, justo al lado del `TextContent`
    en el que se convierte un resultado `str` simple (**[Herramientas](tools.md)**). El resultado de una herramienta es una lista de bloques de contenido; `Image` y `Audio` son
    la forma más corta de producir los dos tipos binarios.

### Pruébalo {#try-it}

Coloca cualquier PNG junto a `server.py`, llámalo `logo.png` y ejecuta:

```console
uv run mcp dev server.py
```

Abre la pestaña **Tools** y llama a `logo`. El resultado no es una cadena: es un bloque de contenido `image`, y el Inspector muestra tu imagen. Todo lo que hay entre el archivo en disco y los píxeles en pantalla lo hizo el SDK.

## Devolver audio {#returning-audio}

`Audio` tiene la misma forma. Deja `logo.png` donde estaba y pon cualquier WAV a su lado como `chime.wav`:

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

El resultado es un bloque **`AudioContent`**:

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

Lo mismo: entra un archivo en disco, salen base64 y un tipo MIME, sin esquema de salida.

## Bytes o un archivo {#bytes-or-a-file}

Ambas utilidades aceptan también `data=` (bytes en bruto) en lugar de `path=`. Ese es el modo para los bytes que nunca vinieron de un archivo propio: una columna de base de datos, una respuesta HTTP, algo que Pillow acaba de dibujar:

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

Con `path=` no hay nada que declarar: el archivo se lee cuando se construye el resultado y el tipo MIME se deduce del sufijo:

* `Image`: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
* `Audio`: `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, `.m4a`.

Un sufijo que no reconoce recurre a `application/octet-stream`.

!!! check
    Con `data=` no hay nombre de archivo, así que no hay nada de lo que deducir. Olvida `format=` y
    el SDK recurre a un valor por defecto: `image/png` para imágenes, `audio/wav` para audio. Construye un
    `Audio` así a partir de bytes MP3 y al cliente se le dice `mime_type="audio/wav"`, y entonces
    falla fielmente al decodificarlo. Cuando pases `data=`, pasa `format=`.

## Iconos {#icons}

Un `Icon` es metadatos, no contenido. No lleva la imagen; apunta a una con una URI, y el cliente puede descargarla y mostrarla junto al nombre de tu servidor, una herramienta, un recurso o un prompt.

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` es una URI que el cliente puede resolver: `https:`, o una URI `data:` si quieres el icono incrustado sin una descarga extra.
* `mime_type` y `sizes` (`"48x48"`, o `"any"` para un formato escalable) permiten al cliente elegir el adecuado cuando ofreces varios.
* `theme="light"` o `theme="dark"` marca un icono para un esquema de color.

El mismo argumento nombrado `icons=[...]` lo aceptan `MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()` y `@mcp.prompt()`.

### Dónde los ve un cliente {#where-a-client-sees-them}

Los iconos viajan con lo que decoran. Los del servidor llegan cuando el cliente se conecta, en `client.server_info` (opcional en conexiones de la generación 2026, así que acota el tipo primero):

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

Los iconos de una herramienta están en el objeto `Tool` de `tools/list`, los de un recurso en el `Resource` de `resources/list`, los de un prompt en el `Prompt` de `prompts/list`. El campo siempre se llama `icons`.

## Resumen {#recap}

* Devuelve un `Image` o un `Audio` desde una herramienta y el cliente recibe un bloque `ImageContent` / `AudioContent`: tus bytes codificados en base64, con un tipo MIME.
* Constrúyelo a partir de un `path=` y deja que el sufijo decida el tipo MIME, o a partir de `data=` en memoria más un `format=` explícito.
* Los resultados multimedia no llevan `structured_content` ni esquema de salida.
* Un `Icon` es un puntero: una URI `src` más `mime_type`, `sizes` y `theme` opcionales.
* `icons=[...]` funciona en el servidor, en herramientas, en recursos y en prompts, y los clientes los encuentran en los objetos correspondientes.

Eso es todo lo que una herramienta puede poner *dentro* de un resultado. Lo que ocurre cuando una herramienta *falla* (y quién debería enterarse) está en **[Manejo de errores](handling-errors.md)**.
