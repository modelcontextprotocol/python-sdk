---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# Усунення несправностей {#troubleshooting}

Кожен заголовок на цій сторінці — це точний текст помилки, яку видає SDK; під ним — що вона означає і як її виправити одним рухом. Знайдіть тут останній рядок свого трасування (або лога сервера) пошуком на сторінці у браузері й читайте лише цей пункт.

Кілька пунктів працюють із цим одним сервером. Один інструмент і один шаблонний ресурс, кожен викидає виняток для міста, якого не знає:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

Помилки, які цитує ця сторінка, справжні: власний набір тестів SDK відтворює кожну з них.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

Це не помилка MCP. Це шум від anyio, а справжня помилка — **останній рядок** виводу.

`Client.__aenter__` запускає групу завдань. anyio загортає все, що виходить із групи завдань, в `ExceptionGroup`, тож *кожен* виняток, що залишає блок `async with Client(...)`, хай який він, приходить усередині групи:

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

Із цим варто зробити дві речі:

1. **Читайте знизу.** `MCPError: No forecast for 'Atlantis'.` — це і є збій; шукайте на цій сторінці *його* текст.
2. **Перехоплюйте всередині блоку.** `ExceptionGroup` з'являється лише тоді, коли виняток *виходить* за межі `async with`. Перехоплений усередині, той самий збій — це звичайний `MCPError`, без жодної групи:

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    Збій під час *з'єднання* (неправильний URL, сервер, який не запущено, `421` нижче
    на цій сторінці) виходить із самого `async with`, тож «всередині», де його можна було б
    перехопити, немає. У таких випадках читайте низ групи.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` лише створює об'єкт. До `async with` нічого не під'єднується, тому кожен метод відмовляє:

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

Увійдіть у нього. `__aenter__` — це і є з'єднання:

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` — це від'єднання, тому й немає `client.close()`, про який можна забути. Сторінка **[Тестування](get-started/testing.md)** побудована саме на цьому шаблоні.

## `Error executing tool <name>: <message>` і `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

Перед вами **результат**, а не виняток. `call_tool` нічого не викинув і ніколи не викине для інструмента, що завершився збоєм.

Викличте `forecast` для міста, якого сервер не знає, — і виняток, який він викидає, повертається із запитом, позначеним як *успішний*:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` має ту саму форму для імені, яке сервер ніколи не реєстрував, а неправильний аргумент відхиляється так само — за вхідною схемою інструмента, ще до того, як ваша функція запуститься.

Виправлення — на боці клієнта: **перевіряйте `result.is_error`**. `try/except` навколо `call_tool` не перехопить жодного з цих випадків, бо перехоплювати нічого. Це зроблено навмисно, і це найкорисніше, що варто засвоїти з цієї сторінки: виклик обрала *модель*, тож саме модель отримує повідомлення й шанс спробувати знову. Докладніше — на сторінці **[Обробка помилок](servers/handling-errors.md)**, зокрема про шлях через `MCPError`, який *таки* викидає виняток.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

Ви написали `@mcp.tool` замість `@mcp.tool()`. `tool()` — це *фабрика* декораторів: без дужок Python передає вашу функцію в її параметр `name=`.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

Додайте дужки. `@mcp.resource(...)` і `@mcp.prompt()` кажуть те саме про ту саму описку.

!!! note
    Цей виняток викидається під час **імпорту** модуля, до того як під'єднається будь-який
    клієнт. Тож хост, який показує ваш сервер як такий, що *не запустився* (або *від'єднався*),
    а не як під'єднаний із нулем інструментів, має саме цю форму: запустіть `python server.py`
    самі й прочитайте трасування. Перевірка типів теж це ловить: функція — не дійсне значення
    для `name=`.

## `Tool already exists: <name>` {#tool-already-exists-name}

Дві реєстрації використали те саме ім'я інструмента. Перемагає **перша**, другу мовчки відкидають, і це попередження в *лозі сервера* — єдиний сигнал:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` повідомляє про один `forecast`, і це `forecast_today`. Перейменуйте один із них. `MCPServer(..., warn_on_duplicate_tools=False)` глушить попередження, не змінюючи результату, тож залишайте його ввімкненим. Для ресурсів і промптів діє те саме правило й той самий рядок у лозі (`Resource already exists:`, `Prompt already exists:`).

## Мій хост показує нуль інструментів {#my-host-lists-zero-tools}

Для цього немає рядка помилки, і саме тому це важко знайти пошуком. SDK ніколи не викидає зареєстрований інструмент із `tools/list`, тож рухайтеся від центру назовні:

* **Чи взагалі запустився сервер?** `@mcp.tool` без дужок викидає виняток під час імпорту, а сервер, що впав, у деяких хостах дуже схожий на порожній. Запустіть `python server.py` самі.
* **Чи інструмент на тому `mcp`, який запускає хост?** Другий `MCPServer(...)` в іншому модулі — це інший, порожній сервер. Перевірте, який об'єкт насправді імпортує команда хоста.
* **Чи не мають два інструменти одне ім'я?** Тоді одного з них немає. Шукайте `Tool already exists:` у лозі сервера.
* **Чи не застарів список у хоста?** Інструмент, доданий після запуску, доходить лише до клієнтів, які обробляють `notifications/tools/list_changed`. Перезапуск хоста — грубе, але дієве рішення.
* **Чи не записало щось у `stdout` поза вікном перенаправлення?** Під час обслуговування SDK перенаправляє *скинутий* (flushed) сторонній stdout у stderr (наскільки можливо: середовище, яке підміняє стандартні потоки, обслуговується як є), але вивід, скинутий у stdout раніше (скрипт-обгортка, що щось виводить, `print()` під час імпорту в небуферизованому процесі), або буферизований `print()`, злитий під час завершення інтерпретатора, потрапляє в потік протоколу, і одного сміттєвого рядка досить, щоб хост розірвав з'єднання, — а деякі хости показують це як сервер, у якому нічого немає. Натомість пишіть лог через модуль `logging`. Решта контрольного списку на боці хоста — на сторінці **[Під'єднання до справжнього хоста](get-started/real-host.md)**.

«Недійсного» імені інструмента в цьому списку *немає*: невідповідне ім'я записує попередження в лог, але інструмент однаково реєструється й потрапляє до списку.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

Сервер одразу відхилив HTTP-запит із тілом, яке не є JSON-RPC, тож python `Client` не має нічого кращого, ніж показати цю заглушку.

Найпоширеніша причина з великим відривом — щойно розгорнутий сервер Streamable HTTP. `streamable_http_app()` (і `mcp.run("streamable-http")`) без `transport_security=` за замовчуванням вмикає **захист від DNS-rebinding**: приймаються лише запити, у яких заголовок `Host` — localhost. Це правильне типове значення на вашому ноутбуці й неправильне за справжнім іменем хоста:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

Розгорніть це, спрямуйте на нього клієнт — і з'єднання падає на рукостисканні:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

Слова, які сервер насправді надіслав, — `421` і `Invalid Host header` — до вас не доходять: тіло відповіді 421 не має `Content-Type: application/json`, тому клієнт не може його розібрати. Вони є в **лозі сервера**, і саме туди варто дивитися далі:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

Виправлення — `transport_security=`. Додайте до списку дозволених ім'я хоста, яке ви справді обслуговуєте:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    Оце й уся зміна. Той самий клієнт тепер під'єднується, узгоджує `2026-07-28` і
    викликає `forecast`.

На сторінці **[Розгортання й масштабування](run/deploy.md)** описано, що означає кожне поле, випадок зі зворотним проксі та все інше, що змінюється під час розгортання. А `421 Misdirected Request` / `Invalid Host header`, одразу нижче, — це той самий збій, побачений з іншого боку.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

Це `Server returned an error response`, побачене з будь-чого, що *не* є python `Client`: curl, вкладки мережі у браузері, журналу доступу зворотного проксі чи іншого SDK.

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

`421 Misdirected Request` — власна фраза-пояснення HTTP для цього статусу; `Invalid Host header` — тіло відповіді SDK; а python `Client` показує ту саму подію як `Server returned an error response`. Усі три — одна відмова. Перевірка виконується за **заголовком `Host`, який несе запит**, а не за адресою, до якої прив'язано сервер, тому зворотний проксі, що пересилає публічне ім'я хоста, спрацьовує на ній так само, як і прямий клієнт.

Виправлення те саме — `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`, показане під `Server returned an error response`. Два його нюанси варто назвати:

* Запис в `allowed_hosts` — це точний рядок. `"mcp.example.com"` відповідає заголовку `Host` без порту, а `"mcp.example.com:*"` — будь-якому явному порту. Вкажіть обидва.
* `403` із тілом `Invalid Origin header` — це споріднена перевірка заголовка `Origin`. Вона спрацьовує лише для браузерів (ніщо інше не надсилає `Origin`), а `allowed_origins=` — її список дозволених.

Докладніше — на сторінці **[Розгортання й масштабування](run/deploy.md)**, зокрема про те, коли вимкнути перевірку — чесна конфігурація.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

Ваш MCP-застосунок змонтовано всередині іншого ASGI-застосунку, і ніщо не запустило його **менеджер сесій**.

`mcp.streamable_http_app()` повертає застосунок Starlette, чий власний життєвий цикл (lifespan) запускає менеджер, а `uvicorn server:app` виконує цей життєвий цикл за вас. Але Starlette **ніколи не виконує життєвий цикл змонтованого підзастосунку**, тож щойно застосунок опиняється всередині `Mount`, менеджер не запускається, і перший же запит вибухає:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

Сервер запускається. Маршрут розв'язується. А потім `uvicorn` друкує це на кожен запит:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

Клієнт бачить 500. Виправлення — життєвий цикл на **хост**-застосунку, який входить у `mcp.session_manager.run()`:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

Про це — сторінка **[Додавання до наявного застосунку](run/asgi.md)**, зокрема про кілька серверів в одному застосунку та FastAPI. Два сусідні рядки з того самого класу:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` Менеджер одноразовий; подвійний вхід у життєвий цикл того самого застосунку натрапляє на це.
* `mcp.session_manager` існує лише **після** виклику `streamable_http_app()`, тож спершу побудуйте маршрути й торкайтеся менеджера лише всередині життєвого циклу.

## `MCPError: Session not found` {#mcperror-session-not-found}

Сервер не впізнає `Mcp-Session-Id`, який надіслав ваш клієнт, майже завжди тому, що сервер **перезапустився** (або вас спрямували на інший екземпляр). Сесії живуть у пам'яті того одного процесу.

Помилки в сервері тут немає. HTTP-відповідь — це `404`, тіло якого *є* JSON-RPC, тож, на відміну від `421` вище, python `Client` показує це повідомлення дослівно:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

Виправлення — перепід'єднатися: вийдіть із блоку `async with Client(...)` і ввійдіть у новий, який узгодить свіжу сесію. Для довгоживучого клієнта це означає перехоплювати `MCPError` навколо викликів і перепід'єднуватися на це повідомлення, а не повторювати спроби всередині мертвої сесії.

Якщо це трапляється *без* перезапуску, у вас працює більше одного робочого процесу без липких сесій: кожен робочий процес тримає власну таблицю сесій, тож запит, спрямований не на той, опиняється тут. Про це та про два виправлення (липка маршрутизація або `stateless_http=True`) — сторінки **[Розгортання й масштабування](run/deploy.md)** і **[Обслуговування клієнтів старого покоління](run/legacy-clients.md)**.

Для оператора сервера відповідний рядок у лозі — `Rejected request with unknown or expired session ID: <id>`. Він пишеться на рівні `INFO`, тож за звичного порога `WARNING` його не видно. Бачити його сплесками одразу після розгортання — нормально: кожен під'єднаний клієнт перепід'єднується.

## `MCPError: Method not found` {#mcperror-method-not-found}

Одна сторона надіслала JSON-RPC-запит, для якого інша не має обробника, а `e.error.data` називає метод. Звична причина — **невідповідність поколінь**: метод, що існує в одній ревізії протоколу й відсутній в іншій, надісланий співрозмовнику не того покоління, — наприклад, `resources/subscribe` покоління `2025`, що приходить на з'єднання `2026-07-28`, або `subscriptions/listen`, який є лише у `2026`, надісланий клієнтом, закріпленим на `mode="legacy"`. Сторінка **[Версії протоколу](protocol-versions.md)** — це мапа того, яка сторона що розуміє, а інша чесна причина (необов'язкова можливість, для якої ви так і не зареєстрували обробник) — на сторінці **[Автодоповнення](servers/completions.md)**.

Одна річ цієї помилки **не** спричиняє, хоч і є запитом, який сучасний протокол вилучив: інструмент, що викликає `ctx.elicit()` на з'єднанні `2026-07-28`. Сервер узагалі відмовляється *надсилати* цей запит, тож натомість ви отримуєте `Cannot send 'elicitation/create': ...`, описане нижче на цій сторінці.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

Ваш сервер хоче про щось запитати користувача, а цей клієнт ніколи не казав, що його можна питати.

Резолвер еліцитації (elicitation) відмовляє одразу, якщо під'єднаний клієнт не оголосив еліцитацію через форму, а `e.error.data` називає, чого саме бракує:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

Передайте `elicitation_callback=` у `Client(...)`. Реєстрація колбека — це і *є* оголошення можливості; другого перемикача немає:

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

На сторінці **[Колбеки клієнта](client/callbacks.md)** перелічено інші (`sampling_callback`, `list_roots_callback`), кожен із яких так само є оголошенням.

!!! info
    `-32021` — це `MISSING_REQUIRED_CLIENT_CAPABILITY`, один із трьох кодів помилок, які додає
    специфікація 2026-07-28. Жоден із них не є класом винятку: усі приходять як `MCPError`, а
    дивитися треба в `e.error.code`. Константи експортує `mcp.types`. Інші два —
    `-32020` `HEADER_MISMATCH` (HTTP-заголовок суперечить тілу запиту, який він супроводжує)
    і `-32022` `UNSUPPORTED_PROTOCOL_VERSION` (запит назвав версію, якою цей сервер не
    говорить). Клієнт SDK, що відповідає специфікації, не може видати жодного з них, тож якщо ви
    такий бачите, шукайте те, що переписує запити між вашим клієнтом і сервером.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

Та сама прогалина, що й `Client did not declare the form elicitation capability ...`, тільки у формулюванні шляхів, які не перевіряють заздалегідь: серверу потрібна була відповідь на еліцитацію, а під'єднаний клієнт не зареєстрував `elicitation_callback`.

Це повідомлення приходить від `ctx.elicit()` на з'єднанні старого покоління, а на будь-якому з'єднанні взагалі — від повернутого багатораундового (multi-round-trip) запитання (**[Багатораундові запити](handlers/multi-round-trip.md)**), що доходить до клієнта без колбека, який міг би відповісти. Виправлення ідентичне: передайте `elicitation_callback=` у `Client(...)`. Не існує варіанта «користувача не запитали», який ваш інструмент отримав би як `decline`; клієнт, якого не можна запитати, — це невдалий виклик, тож проєктуйте інструменти з огляду на це.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

Ваш обробник спробував звернутися до клієнта посеред запиту на з'єднанні, де виклик не має каналу, здатного нести запит від сервера. Є три конфігурації сервера, за яких виклик опиняється в такому становищі.

**З'єднання `2026-07-28`: будь-який транспорт, завжди.** Сучасний протокол узагалі не має запитів, ініційованих сервером, тож сервер відмовляє ще до того, як щось надіслано. `ctx.elicit()` усередині інструмента — класичний спосіб на це натрапити (у найпершому ж тесті в пам'яті, бо `Client(server)` узгоджує `2026-07-28`, навіть якщо його про це не просили), і передавання `elicitation_callback=` нічого не змінює, бо до клієнта ніколи не доходить запит, на який він міг би відповісти:

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

**З'єднання старого покоління на сервері зі `stateless_http=True`.** Відсутність стану означає, що кожен запит — окремий світ: ні сесії, ні потоку від сервера до клієнта, а отже, нікуди надсилати `elicitation/create` (чи `sampling/createMessage`, чи `roots/list`) навіть для покоління, яке їх має:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**З'єднання старого покоління на сервері з `json_response=True`.** На `POST` відповідають одним JSON-тілом, а одне тіло несе лише відповідь, тож потоку в межах запиту, потрібного `ctx.elicit()` посеред запиту, тут теж немає. Сесія, її `Mcp-Session-Id` і її окремий потік — усе на місці; зник лише канал у межах запиту.

Повідомлення називає метод, який не вдалося надіслати. `NoBackChannelError` — клас, який викидає сервер, але мережею передається лише базовий `MCPError`, тож останній рядок вашого трасування — це речення вище, а не ім'я класу.

Для клієнта `2026-07-28` виправлення однакове в усіх трьох випадках: не звертайтеся назад посеред виклику. Перенесіть запитання в **резолвер** (або поверніть `InputRequiredResult` самі) — і воно стає частиною *відповіді*, яку здатне нести будь-яке з'єднання:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

Те саме запитання, той самий `elicitation_callback` на клієнті. Різниця — усередині: резолвер дає серверу *повернути* запитання з виклику замість проштовхувати його, тож від сервера до клієнта ніколи нічого не тече. Це рятує кожного клієнта `2026-07-28`, у якій би з трьох конфігурацій не був сервер. Клієнта *старого покоління* саме лише переписування не рятує: `2025-11-25` не має способу повернути запитання, тож на з'єднанні старого покоління резолвер і далі надсилає `elicitation/create` каналом у межах запиту й далі потребує сервера, який його зберігає, — тобто без `stateless_http=True` і без `json_response=True`. Про резолвери — сторінка **[Еліцитація](handlers/elicitation.md)**; про те, що відбувається в переданих даних, — **[Багатораундові запити](handlers/multi-round-trip.md)**.

!!! check
    Інструмент із `ctx.elicit()` не помилковий, він *до-2026*. Під'єднайтеся з `mode="legacy"`
    (класичне рукостискання `initialize`, специфікація `2025-11-25` і раніші) до сервера, який не
    має ні `stateless_http=True`, ні `json_response=True`, — і він працює, бо там канал від
    сервера до клієнта існує.
    Про те, що є в кожній версії, — сторінка **[Версії протоколу](protocol-versions.md)**.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

Сервер не зміг перевірити токен `requestState`, який ваш клієнт повернув у відповідь, тому відхилив раунд.

`requestState` — непрозорий токен відновлення, який **[багатораундовий](handlers/multi-round-trip.md)** виклик несе між етапами. `MCPServer` запечатує його на виході й перевіряє кожне повернення, і перевіряє *кожен* вхідний `request_state` у `tools/call`, `prompts/get` і `resources/read`, навіть для обробника, який сам ніколи його не випускає. Тож токен, який цей процес не запечатував, відхиляється, хай куди він потрапить:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

Повідомлення навмисно незмінне: передані дані ніколи не розкривають, яка саме перевірка не пройшла. Причина йде в **лог сервера**, і прочитати його — оце й уся діагностика:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

Причини, які ви справді побачите:

* **`unknown key`** — та, що має значення. Типовий ключ запечатування генерується під час запуску процесу, тож повторна спроба, що потрапляє на **інший робочий процес**, інший екземпляр за балансувальником навантаження чи на той самий сервер **після перезапуску**, була запечатана ключем, якого цей процес ніколи не мав. Це не зловмисник; це типове значення, що зіткнулося з більш ніж одним процесом.
* **`audience`**: токен запечатав екземпляр з *іншим іменем сервера*. Ім'я — типове значення audience у печатці, тож флот має мати спільне ім'я (або явний `RequestStateSecurity(audience=...)`), а не лише спільні ключі.
* **`expired`**: раунд тривав довше за `ttl` печатки, а це 600 секунд, причому на раунд, а не на виклик.
* **`malformed`** / **`codec error`**: токен змінили під час передавання, або він узагалі ніколи не був запечатаним токеном.
* **`request binding`**: токен повернувся з іншим інструментом, іншими аргументами чи іншим методом.

Виправлення для кількох процесів — один аргумент (*ті самі* `keys` на кожному екземплярі) плюс одна річ, яка взагалі не є аргументом: те саме *ім'я* сервера (або явний спільний `audience=`).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` запечатує; перевіряє кожен ключ зі списку — саме це робить можливою ротацію без простою. На сторінці **[Багатораундові запити](handlers/multi-round-trip.md#protecting-requeststate)** пояснено, що захищає печатка, і послідовність ротації, а **[Розгортання й масштабування](run/deploy.md)** розбирає весь збій із двома робочими процесами та його виправлення з двох частин.

!!! tip
    `keys=[...]` одразу відхиляє слабкий ключ, із напрочуд корисним повідомленням:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    Зробіть, як воно каже.

## Досі не виходить? {#still-stuck}

* Якщо повідомлення, яке видав SDK, немає на цій сторінці, це помилка в документації, про яку варто повідомити окремо.
* Пошукайте в [трекері задач](https://github.com/modelcontextprotocol/python-sdk/issues); більшість рядків помилок, що там трапляються, хтось уже описав.
* Нічого не знайшли? [Відкрийте issue](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) з повним трасуванням або запитайте в [#python-sdk-dev на Discord-сервері MCP Contributors](https://discord.gg/6CSzBmMkjX).

## Підсумки {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` ніколи не є самою помилкою. Читайте **останній рядок**; перехоплення `MCPError` *всередині* блоку `async with Client(...)` повністю оминає обгортання.
* `call_tool` не викидає виняток для інструмента, що завершився збоєм. `Error executing tool ...` і `Unknown tool: ...` — це результати: перевіряйте `result.is_error`.
* `Client must be used within an async context manager` -> використовуйте `async with`. `Use @tool() instead of @tool` -> додайте дужки.
* `Tool already exists:` у лозі сервера — єдина ознака того, що два однойменні інструменти злилися в один.
* Один 421, три написання: `Server returned an error response` (python `Client`), `421 Misdirected Request` / `Invalid Host header` (усе інше), `Invalid Host header: <host>` (лог сервера). Виправлення: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> змонтований застосунок, чий хост-застосунок у своєму життєвому циклі так і не ввійшов у `mcp.session_manager.run()`.
* `Session not found` -> сервер перезапустився; перепід'єднайтеся.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` потребує каналу від сервера до клієнта: з'єднання `2026-07-28` його ніколи не має, `stateless_http=True` забирає канал старого покоління, а `json_response=True` — канал у межах запиту. Використовуйте резолвер (клієнту старого покоління також потрібен сервер, що зберігає канал). Сусідня помилка `Method not found` — це запит методу, якого немає в ревізії протоколу іншої сторони.
* `Client did not declare the form elicitation capability ...` і `Elicitation not supported` -> клієнту бракує `elicitation_callback=`.
* `Invalid or expired requestState` ніколи не пояснює причину в переданих даних. Лог сервера — пояснює; `unknown key` означає, що треба зробити `RequestStateSecurity(keys=[...])` спільним для всіх робочих процесів.
