---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# Mídia {#media}

Texto não é a única coisa que uma ferramenta pode retornar.

O SDK traz dois helpers para resultados binários (**`Image`** e **`Audio`**) e um tipo **`Icon`** para dar uma cara ao seu servidor, às ferramentas, aos recursos e aos prompts na interface do cliente.

## Retornando uma imagem {#returning-an-image}

Anote o tipo de retorno como `Image`, aponte para um arquivo e retorne:

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` recebe exatamente um entre `path` (um arquivo a ser lido) ou `data` (bytes brutos).
* O tipo MIME que o cliente vê é inferido a partir do sufixo: `logo.png` é anunciado como `image/png`.
* Não há nada aqui específico de logos. Qualquer PNG ao lado de `server.py` funciona: um gráfico que seu código renderizou, um diagrama, uma foto.

`Image` é uma conveniência do SDK, não um tipo do protocolo. Na rede, o seu valor de retorno vira um bloco **`ImageContent`** (os bytes do arquivo codificados em base64, mais o tipo MIME):

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

Repare em duas coisas:

* `data` é base64. Você nunca tocou nos bytes; o SDK leu o arquivo e fez a codificação.
* `structured_content` é `None`. Uma `Image` é conteúdo para o modelo olhar, não dados para a aplicação interpretar: não há schema de saída. (Compare com **[Saída estruturada](structured-output.md)**, onde a anotação de retorno *é* o schema.)

!!! info
    `ImageContent` e `AudioContent` ficam em `mcp.types`, bem ao lado do `TextContent`
    em que um resultado `str` simples se transforma (**[Ferramentas](tools.md)**). O resultado de uma ferramenta é uma lista de blocos de conteúdo; `Image` e `Audio` são
    o caminho mais curto para produzir os dois tipos binários.

### Experimente {#try-it}

Coloque qualquer PNG ao lado de `server.py`, dê a ele o nome `logo.png` e execute:

```console
uv run mcp dev server.py
```

Abra a aba **Tools** e chame `logo`. O resultado não é uma string: é um bloco de conteúdo `image`, e o Inspector renderiza sua imagem. Tudo o que aconteceu entre o arquivo no disco e os pixels na tela foi obra do SDK.

## Retornando áudio {#returning-audio}

`Audio` segue o mesmo molde. Mantenha `logo.png` onde estava e coloque qualquer WAV ao lado dele como `chime.wav`:

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

O resultado é um bloco **`AudioContent`**:

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

Funciona do mesmo jeito: entra um arquivo em disco, saem base64 e um tipo MIME, nenhum schema de saída.

## Bytes ou um arquivo {#bytes-or-a-file}

Os dois helpers também aceitam `data=` (bytes brutos) em vez de `path=`. Esse é o modo para bytes que nunca vieram de um arquivo próprio — uma coluna de banco de dados, uma resposta HTTP, algo que o Pillow acabou de desenhar:

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

Com `path=` não há nada a declarar: o arquivo é lido quando o resultado é montado, e o tipo MIME é inferido a partir do sufixo:

* `Image`: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
* `Audio`: `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, `.m4a`.

Um sufixo não reconhecido cai no padrão `application/octet-stream`.

!!! check
    Com `data=` não há nome de arquivo, então não há de onde inferir nada. Esqueça o `format=` e
    o SDK recorre a um padrão: `image/png` para imagens, `audio/wav` para áudio. Monte um
    `Audio` a partir de bytes MP3 desse jeito e o cliente recebe `mime_type="audio/wav"` e,
    confiando nisso, falha ao decodificar. Quando você passar `data=`, passe `format=`.

## Ícones {#icons}

Um `Icon` é metadado, não conteúdo. Ele não carrega a imagem; aponta para uma por meio de uma URI, e um cliente pode buscá-la e mostrá-la ao lado do nome do seu servidor, de uma ferramenta, de um recurso ou de um prompt.

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` é uma URI que o cliente consegue resolver: `https:`, ou uma URI `data:` se você quiser o ícone embutido, sem uma busca extra.
* `mime_type` e `sizes` (`"48x48"`, ou `"any"` para um formato escalável) permitem que o cliente escolha o certo quando você oferece vários.
* `theme="light"` ou `theme="dark"` marca um ícone para um único esquema de cores.

`MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()` e `@mcp.prompt()` aceitam o mesmo argumento nomeado `icons=[...]`.

### Onde um cliente os vê {#where-a-client-sees-them}

Os ícones viajam junto com aquilo que decoram. Os do servidor chegam quando o cliente se conecta, em `client.server_info` (opcional em conexões da era 2026, então restrinja o tipo primeiro):

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

Os ícones de uma ferramenta ficam no objeto `Tool` de `tools/list`; os de um recurso, no `Resource` de `resources/list`; os de um prompt, no `Prompt` de `prompts/list`. O campo sempre se chama `icons`.

## Recapitulando {#recap}

* Retorne uma `Image` ou um `Audio` de uma ferramenta e o cliente recebe um bloco `ImageContent` / `AudioContent`: seus bytes codificados em base64, com um tipo MIME.
* Monte um a partir de um `path=` e deixe o sufixo decidir o tipo MIME, ou a partir de `data=` em memória mais um `format=` explícito.
* Resultados de mídia não trazem `structured_content` nem schema de saída.
* Um `Icon` é um ponteiro: uma URI `src` mais `mime_type`, `sizes` e `theme` opcionais.
* `icons=[...]` funciona no servidor, em ferramentas, em recursos e em prompts, e os clientes os encontram nos objetos correspondentes.

Isso é tudo o que uma ferramenta pode colocar *dentro* de um resultado. O que acontece quando uma ferramenta *falha* (e quem deve ficar sabendo) está em **[Tratando erros](handling-errors.md)**.
