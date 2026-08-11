---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# Объект Client {#the-client}

Через **`Client`** программа на Python общается с MCP-сервером.

Это один объект с одним жизненным циклом: создать его, войти в `async with`, вызывать методы. Каждая операция протокола (получить список инструментов, вызвать один из них, прочитать ресурс, отрендерить промпт) — это `async`-метод этого объекта, возвращающий типизированный результат.

## Первый клиент {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

Сервер в начале файла нужен лишь для того, чтобы было к чему подключаться. Клиент — это пять выделенных строк.

* `Client(mcp)` получает **сам объект сервера**. Это транспорт в памяти: ни подпроцесса, ни порта, ни HTTP. Именно так подключается каждый пример на этой странице и каждый тест, который вы напишете.
* `async with` — это **жизненный цикл**. Вход в блок подключает и согласовывает возможности; выход — отключает. Пары `connect()` / `close()` нет, и `Client` нельзя использовать повторно после завершения блока.
* Внутри блока сведения о подключении уже доступны как обычные свойства.

### Что можно передать в `Client` {#what-you-can-pass-to-client}

`Client` принимает один позиционный аргумент и определяет транспорт по его типу:

* Экземпляр `MCPServer` (или низкоуровневого `Server`): подключение **внутри процесса**.
* Строка с URL (`Client("http://localhost:8000/mcp")`): Streamable HTTP, основной вариант для реального развёртывания.
* **Транспорт**: всё, что можно использовать как `async with ... as (read, write)`, например `stdio_client(...)`, оборачивающий подпроцесс.

Всё остальное на этой странице одинаково для всех трёх вариантов. Заголовкам, подпроцессам, тайм-аутам и протоколу `Transport` посвящена отдельная страница: **[Транспорты клиента](transports.md)**.

### Что есть у подключённого клиента {#whats-on-a-connected-client}

Четыре свойства только для чтения, заполняемые в момент входа в блок:

* `client.server_info`: сведения о сервере или `None` для сервера поколения 2026, который их не сообщает (серверы на python-sdk по умолчанию сообщают). Здесь `server_info.name` — `"Bookshop"`, а `server_info.version` — то, что сообщает сервер.
* `client.server_capabilities`: что умеет сервер (`tools`, `resources`, `prompts`, `completions`, ...). Возможность, которой у сервера нет, равна `None`.
* `client.protocol_version`: версия протокола, о которой договорились стороны. Здесь это `"2026-07-28"`.
* `client.instructions`: строка `instructions=` сервера или `None`, если сервер её не задал.

Версию протокола вы нигде не выбирали. По умолчанию `Client` зондирует сервер и на старых серверах переходит к классическому рукопожатию, так что один клиент работает с сервером любого поколения. Если этим нужно управлять, подробнее — на странице **[Версии протокола](../protocol-versions.md)**.

!!! tip
    `client.session` — это лежащий в основе `ClientSession`, низкоуровневый запасной выход.
    Ни для чего на этой странице он не понадобится.

## Получение списка инструментов {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` возвращает `ListToolsResult`; инструменты лежат в `.tools`. Каждый из них — полное определение, которое хост передал бы модели:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

а `tool.input_schema` — это JSON Schema, которую сервер вывел из аннотаций типов функции:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Этой схемы достаточно и интерфейсу, чтобы отрисовать форму аргументов, и модели, чтобы сформировать корректные аргументы.

!!! tip
    `title` необязателен, поэтому интерфейсу, показывающему инструменты человеку, приходится выбирать: `title`, если он есть,
    иначе `name`. `from mcp.shared.metadata_utils import get_display_name` делает именно это —
    для инструментов, ресурсов, шаблонов ресурсов и промптов.

## Вызов инструмента {#calling-a-tool}

`call_tool(name, arguments)` запускает инструмент и возвращает `CallToolResult`.

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

Серверный `lookup_book` возвращает Pydantic-модель `Book`. Вот что видит клиент:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

Одно возвращаемое значение, три поля для чтения. У каждого свой потребитель.

### `content`: что читает модель {#content-what-the-model-reads}

`content` — это `list` **блоков содержимого**, а блок содержимого — объединение типов: `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink` или `EmbeddedResource`. Инструмент может вернуть несколько блоков, причём разных видов.

Поэтому `main` сужает тип с помощью `isinstance(block, TextContent)`, прежде чем обращаться к `block.text`. Обратите внимание: вне `isinstance` обращения к `.text` нет — проверка типов этого не допустит, потому что у `ImageContent` есть `.data`, а не `.text`. Объединение честно описывает, что инструмент вправе прислать; код должен быть столь же честен.

### `structured_content`: что читает приложение {#structured_content-what-your-application-reads}

`structured_content` — это возвращаемое значение инструмента в виде JSON, соответствующего объявленной `output_schema` инструмента. Никакого разбора строк, никаких догадок.

Когда есть и то и другое, они намеренно говорят одно и то же дважды: `content` — для модели, `structured_content` — для кода. Откуда берётся структурированная часть и как ею управлять — на странице **[Структурированный вывод](../servers/structured-output.md)**.

### `is_error`: завершился ли инструмент ошибкой {#is_error-whether-the-tool-failed}

Инструмент, выбросивший исключение, **не** выбрасывает его в клиенте. Он возвращается обычным результатом с `is_error=True`.

!!! check
    Запросите у `lookup_book` `"Solaris"` (название, которого нет в каталоге), и функция выбросит
    `ValueError`. Вызов всё равно завершится нормально:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    Сообщение исключения попало в `content`, где **модель** может его прочитать и попробовать снова. Так
    и задумано: ошибка инструмента — часть диалога, а не крах. Всегда проверяйте `is_error`,
    прежде чем доверять `structured_content`.

!!! warning
    `is_error=True` покрывает не только ваш собственный `raise`. Запросите инструмент, которого у сервера вообще нет
    (`call_tool("does_not_exist", {})`), — и исключения не будет. Вернётся та же структура:
    `is_error=True` с `Unknown tool: does_not_exist` в `content`. Метод `Client` выбрасывает
    `MCPError` только тогда, когда сервер отвечает **ошибкой** JSON-RPC вместо результата, а
    когда сервер выдаёт одно, а когда другое, описано на странице **[Обработка ошибок](../servers/handling-errors.md)**.

## Ресурсы {#resources}

Операции с ресурсами идут парами: два способа получить список и один способ прочитать.

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` возвращает **конкретные** ресурсы — те, у которых фиксированный URI. Здесь: `['catalog://genres']`.
* `list_resource_templates()` возвращает **параметризованные**. Здесь: `['catalog://genres/{genre}']`. Это два разных списка, потому что шаблон нельзя прочитать, пока его не заполнить.
* `read_resource(uri)` принимает URI обычной строкой `str` и работает с обоими: передайте `"catalog://genres/poetry"`, и сервер сопоставит его с шаблоном.

`read_resource` возвращает `contents` — список `TextResourceContents` или `BlobResourceContents`. Та же идея, что и с содержимым инструмента: сузьте тип через `isinstance`, затем читайте `.text` (или `.blob`).

Клиент может также узнавать об изменениях ресурса. На подключениях поколения 2025 это `subscribe_resource(uri)` / `unsubscribe_resource(uri)` — пара методов, которую `MCPServer` не реализует, поэтому в протоколе 2026-07-28 (где этих операций больше нет) запрос получает в ответ `-32601`, *Method not found*. Замена в поколении 2026 — поток `subscriptions/listen`, который `MCPServer` *как раз* обслуживает (`server_capabilities.resources.subscribe` там равно `True`), а как читать его через `client.listen(...)` — на странице **[Подписки](subscriptions.md)** этого раздела.

## Промпты {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` сообщает, что предлагает сервер и что нужно каждому промпту:

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` рендерит его. Словарь аргументов имеет вид `str -> str`: аргументы промпта всегда строки. Результат — `messages`, список `PromptMessage`, у каждого есть `role` и блок `content`:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

Хост передаёт эти сообщения прямо модели. Вот и вся возможность.

## Автодополнение {#completions}

Сервер с обработчиком автодополнения может дополнять аргументы промптов и шаблонов ресурсов по мере того, как пользователь их вводит.

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` указывает, *какой* промпт или шаблон заполняется: `PromptReference` или `ResourceTemplateReference`.
* `argument` — это `{"name": ..., "value": ...}`: аргумент и то, что пользователь уже успел набрать.

Ответ лежит в `result.completion.values`. Наберите `"p"` — и сервер вернёт `['poetry']`. Серверная сторона и то, как обработчик использует *другие*, уже заполненные аргументы, чтобы сузить подсказки, — на странице **[Автодополнение](../servers/completions.md)**.

## Пагинация {#pagination}

Каждый метод `list_*` принимает именованный аргумент `cursor=`, а каждый результат содержит `next_cursor`. Когда `next_cursor` равен `None`, у вас есть всё.

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

Этот цикл корректен для любого сервера. `MCPServer` возвращает всё одной страницей, так что `next_cursor` равен `None` и цикл выполняется один раз — поэтому в большинстве программ его и не пишут. О серверах, которые действительно разбивают выдачу на страницы, и о правилах, которым подчиняются курсоры, — на странице **[Пагинация](../advanced/pagination.md)**.

## В тестах {#in-tests}

`Client(mcp)` без процесса и без порта — уже готовая тестовая обвязка для сервера.

Для этого есть один специальный флаг конструктора: `Client(mcp, raise_exceptions=True)`. Он действует только на подключениях в памяти, а объясняет его и строит вокруг него весь подход страница **[Тестирование](../get-started/testing.md)**.

## Итоги {#recap}

* `Client(x)` подключается в памяти к объекту сервера, по Streamable HTTP — к строке с URL, а ко всему остальному — через транспорт.
* `async with` — это весь жизненный цикл. Внутри него `server_capabilities` и `protocol_version` уже заполнены; `server_info` и `instructions` — тоже, если сервер их предоставляет.
* `list_tools()` даёт `name`, `title`, `description` и `input_schema` каждого инструмента.
* `call_tool()` возвращает `content` для модели, `structured_content` для кода и `is_error`. Инструмент, выбросивший исключение, — это результат, а не исключение.
* `content` — объединение типов блоков; сужайте тип через `isinstance` перед чтением.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt` и `complete` замыкают набор операций.
* Каждый `list_*` принимает `cursor=`; крутите цикл, пока `next_cursor` не станет `None`.

То, о чём сервер может попросить *клиент*, и как на это отвечать, — на странице **[Колбэки клиента](callbacks.md)**.
