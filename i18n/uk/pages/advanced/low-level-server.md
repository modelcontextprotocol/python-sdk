---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# Низькорівневий Server {#the-low-level-server}

`@mcp.tool()` — це шар. Під ним лежить другий серверний клас, `Server`, який говорить «сирим» MCP: ви передаєте йому об'єкти протоколу, а він надсилає їх мережею без змін.

`MCPServer` побудований поверх нього. Спускатися на рівень нижче варто тоді, коли зручний шар заважає:

* Потрібно віддати **точну** схему (завантажену з файлу, згенеровану з бази даних), а не виведену з сигнатури Python.
* Потрібен повний контроль над результатом: `_meta`, `is_error`, кожен ключ `structured_content`.
* Потрібно обробити метод, якого MCP не визначає.

Для всього іншого залишайтеся на `MCPServer`.

## Той самий інструмент, вручну {#the-same-tool-by-hand}

Це інструмент `search_books`, який сторінка **[Інструменти](../servers/tools.md)** пише дев'ятьма рядками `@mcp.tool()`, — тільки без синтаксичного цукру:

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

Змінилися три речі, і вони й складають увесь низькорівневий API:

* **Обробники — це параметри конструктора.** `on_list_tools=` і `on_call_tool=` передаються в `Server(...)`. Декораторів тут немає, і кожен обробник має однакову форму: `async (ctx, params) -> result`.
* **Вхідну схему пишете ви.** `Tool.input_schema` — це звичайний `dict` із JSON Schema. Ніхто не виводить її з анотацій типів, бо анотацій типів, з яких можна було б її вивести, немає.
* **Результат будуєте ви.** `CallToolResult(content=[TextContent(...)])`, вручну. Нічого не загортається, не перетворюється й не виводиться з анотації значення, що повертається.

`params` — це розібраний запит: `CallToolRequestParams` дає `.name` і `.arguments`. `ctx` — це `ServerRequestContext`: `ctx.session`, щоб звертатися назад до клієнта, `ctx.lifespan_context`, `ctx.request_id` і `ctx.meta` — вхідні `_meta` запиту.

!!! info
    Якщо ви працювали з FastAPI, це співвідношення вам уже знайоме. `MCPServer` — це шар декораторів і анотацій типів; `Server` — це Starlette під ним. Вони не суперники: `MCPServer` створює `Server` і реєструє на ньому саме такі обробники.

### Спробуйте самі {#try-it}

Inspector тут не допоможе: `mcp dev` і `mcp run` приймають лише `MCPServer`. `Client`, що працює в пам'яті, до цього байдужий: низькорівневий `Server` він приймає так само, як і `MCPServer`:

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

Той самий текст, що його видавала версія з `@mcp.tool()`. Дві чесні відмінності:

* `result.structured_content` дорівнює `None`. Високорівневий сервер загортає `-> str` у `{"result": ...}` за вас; тут ніхто не будує того, чого не побудували ви.
* `list_tools` повертає схему, яку набрали **ви**, символ у символ. У високорівневій версії на кожній властивості було `"title": "Query"`, а в корені — `"title": "search_booksArguments"`: артефакти Pydantic. Тут, якщо щось є в переданих даних, — це ви його туди поклали.

## Ніхто нічого не перевіряє за вас {#nothing-is-checked-for-you}

`MCPServer` відхиляє хибний аргумент ще до того, як ваша функція запуститься, перевіряючи виклик за схемою, яку сам згенерував (**[Інструменти](../servers/tools.md)**).

`Server` цього не робить. Ваша `input_schema` *оголошується* клієнтові; вона ніколи не *застосовується* до `params.arguments`.

!!! check
    Викличте `search_books` без `limit` — і ваш `args["limit"]` викине `KeyError`. Клієнт побачить:

    ```text
    MCPError: Internal server error
    ```

    Помилка JSON-RPC з кодом `-32603` і навмисно загальним повідомленням: SDK не видасть ваш traceback віддаленій стороні, що викликає. Модель так і не дізнається, що зробила не так, тож не зможе повторити спробу. (У тесті `raise_exceptions=True` натомість показує справжній виняток; див. **[Тестування](../get-started/testing.md)**.)

Це узагальнюється. Виняток, викинутий із низькорівневого обробника, — це **завжди** помилка протоколу й ніколи — результат інструмента з `is_error=True`. Якщо потрібно, щоб модель прочитала про невдачу й відновилася, перевіряйте `params.arguments` самі й повертайте `CallToolResult(content=[TextContent(...)], is_error=True)`. Обом видам невдач присвячена сторінка **[Обробка помилок](../servers/handling-errors.md)**.

## Два інструменти, один обробник {#two-tools-one-handler}

`on_call_tool` — єдина точка входу для всіх інструментів сервера. Маршрутизуєте за `params.name`:

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` оголошує обидва. `call_tool` диспетчеризує за іменем.
* Гілка `else` важлива: `Server` спокійно передасть `tools/call` з іменем, якого ви ніколи не оголошували, просто у ваш обробник. Виняток там перетворює виклик на ту саму `-32603`, що й вище.

## Структурований вивід, вручну {#structured-output-by-hand}

Оголосіть `output_schema` на `Tool` і покладіть `structured_content` у результат. І те, й інше — ваше:

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

Викличте його — і результат міститиме обидва подання:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

Блок `_meta` — це ідентифікаційна позначка сервера: SDK додає його до кожного результату покоління 2026 разом із `version` з конструктора (сервер, який її не задав, повідомляє порожній рядок). Сервер, який не повинен себе ідентифікувати, може прибрати цей ключ за допомогою middleware, який володіє результатами, що повертає.

Сервер ніколи не порівнює ці два поля. `Client` цього SDK — порівнює: поверніть `structured_content`, що не відповідає оголошеній вами `output_schema`, і `call_tool` викине `RuntimeError`, який починається з `Invalid structured content returned by tool search_books` і далі цитує помилку `jsonschema`. Пообіцяти схему легко; дотримати її — ваша справа. Уся драбина типів повернення та схем — на сторінці **[Структурований вивід](../servers/structured-output.md)**.

## `_meta`: для застосунку, а не для моделі {#\_meta-for-the-application-not-the-model}

`content` — це частина відповіді, яку читає модель. `structured_content` — та сама відповідь у вигляді типізованих даних. `_meta` — третій канал: дані, що їдуть разом із результатом для **клієнтського застосунку** і взагалі не є частиною відповіді.

Використовуйте його для ідентифікаторів записів, ідентифікаторів трасування — усього, що потрібно вашому UI, але не потрібно промпту:

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* Конструюєте його як `_meta=` — це ім'я в переданих даних. Клієнт зчитує його як `result.meta`.
* Додавайте до ключів простір імен (`bookshop/record_ids`). Ключі `io.modelcontextprotocol/*` зарезервовано протоколом.

!!! warning
    `_meta` — це домовленість між вами й клієнтським застосунком, а не гарантія того, що дійде
    до моделі. Що показувати, вирішує хост. Ніколи не кладіть секрет у жодну частину результату інструмента.

## Можливості випливають з обробників {#capabilities-follow-your-handlers}

`Server` оголошує рівно ті сімейства методів, для яких ви дали йому обробники. `Bookshop` вище передає `on_list_tools` і `on_call_tool` і більше нічого, тож клієнт, що до нього під'єднується, бачить:

```json
{"tools": {"listChanged": false}}
```

Жодних `resources`, жодних `prompts`: за ними нічого не стоїть. Передайте `on_list_prompts` — і з'явиться `prompts`; передайте `on_completion` — і з'явиться `completions`.

`MCPServer` завжди оголошує інструменти, ресурси й промпти, зареєстрували ви щось чи ні, бо його менеджери існують завжди. Тут же оголошення — це *і є* виклик конструктора.

## Життєвий цикл як параметр типу {#the-lifespan-generic}

`Server` узагальнений за типом, який видає його життєвий цикл (lifespan). Анотуйте його один раз — і об'єкт буде типізованим усюди, де з'являється:

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* Життєвий цикл — це `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`; `@asynccontextmanager` над `async`-генератором дає саме це.
* Усе, що він видає через `yield`, стає `ctx.lifespan_context`, а оскільки обробники анотовано як `ServerRequestContext[Catalog]`, `.search(...)` автодоповнюється й проходить перевірку типів.
* У нього входять один раз під час старту сервера й виходять один раз під час зупинки. Запуск, завершення та версія тієї самої ідеї в `MCPServer` — на сторінці **[Життєвий цикл](../handlers/lifespan.md)**.

Без `lifespan=` `ctx.lifespan_context` — порожній `dict`.

## Власний метод {#a-method-of-your-own}

Конструктор покриває методи, які визначає MCP. `add_request_handler` покриває все інше:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* Перший аргумент — рядок методу. Для сповіщень є близнюк — `add_notification_handler`.
* `params_type` — це модель, за якою вхідні `params` перевіряються **до** запуску вашого обробника, тож власні методи *отримують* перевірку, якої інструменти не мають. Успадковуйтеся від `RequestParams`, щоб поле `_meta` розбиралося так само, як у кожного іншого методу.
* Обробник повертає `BaseModel`, `dict` або `None`. SDK серіалізує це в результат JSON-RPC.

Одне чесне застереження: високорівневий `Client` має дієслова лише для методів, які визначає MCP, тож `client.reindex()` немає. Вендорний метод — для сторони, яка вже знає про його існування: клієнта, який ви теж постачаєте, або іншого вашого сервісу, що говорить JSON-RPC.

Один метод забрати собі не можна:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

Рукостискання належить засобу запуску сервера. `server/discover`, `ping` та всі інші вбудовані методи можна замінювати.

!!! tip
    `Server.middleware`, згаданий у цій помилці, обгортає **кожне** вхідне повідомлення, включно з `initialize`. Якщо мета — спостерігати за трафіком чи переписувати його, а не відповідати на новий метод, почніть із **[Middleware](middleware.md)**.

## Інші обробники {#the-other-handlers}

Кожен із них — одна ідея, для якої у вас тепер є словник; кожна має власну сторінку.

* `on_call_tool`, `on_get_prompt` і `on_read_resource` можуть повернути `InputRequiredResult` замість звичайного результату, щоб призупинити виклик і попросити клієнта про введення; див. **[Багатораундові запити](../handlers/multi-round-trip.md)** (multi-round-trip). Як і годиться цьому рівню, нічого не встановлюється за вас: якщо `MCPServer` за замовчуванням запечатує `requestState`, то тут заданий вами `request_state` передається мережею точно так, як написано, доки ви не ввімкнете захист через `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))`: один рядок (обидва імені імпортуються з `mcp.server.request_state`) — і отримуєте те саме запечатування й перевірку, що їх виконує `MCPServer` (**[Захист `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion` — та сама форма `(ctx, params) -> result` для інших примітивів.
* `on_subscriptions_listen` обслуговує потік `subscriptions/listen` версії 2026-07-28. Передайте `ListenHandler`, побудований поверх `SubscriptionBus`, і публікуйте події в шину з інших обробників; повну композицію див. на сторінці **[Підписки](../handlers/subscriptions.md)**.
* `server.streamable_http_app()` повертає той самий Starlette-застосунок, що й у `MCPServer`; розгортайте його так, як **[Запуск сервера](../run/index.md)** розгортає будь-який інший ASGI-застосунок. `server.run(transport=...)` тут немає: `server.run(read_stream, write_stream, server.create_initialization_options())` веде одне з'єднання через пару потоків, і цей один рядок — оце й усе.

## Підсумки {#recap}

* Низькорівневий `Server` приймає обробники як **параметри конструктора** `on_*`; кожен обробник — це `async (ctx, params) -> result`.
* Ви пишете словник `input_schema` і будуєте `CallToolResult`. Нічого не виводиться, не загортається й не перевіряється за вас.
* Виняток в обробнику — це помилка протоколу `-32603`. Помилка інструмента, яку може прочитати модель, — це `CallToolResult` з `is_error=True`, який повертаєте **ви**.
* `_meta` в результаті адресовано клієнтському застосунку, а не моделі.
* `Server[T]` узагальнений за тим, що видає його життєвий цикл; `ctx.lifespan_context` — це типізований `T`.
* `add_request_handler(method, params_type, handler)` обслуговує будь-який метод. `initialize` зарезервовано.
* Можливості, які оголошує `Server`, виводяться з того, які обробники ви зареєстрували.

`Client(server)` поводився з обома серверами однаково, бо вони *і є* тим самим протоколом — у цьому й увесь сенс. Наступний шар нижче — взагалі не клас: це **[Middleware](middleware.md)**.
