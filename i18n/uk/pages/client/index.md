---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# Клієнт {#the-client}

**`Client`** — це те, через що програма на Python спілкується з MCP-сервером.

Це один об'єкт з одним життєвим циклом: створіть його, увійдіть в `async with`, викликайте методи. Кожна дія протоколу (перелічити інструменти, викликати один із них, прочитати ресурс, відрендерити промпт) — це його `async`-метод, що повертає типізований результат.

## Перший клієнт {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

Сервер угорі потрібен лише для того, щоб було до чого під'єднатися. Клієнт — це п'ять виділених рядків.

* `Client(mcp)` отримує **сам об'єкт сервера**. Це транспорт у пам'яті: без підпроцесу, без порту, без HTTP. Саме так під'єднується кожен приклад на цій сторінці й кожен тест, який ви напишете.
* `async with` — це **життєвий цикл**. Вхід у блок під'єднує й узгоджує параметри; вихід — від'єднує. Пари `connect()` / `close()` немає, а `Client` не можна використати повторно після завершення блоку.
* Усередині блоку відомості про з'єднання вже доступні як звичайні властивості.

### Що можна передати в `Client` {#what-you-can-pass-to-client}

`Client` приймає один позиційний аргумент і визначає транспорт за його типом:

* Екземпляр `MCPServer` (або низькорівневого `Server`): під'єднання **в межах процесу**.
* Рядок з URL (`Client("http://localhost:8000/mcp")`): Streamable HTTP, шлях для робочого розгортання.
* **Транспорт**: будь-що, що можна використати як `async with ... as (read, write)`, наприклад `stdio_client(...)`, що обгортає підпроцес.

Усе інше на цій сторінці однакове для всіх трьох. Заголовки, підпроцеси, тайм-аути та протокол `Transport` мають власну сторінку: **[Транспорти клієнта](transports.md)**.

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

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` повертає `ListToolsResult`; інструменти лежать у `.tools`. Кожен із них — повне означення, яке хост передав би моделі:

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

!!! tip
    `title` необов'язковий, тож UI, що показує інструменти людині, має обирати: `title`, якщо він є,
    і `name`, якщо немає. `from mcp.shared.metadata_utils import get_display_name` робить саме це —
    для інструментів, ресурсів, шаблонів ресурсів і промптів.

## Виклик інструмента {#calling-a-tool}

`call_tool(name, arguments)` запускає інструмент і повертає `CallToolResult`.

```python title="client.py" hl_lines="26-33"
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
    `ValueError`. Виклик усе одно повернеться нормально:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    Повідомлення винятку потрапило в `content`, де його може прочитати **модель** і спробувати ще раз. Це
    навмисно: помилка інструмента — частина розмови, а не аварія. Завжди дивіться на `is_error`,
    перш ніж довіряти `structured_content`.

!!! warning
    `is_error=True` охоплює більше, ніж ваш власний `raise`. Попросіть інструмент, якого в сервера
    взагалі немає (`call_tool("does_not_exist", {})`), — і нічого не викидається. Повертається та сама форма:
    `is_error=True` з `Unknown tool: does_not_exist` у `content`. Метод `Client` викидає
    `MCPError` лише тоді, коли сервер відповідає **помилкою** JSON-RPC замість результату, а коли
    сервер повертає що саме — описано на сторінці **[Обробка помилок](../servers/handling-errors.md)**.

## Ресурси {#resources}

Дії з ресурсами йдуть парами: два способи перелічити, один спосіб прочитати.

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` повертає **конкретні** ресурси — ті, що мають фіксований URI. Тут: `['catalog://genres']`.
* `list_resource_templates()` повертає **параметризовані**. Тут: `['catalog://genres/{genre}']`. Це два різні списки, бо шаблон не можна прочитати, доки його не заповнено.
* `read_resource(uri)` приймає URI як звичайний `str` і працює з обома: передайте `"catalog://genres/poetry"` — і сервер зіставить його з шаблоном.

`read_resource` повертає `contents` — список `TextResourceContents` або `BlobResourceContents`. Та сама ідея, що й із вмістом інструментів: звузьте тип через `isinstance`, потім читайте `.text` (або `.blob`).

Клієнта також можна сповіщати про зміни ресурсу. На з'єднаннях покоління 2025 це `subscribe_resource(uri)` / `unsubscribe_resource(uri)` — пара методів, яку `MCPServer` не реалізує, тож у протоколі 2026-07-28 (де цих дій уже немає) запит повертає `-32601`, *Method not found*. Заміна у версії 2026 — потік `subscriptions/listen`, який `MCPServer` *таки* обслуговує — `server_capabilities.resources.subscribe` там дорівнює `True` — а як споживати його через `client.listen(...)`, описано на сторінці **[Підписки](subscriptions.md)** цього розділу.

## Промпти {#prompts}

```python title="client.py" hl_lines="15-20"
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

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` вказує, *який* промпт чи шаблон ви заповнюєте: `PromptReference` або `ResourceTemplateReference`.
* `argument` — це `{"name": ..., "value": ...}`: аргумент і те, що користувач уже встиг набрати.

Відповідь — у `result.completion.values`. Наберіть `"p"` — і сервер поверне `['poetry']`. Серверний бік, а також те, як обробник використовує *інші*, уже заповнені аргументи, щоб звузити свої пропозиції, — на сторінці **[Автодоповнення](../servers/completions.md)**.

## Пагінація {#pagination}

Кожен метод `list_*` приймає іменований аргумент `cursor=`, а кожен результат містить `next_cursor`. Коли `next_cursor` дорівнює `None`, у вас є все.

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

Цей цикл коректний для будь-якого сервера. `MCPServer` повертає все однією сторінкою, тож `next_cursor` дорівнює `None` і цикл виконується один раз — саме тому більшість коду його ніколи не пише. Сервери, що справді розбивають результати на сторінки, і правила, яким підкоряються курсори, — на сторінці **[Пагінація](../advanced/pagination.md)**.

## У тестах {#in-tests}

`Client(mcp)` без процесу й без порту — це вже тестова обв'язка для вашого сервера.

Саме для цього є один прапорець конструктора: `Client(mcp, raise_exceptions=True)`. Він діє лише на з'єднаннях у пам'яті, а пояснює його й будує навколо нього весь підхід сторінка **[Тестування](../get-started/testing.md)**.

## Підсумки {#recap}

* `Client(x)` під'єднується в пам'яті до об'єкта сервера, через Streamable HTTP — до рядка з URL і через транспорт — до всього іншого.
* `async with` — це весь життєвий цикл. Усередині нього `server_capabilities` і `protocol_version` уже заповнені; `server_info` та `instructions` — теж, якщо сервер їх надає.
* `list_tools()` дає `name`, `title`, `description` та `input_schema` кожного інструмента.
* `call_tool()` повертає `content` для моделі, `structured_content` для вашого коду та `is_error`. Інструмент, що викидає виняток, — це результат, а не виняток.
* `content` — об'єднання типів блоків; звужуйте тип через `isinstance`, перш ніж читати.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt` і `complete` доповнюють набір дій.
* Кожен `list_*` приймає `cursor=`; повторюйте цикл, доки `next_cursor` не стане `None`.

Про що сервер може попросити *клієнта* і як на це відповідати — на сторінці **[Колбеки клієнта](callbacks.md)**.
