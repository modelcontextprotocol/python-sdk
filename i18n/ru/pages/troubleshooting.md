---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# Устранение неполадок {#troubleshooting}

Каждый заголовок на этой странице — точный текст ошибки, которую выдаёт SDK, а под ним — что она означает и как её исправить одним действием. Найдите здесь последнюю строку своей трассировки (или лога сервера) поиском по странице в браузере и читайте только эту запись.

Несколько записей опираются на один и тот же сервер. Один инструмент и один шаблонный ресурс, каждый из которых выбрасывает исключение для города, которого не знает:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

Ошибки, которые цитирует эта страница, настоящие: собственный набор тестов SDK воспроизводит каждую из них.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

Это не ошибка MCP. Это шум от anyio, а настоящая ошибка — **последняя строка** вывода.

`Client.__aenter__` запускает группу задач. anyio оборачивает всё, что покидает группу задач, в `ExceptionGroup`, поэтому *любое* исключение, вышедшее за пределы блока `async with Client(...)`, каким бы оно ни было, приходит внутри такой группы:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

С этим нужно сделать две вещи:

1. **Читайте снизу.** `MCPError: No forecast for 'Atlantis'.` — это и есть сбой; ищите на этой странице *его* текст.
2. **Перехватывайте внутри блока.** `ExceptionGroup` появляется только тогда, когда исключение *покидает* `async with`. Если перехватить его внутри, тот же сбой — обычный `MCPError`, без всякой группы:

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    Сбой во время *подключения* (неверный URL, незапущенный сервер, `421` ниже
    на этой странице) выходит из самого `async with`, так что никакого «внутри», где его можно
    было бы перехватить, нет. В таких случаях читайте низ группы.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` лишь создаёт объект. До `async with` ничего не подключается, поэтому каждый метод отказывает:

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

Войдите в него. `__aenter__` — это и есть подключение:

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` — это отключение, и именно поэтому нет `client.close()`, который можно забыть вызвать. Страница **[Тестирование](get-started/testing.md)** построена ровно на этом шаблоне.

## `Error executing tool <name>: <message>` и `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

Перед вами **результат**, а не исключение. `call_tool` ничего не выбросил и никогда не выбросит для инструмента, завершившегося с ошибкой.

Вызовите `forecast` для города, которого сервер не знает, — и исключение, которое он выбрасывает, вернётся вместе с запросом, помеченным как *успешный*:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` — та же форма для имени, которое сервер никогда не регистрировал, а неправильный аргумент отклоняется так же — по входной схеме инструмента, ещё до того, как ваша функция запустится.

Исправление — на стороне клиента: **проверяйте `result.is_error`**. `try/except` вокруг `call_tool` не поймает ничего из этого, потому что ловить нечего. Так задумано, и это самая полезная мысль на всей странице, которую стоит усвоить: вызов выбрала *модель*, поэтому именно модель получает сообщение и шанс попробовать снова. Подробнее — на странице **[Обработка ошибок](servers/handling-errors.md)**, включая путь через `MCPError`, который *действительно* выбрасывает исключение.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

Вы написали `@mcp.tool` вместо `@mcp.tool()`. `tool()` — это *фабрика* декораторов: без скобок Python передаёт вашу функцию в её параметр `name=`.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

Добавьте скобки. `@mcp.resource(...)` и `@mcp.prompt()` говорят то же самое при той же описке.

!!! note
    Исключение выбрасывается при **импорте** модуля, ещё до подключения любого клиента. Поэтому
    у хоста, который показывает ваш сервер как *не запустившийся* (или *отключённый*), а не как
    подключённый с нулём инструментов, именно эта картина: запустите `python server.py` сами и
    прочитайте трассировку. Проверка типов тоже это ловит: функция — недопустимое значение для `name=`.

## `Tool already exists: <name>` {#tool-already-exists-name}

Две регистрации использовали одно и то же имя инструмента. Побеждает **первая**, вторая молча отбрасывается, и единственный сигнал — это предупреждение в *логе сервера*:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` сообщает об одном `forecast`, и это `forecast_today`. Переименуйте один из них. `MCPServer(..., warn_on_duplicate_tools=False)` заглушает предупреждение, не меняя исхода, так что оставьте его включённым. Для ресурсов и промптов действует то же правило и та же строка лога (`Resource already exists:`, `Prompt already exists:`).

## Хост показывает ноль инструментов {#my-host-lists-zero-tools}

Строки ошибки для этого нет, и именно поэтому это трудно искать. SDK никогда не выбрасывает зарегистрированный инструмент из `tools/list`, так что двигайтесь от сервера наружу:

* **Запустился ли сервер вообще?** `@mcp.tool` без скобок выбрасывает исключение при импорте, а упавший сервер в некоторых хостах очень похож на пустой. Запустите `python server.py` сами.
* **Находится ли инструмент на том `mcp`, который запускает хост?** Второй `MCPServer(...)` в другом модуле — это другой, пустой сервер. Проверьте, какой объект на самом деле импортирует команда хоста.
* **Не совпали ли имена у двух инструментов?** Тогда один из них пропал. Ищите `Tool already exists:` в логе сервера.
* **Не устарел ли список у хоста?** Инструмент, добавленный после запуска, доходит только до клиентов, которые обрабатывают `notifications/tools/list_changed`. Грубое, но действенное решение — перезапустить хост.
* **Не записало ли что-нибудь в `stdout` вне окна перенаправления?** Пока сервер обслуживает запросы, SDK перенаправляет *сброшенный из буфера* посторонний вывод stdout в stderr (по возможности: среда, которая подменяет стандартные потоки, обслуживается как есть), но вывод, сброшенный в stdout раньше (эхо скрипта-обёртки, `print()` при импорте в небуферизованном процессе), или буферизованный `print()`, слитый при выходе интерпретатора, попадает в поток протокола, а одной мусорной строки достаточно, чтобы хост разорвал соединение — что некоторые хосты отображают как сервер, в котором ничего нет. Пишите логи через модуль `logging`. Остальной чек-лист на стороне хоста — на странице **[Подключение к настоящему хосту](get-started/real-host.md)**.

«Недопустимого» имени инструмента в этом списке *нет*: имя, не соответствующее правилам, пишет предупреждение в лог, но инструмент всё равно регистрируется и попадает в список.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

Сервер сразу отклонил HTTP-запрос, причём тело ответа — не JSON-RPC, поэтому `Client` на Python не может показать ничего лучше этой заглушки.

Самая частая причина с большим отрывом — только что развёрнутый сервер Streamable HTTP. `streamable_http_app()` (и `mcp.run("streamable-http")`) без `transport_security=` по умолчанию включает **защиту от DNS-rebinding**: принимаются только запросы, у которых заголовок `Host` — localhost. Это правильное значение по умолчанию на ноутбуке и неправильное за настоящим именем хоста:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

Разверните это, направьте на него клиент — и подключение провалится на рукопожатии:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

Слова, которые сервер на самом деле отправил, — `421` и `Invalid Host header` — до вас не доходят: у тела ответа 421 нет `Content-Type: application/json`, поэтому клиент не может его разобрать. Они есть в **логе сервера**, куда и стоит заглянуть дальше:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

Исправление — `transport_security=`. Внесите в список разрешённых то имя хоста, которое вы действительно обслуживаете:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    Вот и всё изменение. Тот же самый клиент теперь подключается, согласовывает `2026-07-28` и
    вызывает `forecast`.

На странице **[Развёртывание и масштабирование](run/deploy.md)** рассказано, что означает каждое поле, разобран случай с обратным прокси и всё остальное, что меняется при развёртывании. А `421 Misdirected Request` / `Invalid Host header`, сразу ниже, — тот же сбой, увиденный с другой стороны.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

Это `Server returned an error response`, увиденный из чего угодно, кроме `Client` на Python: curl, вкладка сети в браузере, журнал доступа обратного прокси или другой SDK.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` — это собственная поясняющая фраза HTTP для этого статуса; `Invalid Host header` — тело ответа SDK; а `Client` на Python отображает то же событие как `Server returned an error response`. Все три — один и тот же отказ. Проверка выполняется по **заголовку `Host`, который несёт запрос**, а не по адресу, к которому привязан сервер, поэтому обратный прокси, пересылающий публичное имя хоста, натыкается на неё точно так же, как прямой клиент.

Исправление — тот же `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`, показанный в разделе `Server returned an error response`. Два его пограничных момента стоит назвать:

* Элемент `allowed_hosts` — это точная строка. `"mcp.example.com"` совпадает с заголовком `Host` без порта, а `"mcp.example.com:*"` — с любым явно указанным портом. Укажите оба.
* `403` с телом `Invalid Origin header` — родственная проверка заголовка `Origin`. Она срабатывает только для браузеров (больше ничто не отправляет `Origin`), а `allowed_origins=` — её список разрешённых.

Подробнее — на странице **[Развёртывание и масштабирование](run/deploy.md)**, в том числе о том, когда отключить проверку — это честная конфигурация.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

Ваше MCP-приложение смонтировано внутри другого ASGI-приложения, и ничто не запустило его **менеджер сессий**.

`mcp.streamable_http_app()` возвращает Starlette-приложение, чей собственный жизненный цикл (lifespan) запускает менеджер, а `uvicorn server:app` выполняет этот жизненный цикл за вас. Но Starlette **никогда не запускает жизненный цикл смонтированного подприложения**, поэтому, как только приложение оказывается внутри `Mount`, менеджер так и не стартует, и первый же запрос взрывается:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

Сервер запускается. Маршрут разрешается. А затем `uvicorn` печатает это на каждый запрос:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

Клиент видит 500. Исправление — жизненный цикл на приложении-**хосте**, который входит в `mcp.session_manager.run()`:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

Этому посвящена страница **[Добавление в существующее приложение](run/asgi.md)**, включая несколько серверов в одном приложении и FastAPI. Две соседние строки из того же класса:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` Менеджер одноразовый; двойной вход в жизненный цикл одного и того же приложения натыкается на неё.
* `mcp.session_manager` существует только **после** вызова `streamable_http_app()`, поэтому сначала постройте маршруты, а к менеджеру обращайтесь только внутри жизненного цикла.

## `MCPError: Session not found` {#mcperror-session-not-found}

Сервер не узнаёт `Mcp-Session-Id`, который отправил клиент, — почти всегда потому, что сервер **перезапустился** (или вас направили на другой экземпляр). Сессии живут в памяти одного этого процесса.

Искать ошибку в сервере незачем. HTTP-ответ — `404`, тело которого — *настоящий* JSON-RPC, поэтому, в отличие от `421` выше, `Client` на Python показывает его дословно:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

Исправление — переподключиться: выйти из блока `async with Client(...)` и войти в новый, который согласует свежую сессию. Для долгоживущего клиента это означает перехватывать `MCPError` вокруг вызовов и переподключаться по этому сообщению, а не повторять попытки внутри мёртвой сессии.

Если это происходит *без* перезапуска, значит, у вас больше одного воркера без закрепления сессий за ними: каждый воркер держит собственную таблицу сессий, поэтому запрос, направленный не на тот воркер, оказывается здесь. Эта история и два её решения (маршрутизация с привязкой сессий или `stateless_http=True`) — на страницах **[Развёртывание и масштабирование](run/deploy.md)** и **[Обслуживание клиентов старого поколения](run/legacy-clients.md)**.

Для оператора сервера соответствующая строка лога — `Rejected request with unknown or expired session ID: <id>`. Она пишется на уровне `INFO`, поэтому при обычном пороге `WARNING` её не видно. Видеть её пачками сразу после развёртывания — нормально: все подключённые клиенты переподключаются.

## `MCPError: Method not found` {#mcperror-method-not-found}

Одна сторона отправила JSON-RPC-запрос, для которого у другой нет обработчика, и `e.error.data` называет метод. Обычная причина — **несовпадение поколений**: метод, который есть в одной ревизии протокола и отсутствует в другой, отправлен собеседнику не того поколения — например, `resources/subscribe` поколения `2025`, пришедший на подключение `2026-07-28`, или `subscriptions/listen`, существующий только в `2026`, отправленный клиентом, закреплённым на `mode="legacy"`. Карта того, какая сторона на чём говорит, — на странице **[Версии протокола](protocol-versions.md)**, а другая честная причина (необязательная возможность, для которой вы так и не зарегистрировали обработчик) — на странице **[Автодополнение](servers/completions.md)**.

Одна вещь эту ошибку **не** вызывает, хотя и представляет собой запрос, который современный протокол удалил: инструмент, вызывающий `ctx.elicit()` на подключении `2026-07-28`. Сервер вообще отказывается *отправлять* этот запрос, так что вместо этого вы получаете `Cannot send 'elicitation/create': ...`, ниже на этой странице.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

Сервер хочет что-то спросить у пользователя, а этот клиент никогда не говорил, что его можно спрашивать.

Резолвер элицитации (elicitation) отказывает заранее, если подключённый клиент не объявил элицитацию через формы, и `e.error.data` называет ровно то, чего не хватает:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

Передайте `elicitation_callback=` в `Client(...)`. Регистрация колбэка *и есть* объявление возможности; второго переключателя нет:

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

На странице **[Колбэки клиента](client/callbacks.md)** перечислены остальные (`sampling_callback`, `list_roots_callback`), каждый из которых точно так же служит объявлением.

!!! info
    `-32021` — это `MISSING_REQUIRED_CLIENT_CAPABILITY`, один из трёх кодов ошибок, которые
    добавляет спецификация 2026-07-28. Ни один из них не класс исключения: все они приходят как
    `MCPError`, и смотреть нужно в `e.error.code`. Константы экспортирует `mcp.types`. Два других —
    `-32020` `HEADER_MISMATCH` (HTTP-заголовок расходится с телом запроса, которое он сопровождает)
    и `-32022` `UNSUPPORTED_PROTOCOL_VERSION` (запрос назвал версию, на которой этот сервер не
    говорит). Соответствующий спецификации SDK-клиент не может выдать ни одну из них, так что,
    если вы такую видите, ищите то, что переписывает запросы между вашим клиентом и вашим сервером.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

Тот же пробел, что и `Client did not declare the form elicitation capability ...`, но в формулировке тех путей, которые не проверяют заранее: серверу нужен был ответ на элицитацию, а подключённый клиент не зарегистрировал `elicitation_callback`.

Это сообщение приходит от `ctx.elicit()` на подключении старого поколения, а на любом подключении вообще — от возвращённого многораундового (multi-round-trip) вопроса (**[Многораундовые запросы](handlers/multi-round-trip.md)**), который дошёл до клиента без колбэка, способного на него ответить. Исправление то же: передайте `elicitation_callback=` в `Client(...)`. Не существует варианта «пользователя не спросили», который ваш инструмент получил бы как `decline`; клиент, которого нельзя спросить, — это провалившийся вызов, так что проектируйте инструменты с расчётом на это.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

Обработчик попытался обратиться к клиенту посреди запроса на подключении, где у вызова нет канала, способного донести запрос от сервера. В такое положение вызов ставят три конфигурации сервера.

**Подключение `2026-07-28`: любой транспорт, всегда.** В современном протоколе вообще нет запросов, инициируемых сервером, поэтому сервер отказывает ещё до того, как что-либо отправлено. `ctx.elicit()` внутри инструмента — классический способ с этим столкнуться (в самом первом тесте в памяти, поскольку `Client(server)` согласовывает `2026-07-28`, не спрашивая), и передача `elicitation_callback=` ничего не меняет: никакой запрос до клиента не доходит, так что отвечать ему не на что:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**Подключение старого поколения к серверу с `stateless_http=True`.** Отсутствие состояния означает, что каждый запрос — отдельный мир: ни сессии, ни потока от сервера к клиенту, а значит, `elicitation/create` (как и `sampling/createMessage` или `roots/list`) отправить некуда даже для того поколения, в котором они есть:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**Подключение старого поколения к серверу с `json_response=True`.** На `POST` отвечают одним JSON-телом, а одно тело несёт только ответ, поэтому потока, привязанного к запросу, который нужен `ctx.elicit()` посреди запроса, здесь тоже нет. Сессия, её `Mcp-Session-Id` и её отдельный поток по-прежнему на месте; исчез только канал, привязанный к запросу.

Сообщение называет метод, который не удалось отправить. Сервер выбрасывает класс `NoBackChannelError`, но по сети передаётся только базовый `MCPError`, поэтому последняя строка вашей трассировки — приведённое выше предложение, а не имя класса.

Для клиента `2026-07-28` исправление во всех трёх случаях одно: не обращайтесь к клиенту посреди вызова. Перенесите вопрос в **резолвер** (или сами верните `InputRequiredResult`) — и он станет частью *ответа*, который способно донести любое подключение:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

Тот же вопрос, тот же `elicitation_callback` на клиенте. Разница внутри: резолвер позволяет серверу *вернуть* вопрос из вызова, а не проталкивать его, так что от сервера к клиенту ничего никогда не идёт. Этого достаточно для любого клиента `2026-07-28`, в какой бы из трёх конфигураций ни был сервер. Клиенту *старого поколения* одной лишь переделки мало: в `2025-11-25` нет способа вернуть вопрос, поэтому на подключении старого поколения резолвер по-прежнему отправляет `elicitation/create` по каналу, привязанному к запросу, и по-прежнему нуждается в сервере, который этот канал сохраняет, — без `stateless_http=True` и без `json_response=True`. Резолверы описаны на странице **[Элицитация](handlers/elicitation.md)**; что происходит в передаваемых данных — на странице **[Многораундовые запросы](handlers/multi-round-trip.md)**.

!!! check
    Инструмент с `ctx.elicit()` не ошибочный — он *из поколения до 2026*. Подключитесь с `mode="legacy"`
    (классическое рукопожатие `initialize`, спецификация `2025-11-25` и более ранние) к серверу без
    `stateless_http=True` и без `json_response=True` — и он заработает, потому что там канал от
    сервера к клиенту существует.
    Что есть в каждой версии — на странице **[Версии протокола](protocol-versions.md)**.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

Сервер не смог проверить токен `requestState`, который клиент вернул ему обратно, и отклонил раунд.

`requestState` — непрозрачный токен возобновления, который **[многораундовый](handlers/multi-round-trip.md)** вызов несёт между этапами. `MCPServer` запечатывает его на выходе и проверяет каждый возврат, причём проверяет *каждый* входящий `request_state` в `tools/call`, `prompts/get` и `resources/read`, даже для обработчика, который сам никогда его не выпускает. Поэтому токен, который этот процесс не запечатывал, отклоняется, куда бы он ни попал:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

Сообщение намеренно неизменно: по сети никогда не раскрывается, какая проверка не прошла. Причина уходит в **лог сервера**, и прочитать его — вот и вся диагностика:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

Причины, которые вы реально увидите:

* **`unknown key`** — та, что важна. Ключ запечатывания по умолчанию генерируется при запуске процесса, поэтому повторная попытка, попавшая на **другой воркер**, на другой экземпляр за балансировщиком нагрузки или на тот же сервер **после перезапуска**, была запечатана ключом, которого у этого процесса никогда не было. Это не злоумышленник; это значение по умолчанию столкнулось с более чем одним процессом.
* **`audience`**: токен запечатан экземпляром с *другим именем сервера*. Имя по умолчанию служит в печати значением audience, поэтому у всего парка серверов должно совпадать имя (или быть задан явный `RequestStateSecurity(audience=...)`), а не только ключи.
* **`expired`**: раунд занял больше, чем `ttl` печати — 600 секунд, причём на раунд, а не на вызов.
* **`malformed`** / **`codec error`**: токен изменили при передаче, или он вовсе никогда не был запечатанным токеном.
* **`request binding`**: токен вернулся с другим инструментом, другими аргументами или другим методом.

Исправление для нескольких процессов — один аргумент (*одни и те же* `keys` на каждом экземпляре) плюс одна вещь, которая вовсе не аргумент: одно и то же *имя* сервера (или явный общий `audience=`).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` запечатывает; проверяет каждый ключ из списка — именно это делает возможной ротацию без простоя. На странице **[Многораундовые запросы](handlers/multi-round-trip.md#protecting-requeststate)** объясняется, что защищает печать, и приведена последовательность ротации, а на странице **[Развёртывание и масштабирование](run/deploy.md)** разобран весь сбой с двумя воркерами и его исправление из двух частей.

!!! tip
    `keys=[...]` сразу отклоняет слабый ключ, причём с необычно полезным сообщением:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    Сделайте, как сказано.

## Всё ещё не получается? {#still-stuck}

* Если сообщения, которое выдал SDK, на этой странице нет, это ошибка документации, о которой стоит сообщить отдельно.
* Поищите в [трекере задач](https://github.com/modelcontextprotocol/python-sdk/issues): большинство строк ошибок, которые там встречаются, кто-то уже подробно описал.
* Ничего не нашли? [Откройте задачу](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) с полной трассировкой или спросите в [#python-sdk-dev на Discord-сервере MCP Contributors](https://discord.gg/6CSzBmMkjX).

## Итоги {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` — никогда не сама ошибка. Читайте **последнюю строку**; перехват `MCPError` *внутри* блока `async with Client(...)` полностью избавляет от обёртки.
* `call_tool` не выбрасывает исключение для инструмента, завершившегося с ошибкой. `Error executing tool ...` и `Unknown tool: ...` — это результаты: проверяйте `result.is_error`.
* `Client must be used within an async context manager` -> используйте `async with`. `Use @tool() instead of @tool` -> добавьте скобки.
* `Tool already exists:` в логе сервера — единственный признак того, что два одноимённых инструмента схлопнулись в один.
* Один 421, три написания: `Server returned an error response` (`Client` на Python), `421 Misdirected Request` / `Invalid Host header` (всё остальное), `Invalid Host header: <host>` (лог сервера). Исправление: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> смонтированное приложение, жизненный цикл хоста которого так и не вошёл в `mcp.session_manager.run()`.
* `Session not found` -> сервер перезапустился; переподключитесь.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` нужен канал от сервера к клиенту: у подключения `2026-07-28` его не бывает никогда, `stateless_http=True` отнимает его у подключений старого поколения, а `json_response=True` отнимает канал, привязанный к запросу. Используйте резолвер (клиенту старого поколения к тому же нужен сервер, который сохраняет канал). Соседнее `Method not found` — это запрос метода, которого нет в ревизии протокола другой стороны.
* `Client did not declare the form elicitation capability ...` и `Elicitation not supported` -> у клиента не хватает `elicitation_callback=`.
* `Invalid or expired requestState` никогда не говорит по сети, почему. Лог сервера говорит; `unknown key` означает, что `RequestStateSecurity(keys=[...])` нужно сделать общим для всех воркеров.
