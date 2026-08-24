---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# Застарілі можливості {#deprecated-features}

Специфікація 2026-07-28 виводить з ужитку п'ять речей. SDK і далі реалізує кожну з них, і кожна тепер супроводжується **попередженням про застарілість**. Один допоміжний метод SDK оголошено застарілим окремо, і його наведено [наприкінці сторінки](#deprecated-sdk-helpers).

Таблиця нижче називає кожну застарілу можливість, пояснює, чому вона зникає, і вказує заміну, на яку варто спиратися.

## Що застаріло {#what-is-deprecated}

| Застаріле | Чому | Що робити натомість |
|---|---|---|
| **Кореневі каталоги (roots)**: `ctx.session.list_roots()`, `client.send_roots_list_changed()`, колбек `list_roots_callback=`, який передають у `Client(...)` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) виводить цю можливість з ужитку. | Приймайте шляхи як звичайні аргументи інструмента чи URI ресурсів або вбудуйте `ListRootsRequest` в `InputRequiredResult` (див. **[Багатораундові запити (multi-round-trip)](handlers/multi-round-trip.md)**). |
| **Семплювання (sampling) з ініціативи сервера**: `ctx.session.create_message()`, колбек `sampling_callback=`, який передають у `Client(...)` | SEP-2577 виводить цю можливість з ужитку. | Повертайте `InputRequiredResult`, і нехай клієнт повторить виклик (див. **[Багатораундові запити](handlers/multi-round-trip.md)**). |
| **Протокольне логування**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | SEP-2577 виводить цю можливість з ужитку. У протоколі її ніщо не замінює. | Звичайний `import logging` у stderr (див. **[Логування](handlers/logging.md)**). |
| **`ping`**: `client.send_ping()` | **Вилучено** з протоколу, а не просто оголошено застарілим. У 2026-07-28 методу `ping` немає. | Нічого. Він працює лише на з'єднанні з `mode="legacy"`. |
| **Перебіг виконання від клієнта до сервера**: `client.send_progress_notification()` | У 2026-07-28 перебіг виконання передається лише від сервера до клієнта. | Надсилати нічого. Про перебіг виконання звітує ваш *сервер* через `ctx.report_progress()` (див. **[Перебіг виконання](handlers/progress.md)**). |

З цієї таблиці випливають три речі:

* Кореневі каталоги, семплювання й логування йдуть разом. Одна пропозиція, **SEP-2577**, оголошує застарілими всі три можливості одразу.
* Семплювання й кореневі каталоги мають спільну глибшу проблему: це місця, де **сервер** надсилає **запит** **клієнту**. Саме цей напрямок цілком 2026-07-28 замінює на **[багатораундові запити](handlers/multi-round-trip.md)**. Зникли окремі RPC-методи (`sampling/createMessage`, `roots/list` і push-варіант `elicitation/create`); типи корисного навантаження `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` залишаються — вбудовані в `InputRequiredResult.input_requests`, а на клієнті вони потрапляють у ті самі колбеки.
* `ping` стоїть осторонь. Протокол не оголошує його застарілим, а вилучає. Метод SDK і далі попереджає (у його повідомленні сказано *removed*, а не *deprecated*), а виклик на сучасному з'єднанні отримує у відповідь *«Method not found»*.

## Застарілість має рекомендаційний характер {#deprecated-is-advisory}

Сьогодні нічого не ламається.

Кожен із наведених методів і далі працює з будь-якою сесією, що узгодила **2025-11-25 або ранішу версію**. Зафіксуйте `mode="legacy"` на клієнті — і отримаєте точнісінько ту поведінку, що була до 2026. У переданих даних нічого не змінюється, узгодження можливостей теж без змін.

Змінюється те, що під час першого виконання кожного з них з'являється помітне попередження:

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` успадковує `UserWarning`, а **не** `DeprecationWarning`. Це навмисно: типовий фільтр Python показує `DeprecationWarning` лише в коді, запущеному безпосередньо як `__main__`, — саме так бібліотеки оголошують щось застарілим, і два роки ніхто цього не помічає. Це попередження видно всюди, без жодного прапорця `-W`.

!!! warning
    «Рекомендаційний характер» закінчується на рівні переданих даних. Семплювання й кореневі
    каталоги — це *запити* від сервера до клієнта, а сесія 2026-07-28 не має каналу, яким
    їх можна передати. Викличте `ctx.session.create_message()` усередині інструмента на
    сучасному з'єднанні — попередження все одно спрацює, а потім надсилання завершиться
    помилкою:

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    Два сигнали, саме в такому порядку. `MCPDeprecationWarning` спрацьовує тієї ж миті, коли
    ви викликаєте метод, на будь-якому з'єднанні. Помилка — це те, що повертається, коли SDK
    потім намагається надіслати запит. Ці два методи працюють від початку до кінця лише на
    з'єднанні з `mode="legacy"`, клієнт якого зареєстрував відповідний колбек.

## `ping` у сесії старого покоління {#ping-on-a-legacy-session}

**Ping** — це порожній запит, який може надіслати будь-яка сторона, щоб перевірити, чи інша ще відповідає. Специфікація 2026-07-28 його вилучає ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)): кожен запит, який надсилає сучасний клієнт, уже доводить, що сервер на місці, а сучасний сервер не має каналу, яким міг би надіслати свій. Обидва методи SDK і далі працюють у сесії покоління з рукостисканням. З боку клієнта:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

А з боку сервера, усередині будь-якого обробника:

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` попереджає через `MCPDeprecationWarning` під час кожного виклику. На з'єднанні за замовчуванням (`2026-07-28`) сервер натомість відповідає `MCPError: Method not found`.
* `ctx.session.send_ping()` попередження не має. На сучасному з'єднанні він викидає ту саму помилку про відсутність зворотного каналу (back-channel), що й будь-який інший запит з ініціативи сервера.
* Жодна зі сторін нічого не реєструє, щоб відповідати на ping.

## Сповіщення про зміну кореневих каталогів {#roots-change-notifications}

Клієнт покоління 2025, який оголосив можливість кореневих каталогів, може повідомити серверу, що теки його робочого простору змінилися, надіславши `notifications/roots/list_changed`; сервер у відповідь знову запитує `roots/list`. Специфікація 2026-07-28 вилучає це сповіщення разом із рештою push-варіанту роботи з кореневими каталогами. На клієнті саме передавання `list_roots_callback=` (**[Колбеки клієнта](client/callbacks.md)**) оголошує `"roots": {"listChanged": true}`, а один виклик дотримує цієї обіцянки:

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

На боці сервера обробник, що приймає це сповіщення, передають у низькорівневий `Server`:

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` — це список, який повертає ваш `list_roots_callback`. `client.send_roots_list_changed()` попереджає і потребує клієнта з `mode="legacy"`: на сучасному з'єднанні сповіщення мовчки відкидається. Після цього не закривайте сесію, бо наступний запит сервера `roots/list` надходить саме нею.
* `MCPServer` не має гачка для цього сповіщення. У низькорівневому `Server` обробник реєструє параметр `on_roots_list_changed=` (теж застарілий, він попереджає під час створення екземпляра). Сповіщення не несе корисного навантаження, тож обробник викликає `ctx.session.list_roots()`, щоб отримати новий список.

## Приглушення попередження {#silencing-the-warning}

У новому коді — не робіть цього.

Але сервер, який ви підтримуєте і який справді обслуговує клієнтів до 2026, має повне право на тихий лог. Відфільтруйте категорію до того, як виконається перший застарілий виклик:

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

Оце й увесь API. Перемикача для окремих методів немає, і він вам не потрібен: сенс однієї категорії в тому, що один рядок її приглушує, а один рядок повертає.

!!! check
    Розверніть фільтр у зворотний бік — і отримаєте безкоштовний регресійний тест. Додайте
    `"error::mcp.MCPDeprecationWarning"` до налаштування `filterwarnings` у конфігурації
    pytest — і застарілий виклик **викидатиме виняток** замість попередження. Інструмент
    з назвою `old_log`, який досі викликає `ctx.info()`, перестає проходити тест: виклик
    повертається з `is_error=True` і текстом `Error executing tool old_log`, а захоплений
    лог сервера називає винуватця:

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    Один рядок конфігурації pytest — і застарілий виклик більше ніколи не прокрадеться назад
    у вашу кодову базу, не проваливши тест.

## Застарілі допоміжні методи SDK {#deprecated-sdk-helpers}

Це не зміни специфікації, а лише внутрішні частини SDK, для яких є краща заміна. Вони попереджають тим самим `MCPDeprecationWarning` і будуть вилучені у версії 3.0.

| Застаріле | Що робити натомість |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | `FuncMetadata.validate_arguments()`, а потім `FuncMetadata.call_fn()`. Його викликав лише код, що працює з `FuncMetadata` безпосередньо (скажімо, власний підклас `Tool`). |

## Підсумки {#recap}

* Специфікація 2026-07-28 оголошує застарілими **кореневі каталоги**, **семплювання** з ініціативи сервера та протокольне **логування** (усе — [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), обмежує **перебіг виконання** напрямком від сервера до клієнта й вилучає **`ping`**.
* Стовпець із замінами вказує, куди рухатися далі: **[Багатораундові запити](handlers/multi-round-trip.md)** для семплювання й кореневих каталогів, **[Логування](handlers/logging.md)** для логування, **[Перебіг виконання](handlers/progress.md)** для перебігу виконання. `ping` не потребує взагалі нічого.
* Застарілість має рекомендаційний характер: жодних змін у переданих даних, усе й далі працює із сесіями до 2026, а ви отримуєте помітне попередження `MCPDeprecationWarning` (це `UserWarning`, тож воно ввімкнене за замовчуванням).
* Семплювання й кореневі каталоги додатково потребують зворотного каналу, якого сесія 2026-07-28 не має. На сучасному з'єднанні вони попереджають, а потім викидають виняток.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` приглушує всю категорію; `"error::mcp.MCPDeprecationWarning"` у pytest перетворює її на провал тесту.
* Один допоміжний метод SDK, `FuncMetadata.call_fn_with_arg_validation()`, оголошено застарілим окремо — його вилучать у версії 3.0.
* Новий код не варто будувати на жодній із цих можливостей.

Усі інші сторінки цієї документації навчають чинного API.
