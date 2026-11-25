---
translation:
  sections: [ebef1e7a0df854f4, 7e16449f66e7dfd6, eeb0682f7d2a1079, 5713f0196a34e6e7, 0e844597859e4248, 3a97d9195ddcc92e, 1da08c483e59c141, 84702cc6e0a1fd42, 8dee7a31c86ffc5c, 83a5bce168ef23d7]
  tool: 1
---
# Клієнт {#the-client}

**`Client`** — це те, через що програма на Python спілкується з MCP-сервером.

Це один об'єкт з одним життєвим циклом: створіть його, увійдіть в `async with`, викликайте методи. Кожна дія протоколу (перелічити інструменти, викликати один із них, прочитати ресурс, відрендерити промпт) — це його `async`-метод, що повертає типізований результат.

## Перший клієнт {#your-first-client}

Клієнтові потрібен сервер, з яким говорити. До цього Bookshop під'єднується кожен приклад на цій сторінці. Збережіть його як `server.py` і залиште працювати через HTTP:

```python title="server.py"
--8<-- "docs_src/client/tutorial001.py"
```

```console
uv run mcp run server.py --transport streamable-http
```

Тепер сервер доступний за адресою `http://localhost:8000/mcp`. Клієнт — окрема програма. Збережіть його як `client.py` і запустіть `python client.py` у другому терміналі:

```python title="client.py" hl_lines="7-11"
--8<-- "docs_src/client/tutorial001_client.py"
```

* `Client("http://localhost:8000/mcp")` отримує **URL**, тож під'єднується через Streamable HTTP до сервера, який ви щойно запустили.
* `async with` — це **життєвий цикл**. Вхід у блок під'єднує й узгоджує параметри; вихід — від'єднує. Пари `connect()` / `close()` немає, а `Client` не можна використати повторно після завершення блоку.
* Усередині блоку відомості про з'єднання вже доступні як звичайні властивості.

### Що можна передати в `Client` {#what-you-can-pass-to-client}

`Client` приймає один позиційний аргумент і визначає транспорт за його типом:

* Рядок з URL (`Client("http://localhost:8000/mcp")`): Streamable HTTP, транспорт для робочого розгортання.
* `StdioServerParameters`: команда, яку буде запущено як локальний **підпроцес**; спілкування з ним іде через його stdin і stdout.
* **Транспорт**: будь-що, що можна використати як `async with ... as (read, write)`, наприклад `streamable_http_client(url, http_client=...)` навколо вашого власного HTTP-клієнта.
* Екземпляр `MCPServer` (або низькорівневого `Server`): під'єднання **в межах процесу**, без підпроцесу й без порту. Це для тестів, і на ньому побудована сторінка **[Тестування](../get-started/testing.md)**.

Усе інше на цій сторінці однакове для всіх чотирьох. Заголовки, підпроцеси, тайм-аути та протокол `Transport` мають власну сторінку: **[Транспорти клієнта](transports.md)**.

### Що є в під'єднаного клієнта {#whats-on-a-connected-client}

Чотири властивості лише для читання, заповнені в мить входу в блок:

* `client.server_info`: ідентичність сервера або `None` для сервера покоління 2026, який її не повідомляє (сервери python-sdk за замовчуванням повідомляють). `server_info.name` тут — `"Bookshop"`, а `server_info.version` — те, що повідомить сервер.
* `client.server_capabilities`: що вміє сервер (`tools`, `resources`, `prompts`, `completions`, ...). Можливість, якої сервер не має, дорівнює `None`.
* `client.protocol_version`: версія протоколу, про яку домовилися обидві сторони. Тут це `"2026-07-28"`.
* `client.instructions`: рядок `instructions=` сервера або `None`, якщо сервер його не задав.

Версію протоколу ви не обирали. За замовчуванням `Client` зондує сервер і на старіших повертається до класичного рукостискання, тож один клієнт працює із сервером будь-якого покоління. Якщо потрібно цим керувати, докладніше — на сторінці **[Версії протоколу](../protocol-versions.md)**.

!!! tip
    `client.session` — це базова `ClientSession`, низькорівневий запасний вихід.
    Для жодної задачі на цій сторінці вона не знадобиться.

## Перелік інструментів {#listing-tools}

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` повертає `ListToolsResult`; інструменти лежать у `.tools`. Кожен із них — повне означення, яке хост передав би моделі. Ось перший:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

а `tool.input_schema` — це JSON Schema, яку сервер вивів з анотацій типів функції:

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

Ця схема — усе, що потрібно UI, щоб показати форму аргументів, і все, що потрібно моделі, щоб сформувати коректні аргументи.

Другий інструмент, `lookup_book`, зареєстровано без `title=`, тож його `tool.title` дорівнює `None`.

!!! tip
    `title` необов'язковий, тож UI, що показує інструменти людині, має обирати: `title`, якщо він є,
    і `name`, якщо немає. `from mcp.shared.metadata_utils import get_display_name` робить саме це —
    для інструментів, ресурсів, шаблонів ресурсів і промптів.

## Виклик інструмента {#calling-a-tool}

`call_tool(name, arguments)` запускає інструмент і повертає `CallToolResult`.

```python title="client.py" hl_lines="9-16"
--8<-- "docs_src/client/tutorial003.py"
```

Серверний `lookup_book` повертає Pydantic-модель `Book`. Ось що бачить клієнт:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

Одне повернене значення, три речі для читання. У кожної свій споживач.

### `content`: що читає модель {#content-what-the-model-reads}

`content` — це `list` **блоків вмісту**, а блок вмісту — це об'єднання типів: `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink` або `EmbeddedResource`. Інструмент може повернути кілька блоків, різних видів.

Саме тому `main` звужує тип через `isinstance(block, TextContent)`, перш ніж звертатися до `block.text`. Зверніть увагу: поза `isinstance` немає жодного `.text` — перевірка типів цього не дозволить, бо `ImageContent` має `.data`, а не `.text`. Об'єднання чесно показує, що інструменту дозволено вам надіслати; ваш код має бути таким самим чесним.

### `structured_content`: що читає ваш застосунок {#structured_content-what-your-application-reads}

`structured_content` — це повернене значення інструмента у вигляді JSON, що відповідає оголошеній `output_schema` інструмента. Жодного розбору рядків, жодних здогадок.

Коли є обидва, вони навмисно кажуть те саме двічі: `content` — для моделі, `structured_content` — для коду. Звідки береться структурована половина і як нею керувати — на сторінці **[Структурований вивід](../servers/structured-output.md)**.

### `is_error`: чи завершився інструмент помилкою {#is_error-whether-the-tool-failed}

Інструмент, що викидає виняток, **не** викидає його у вашому клієнті. Він повертається як звичайний результат з `is_error=True`.

!!! check
    Попросіть у `lookup_book` `"Solaris"` (назву, якої немає в каталозі) — і функція викине
    `ToolError`. Виклик усе одно повернеться нормально:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    Повідомлення `ToolError` потрапило в `content`, де його може прочитати **модель** і спробувати ще раз. Це
    навмисно: помилка інструмента — частина розмови, а не аварія. (Якби інструмент упав
    з якимось іншим винятком, у `content` було б лише `Error executing tool lookup_book`.) Завжди дивіться на
    `is_error`, перш ніж довіряти `structured_content`.

!!! warning
    `is_error=True` охоплює більше, ніж ваш власний `raise`. Попросіть інструмент, якого в сервера
    взагалі немає (`call_tool("does_not_exist", {})`), — і нічого не викидається. Повертається та сама форма:
    `is_error=True` з `Unknown tool: does_not_exist` у `content`. Метод `Client` викидає
    `MCPError` лише тоді, коли сервер відповідає **помилкою** JSON-RPC замість результату, а коли
    сервер повертає що саме — описано на сторінці **[Обробка помилок](../servers/handling-errors.md)**.

## Ресурси {#resources}

Дії з ресурсами йдуть парами: два способи перелічити, один спосіб прочитати.

```python title="client.py" hl_lines="9-18"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` повертає **конкретні** ресурси — ті, що мають фіксований URI. Тут: `['catalog://genres']`.
* `list_resource_templates()` повертає **параметризовані**. Тут: `['catalog://genres/{genre}']`. Це два різні списки, бо шаблон не можна прочитати, доки його не заповнено.
* `read_resource(uri)` приймає URI як звичайний `str` і працює з обома: передайте `"catalog://genres/poetry"` — і сервер зіставить його з шаблоном.

`read_resource` повертає `contents` — список `TextResourceContents` або `BlobResourceContents`. Та сама ідея, що й із вмістом інструментів: звузьте тип через `isinstance`, потім читайте `.text` (або `.blob`).

Клієнта також можна сповіщати про зміни ресурсу. На з'єднаннях покоління 2025 це `subscribe_resource(uri)` / `unsubscribe_resource(uri)` — пара методів, яку `MCPServer` не реалізує, тож у протоколі 2026-07-28 (де цих дій уже немає) запит повертає `-32601`, *Method not found*. Заміна у версії 2026 — потік `subscriptions/listen`, який `MCPServer` *таки* обслуговує — `server_capabilities.resources.subscribe` там дорівнює `True` — а як споживати його через `client.listen(...)`, описано на сторінці **[Підписки](subscriptions.md)** цього розділу.

## Промпти {#prompts}

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` повідомляє, що пропонує сервер і що потрібно кожному промпту:

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` рендерить його. Словник аргументів — `str -> str`: аргументи промпту завжди рядки. Результат — `messages`, список `PromptMessage`, кожне з `role` і блоком `content`:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

Хост передає ці повідомлення прямо моделі. Оце й уся можливість.

## Автодоповнення {#completions}

Сервер з обробником автодоповнення може доповнювати аргументи промптів і шаблонів ресурсів, поки користувач друкує.

```python title="client.py" hl_lines="9-13"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` вказує, *який* промпт чи шаблон ви заповнюєте: `PromptReference` або `ResourceTemplateReference`.
* `argument` — це `{"name": ..., "value": ...}`: аргумент і те, що користувач уже встиг набрати.

Відповідь — у `result.completion.values`. Наберіть `"p"` — і сервер поверне `['poetry']`. Серверний бік, а також те, як обробник використовує *інші*, уже заповнені аргументи, щоб звузити свої пропозиції, — на сторінці **[Автодоповнення](../servers/completions.md)**.

## Пагінація {#pagination}

Кожен метод `list_*` приймає іменований аргумент `cursor=`, а кожен результат містить `next_cursor`. Коли `next_cursor` дорівнює `None`, у вас є все.

```python title="client.py" hl_lines="7-15"
--8<-- "docs_src/client/tutorial007.py"
```

`list_all_tools` коректна для будь-якого сервера. `MCPServer` повертає все однією сторінкою, тож `next_cursor` дорівнює `None` і цикл виконується один раз — саме тому більшість коду його ніколи не пише. Сервери, що справді розбивають результати на сторінки, і правила, яким підкоряються курсори, — на сторінці **[Пагінація](../advanced/pagination.md)**.

## У тестах {#in-tests}

Кожен `client.py` на цій сторінці звертався до `server.py` через HTTP. У тесті мережу оминають і передають у `Client` сам об'єкт сервера: `from server import mcp`, потім `Client(mcp)`. Без процесу, без порту, а всі методи вище працюють так само.

Саме для цього є один прапорець конструктора: `Client(mcp, raise_exceptions=True)`. Він діє лише на з'єднаннях у межах процесу, а пояснює його й будує навколо нього весь підхід сторінка **[Тестування](../get-started/testing.md)**.

## Підсумки {#recap}

* `Client(x)` під'єднується через Streamable HTTP до рядка з URL, запускає підпроцес для `StdioServerParameters`, входить у транспорт напряму, а в тестах приймає сам об'єкт сервера.
* `async with` — це весь життєвий цикл. Усередині нього `server_capabilities` і `protocol_version` уже заповнені; `server_info` та `instructions` — теж, якщо сервер їх надає.
* `list_tools()` дає `name`, `title`, `description` та `input_schema` кожного інструмента.
* `call_tool()` повертає `content` для моделі, `structured_content` для вашого коду та `is_error`. Інструмент, що викидає виняток, — це результат, а не виняток.
* `content` — об'єднання типів блоків; звужуйте тип через `isinstance`, перш ніж читати.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt` і `complete` доповнюють набір дій.
* Кожен `list_*` приймає `cursor=`; повторюйте цикл, доки `next_cursor` не стане `None`.

Про що сервер може попросити *клієнта* і як на це відповідати — на сторінці **[Колбеки клієнта](callbacks.md)**.
