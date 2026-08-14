---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# Низкоуровневый Server {#the-low-level-server}

`@mcp.tool()` — это слой. Под ним лежит второй класс сервера, `Server`, который говорит на чистом MCP: вы передаёте ему объекты протокола, и он отправляет их по сети без изменений.

`MCPServer` построен поверх него. Спускаться ниже стоит тогда, когда слой удобства мешает:

* Нужно отдать **точную** схему (загруженную из файла, сгенерированную из базы данных), а не выведенную из сигнатуры Python.
* Нужен полный контроль над результатом: `_meta`, `is_error`, каждый ключ `structured_content`.
* Нужно обработать метод, который MCP не определяет.

Во всех остальных случаях оставайтесь на `MCPServer`.

## Тот же инструмент, вручную {#the-same-tool-by-hand}

Это инструмент `search_books`, который на странице **[Инструменты](../servers/tools.md)** занимает девять строк с `@mcp.tool()`, — но без синтаксического сахара:

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

Изменились три вещи, и это весь низкоуровневый API:

* **Обработчики — параметры конструктора.** `on_list_tools=` и `on_call_tool=` передаются в `Server(...)`. Декораторов здесь нет, и у каждого обработчика одна и та же форма: `async (ctx, params) -> result`.
* **Входную схему пишете вы.** `Tool.input_schema` — обычный `dict` с JSON Schema. Никто не выводит её из аннотаций типов, потому что аннотаций типов, из которых её можно было бы вывести, нет.
* **Результат собираете вы.** `CallToolResult(content=[TextContent(...)])`, вручную. Ничего не оборачивается, не преобразуется и не выводится из аннотации возвращаемого значения.

`params` — это разобранный запрос: `CallToolRequestParams` даёт `.name` и `.arguments`. `ctx` — это `ServerRequestContext`: `ctx.session` для обращения к клиенту, `ctx.lifespan_context`, `ctx.request_id` и `ctx.meta` — входящий `_meta` запроса.

!!! info
    Если вы работали с FastAPI, это соотношение вам уже знакомо. `MCPServer` — слой с декораторами и аннотациями типов; `Server` — это Starlette под ним. Они не конкуренты: `MCPServer` создаёт `Server` и регистрирует на нём ровно такие же обработчики.

### Попробуйте сами {#try-it}

Inspector здесь не поможет: `mcp dev` и `mcp run` принимают только `MCPServer`. Клиенту `Client`, работающему в памяти, всё равно — он принимает низкоуровневый `Server` точно так же, как `MCPServer`:

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

Тот же текст, что выдала версия с `@mcp.tool()`. Два честных отличия:

* `result.structured_content` равен `None`. Высокоуровневый сервер сам оборачивает `-> str` в `{"result": ...}`; здесь никто не соберёт то, чего не собрали вы.
* `list_tools` возвращает схему, которую набрали **вы**, символ в символ. В высокоуровневой версии у каждого свойства было `"title": "Query"`, а в корне — `"title": "search_booksArguments"`: артефакты Pydantic. Здесь всё, что есть в передаваемых данных, положили туда вы.

## За вас ничего не проверяют {#nothing-is-checked-for-you}

`MCPServer` отклоняет некорректный аргумент ещё до запуска вашей функции, проверяя вызов по сгенерированной им схеме (**[Инструменты](../servers/tools.md)**).

`Server` этого не делает. Ваша `input_schema` *объявляется* клиенту, но никогда не *применяется* к `params.arguments`.

!!! check
    Вызовите `search_books` без `limit`, и ваше `args["limit"]` выбросит `KeyError`. Клиент увидит:

    ```text
    MCPError: Internal server error
    ```

    Ошибка JSON-RPC с кодом `-32603` и намеренно общим сообщением: SDK не станет выдавать вашу трассировку удалённому вызывающему. Модель так и не узнает, что сделала не так, и не сможет повторить попытку. (В тесте `raise_exceptions=True` вместо этого показывает настоящее исключение; см. **[Тестирование](../get-started/testing.md)**.)

Это обобщается. Исключение, выброшенное из низкоуровневого обработчика, — **всегда** ошибка протокола и никогда не результат инструмента с `is_error=True`. Если хотите, чтобы модель прочитала описание сбоя и восстановилась, проверяйте `params.arguments` сами и возвращайте `CallToolResult(content=[TextContent(...)], is_error=True)`. Этим двум видам сбоев посвящена страница **[Обработка ошибок](../servers/handling-errors.md)**.

## Два инструмента, один обработчик {#two-tools-one-handler}

`on_call_tool` — единственная точка входа для всех инструментов сервера. Маршрутизация идёт по `params.name`:

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` объявляет оба. `call_tool` выбирает ветку по имени.
* Ветка `else` важна: `Server` без возражений передаст `tools/call` с именем, которое вы никогда не объявляли, прямо в ваш обработчик. Исключение там превращает вызов в тот же `-32603`, что и выше.

## Структурированный вывод, вручную {#structured-output-by-hand}

Объявите `output_schema` в `Tool` и поместите `structured_content` в результат. И то и другое — ваше:

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

Вызовите его, и результат несёт оба представления:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

Блок `_meta` — это идентификационная отметка сервера: SDK добавляет её в каждый результат поколения 2026, с `version` из конструктора (сервер, который её не задал, сообщает пустую строку). Сервер, который не должен себя называть, может убрать этот ключ с помощью middleware — оно владеет результатами, которые возвращает.

Сервер никогда не сравнивает эти два поля. А вот `Client` из этого SDK сравнивает: верните `structured_content`, не соответствующий объявленной вами `output_schema`, и `call_tool` выбросит `RuntimeError`, который начинается с `Invalid structured content returned by tool search_books` и дальше цитирует ошибку `jsonschema`. Пообещать схему легко; соблюдать её — ваша забота. Вся лестница возвращаемых типов и схем — на странице **[Структурированный вывод](../servers/structured-output.md)**.

## `_meta`: для приложения, не для модели {#\_meta-for-the-application-not-the-model}

`content` — это та часть ответа, которую читает модель. `structured_content` — тот же ответ в виде типизированных данных. `_meta` — третий канал: данные, которые едут вместе с результатом для **клиентского приложения** и вообще не являются частью ответа.

Используйте его для идентификаторов записей, идентификаторов трассировки — всего, что нужно вашему UI и не нужно промпту:

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* При создании вы пишете `_meta=` — имя, которое идёт по сети. Клиент читает его обратно как `result.meta`.
* Давайте ключам пространство имён (`bookshop/record_ids`). Ключи `io.modelcontextprotocol/*` зарезервированы протоколом.

!!! warning
    `_meta` — это соглашение между вами и клиентским приложением, а не гарантия того, что дойдёт
    до модели. Что отображать, решает хост. Никогда не помещайте секрет ни в одну часть результата инструмента.

## Возможности следуют за обработчиками {#capabilities-follow-your-handlers}

`Server` объявляет ровно те семейства методов, для которых вы передали обработчики. `Bookshop` выше передаёт `on_list_tools` и `on_call_tool` и больше ничего, поэтому подключившийся к нему клиент видит:

```json
{"tools": {"listChanged": false}}
```

Ни `resources`, ни `prompts`: их нечем обеспечить. Передайте `on_list_prompts` — появится `prompts`; передайте `on_completion` — появится `completions`.

`MCPServer` всегда объявляет инструменты, ресурсы и промпты, зарегистрировали вы что-нибудь или нет, потому что его менеджеры существуют всегда. Здесь же объявление — это *и есть* вызов конструктора.

## Дженерик жизненного цикла {#the-lifespan-generic}

`Server` — дженерик по типу, который отдаёт его жизненный цикл (lifespan). Аннотируйте его один раз, и объект будет типизирован везде, где появляется:

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* Жизненный цикл — это `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`; `@asynccontextmanager` на `async`-генераторе даёт ровно это.
* То, что он отдаёт через `yield`, становится `ctx.lifespan_context`, а поскольку обработчики аннотированы как `ServerRequestContext[Catalog]`, `.search(...)` автодополняется и проходит проверку типов.
* Вход в него происходит один раз при запуске сервера, выход — один раз при остановке. Запуск, завершение и версия той же идеи в `MCPServer` — на странице **[Жизненный цикл](../handlers/lifespan.md)**.

Без `lifespan=` значение `ctx.lifespan_context` — пустой `dict`.

## Собственный метод {#a-method-of-your-own}

Конструктор покрывает методы, которые определяет MCP. `add_request_handler` покрывает всё остальное:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* Первый аргумент — строка метода. У уведомлений есть двойник, `add_notification_handler`.
* `params_type` — модель, по которой входящие `params` проверяются **до** запуска вашего обработчика, так что пользовательские методы *получают* ту проверку, которой нет у инструментов. Наследуйтесь от `RequestParams`, чтобы поле `_meta` разбиралось так же, как у любого другого метода.
* Обработчик возвращает `BaseModel`, `dict` или `None`. SDK сериализует это в результат JSON-RPC.

Одна честная оговорка: у высокоуровневого `Client` есть глаголы только для методов, определённых MCP, так что `client.reindex()` не существует. Вендорный метод предназначен для стороны, которая уже знает о его существовании: клиента, который вы тоже поставляете, или другого вашего сервиса, говорящего на JSON-RPC.

Один метод занять нельзя:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

Рукопожатие принадлежит раннеру. `server/discover`, `ping` и все остальные встроенные методы можно заменять.

!!! tip
    `Server.middleware`, упомянутый в этой ошибке, оборачивает **каждое** входящее сообщение, включая `initialize`. Если нужно наблюдать за трафиком или переписывать его, а не отвечать на новый метод, начните со страницы **[Middleware](middleware.md)**.

## Остальные обработчики {#the-other-handlers}

Каждый из них — одна идея, для которой у вас теперь есть словарь; у каждого своя страница.

* `on_call_tool`, `on_get_prompt` и `on_read_resource` могут вернуть `InputRequiredResult` вместо обычного результата, чтобы приостановить вызов и запросить ввод у клиента; см. **[Многораундовые запросы](../handlers/multi-round-trip.md)**. Верные духу этого уровня, они ничего не устанавливают за вас: там, где `MCPServer` по умолчанию запечатывает `requestState`, здесь заданный вами `request_state` идёт по сети ровно в том виде, в каком написан, пока вы не включите защиту явно: `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))` — одна строка (оба имени импортируются из `mcp.server.request_state`) для точно такого же запечатывания и проверки, какие выполняет `MCPServer` (**[Защита `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion` — та же форма `(ctx, params) -> result` для остальных примитивов.
* `on_subscriptions_listen` обслуживает поток `subscriptions/listen` версии 2026-07-28. Передайте `ListenHandler`, построенный поверх `SubscriptionBus`, и публикуйте события в шину из остальных обработчиков; полная схема компоновки — на странице **[Подписки](../handlers/subscriptions.md)**.
* `server.streamable_http_app()` возвращает то же Starlette-приложение, что и у `MCPServer`; разворачивайте его так же, как страница **[Запуск сервера](../run/index.md)** разворачивает любое другое ASGI-приложение. `server.run(transport=...)` здесь нет: `server.run(read_stream, write_stream, server.create_initialization_options())` ведёт одно подключение по паре потоков, и этой одной строкой всё исчерпывается.

## Итоги {#recap}

* Низкоуровневый `Server` принимает обработчики как **параметры конструктора** `on_*`; каждый обработчик — `async (ctx, params) -> result`.
* Словарь `input_schema` пишете вы, и `CallToolResult` собираете вы. Ничего не выводится, не оборачивается и не проверяется за вас.
* Исключение в обработчике — ошибка протокола `-32603`. Ошибка инструмента, которую может прочитать модель, — это `CallToolResult` с `is_error=True`, который возвращаете **вы**.
* `_meta` в результате адресован клиентскому приложению, а не модели.
* `Server[T]` — дженерик по тому, что отдаёт его жизненный цикл; `ctx.lifespan_context` — типизированный `T`.
* `add_request_handler(method, params_type, handler)` обслуживает любой метод. `initialize` зарезервирован.
* Возможности, которые объявляет `Server`, выводятся из того, какие обработчики вы зарегистрировали.

`Client(server)` обращался с обоими серверами одинаково, потому что это *и есть* один и тот же протокол — в этом весь смысл. Следующий уровень вниз — вообще не класс: это **[Middleware](middleware.md)**.
