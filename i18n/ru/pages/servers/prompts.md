---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
  tool: 1
---
# Промпты {#prompts}

**Промпт** — это шаблон сообщения, который выбирает пользователь.

Инструменты предназначены для модели. Промпт — наоборот: пользователь выбирает его из меню в своём клиенте (слэш-команда, кнопка), заполняет аргументы, и отрендеренные сообщения попадают в диалог так, будто он набрал их сам.

Чтобы объявить промпт, поставьте `@mcp.prompt()` над функцией, которая возвращает текст.

## Первый промпт {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

SDK читает те же три вещи, что и у инструмента:

* **Имя** — это имя функции: `review_code`.
* **Описание**, которое показывает клиент, — это строка документации: `Review a piece of code.`
* **Аргументы** берутся из параметров. У `code` нет значения по умолчанию, поэтому он обязательный.

Вот что клиент получает в ответ на `prompts/list`:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

Никакой JSON Schema здесь нет. Аргументы промпта — это плоский список **именованных строковых значений**: форма, которую заполняет человек, а не полезная нагрузка, которую конструирует модель.

### Рендеринг {#rendering-it}

Клиент рендерит шаблон через `prompts/get`, передавая аргументы. Функция выполняется, и возвращённая `str` становится **одним сообщением пользователя**:

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

Вот и вся жизнь промпта: перечислен по имени, отрендерен по запросу, отправлен в чат.

!!! check
    `required` проверяется до запуска функции. Попробуйте отрендерить `review_code` без `code` —
    сам запрос завершится ошибкой JSON-RPC (код `-32603`):

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    Результата с ошибкой в стиле инструмента, который можно было бы вернуть модели, нет, потому что
    модели в этой цепочке нет: вызов выбрасывает исключение. Причина (`Missing required arguments: {'code'}`)
    попадает в лог сервера.

### Попробуйте сами {#try-it}

Запустите сервер с MCP Inspector:

```console
uv run mcp dev server.py
```

Откройте вкладку **Prompts** и выберите `review_code`. Inspector нарисует форму с одним обязательным полем `code`. Заполните его, отрендерите — и в ответ придёт ровно то сообщение пользователя, что показано выше.

## Больше одного сообщения {#more-than-one-message}

Ревью кода — это одно сообщение. Сессия отладки — это диалог, и промпт может задать его целиком.

Верните список сообщений вместо `str`:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` и `AssistantMessage` находятся в `mcp.server.mcpserver.prompts.base`. Передайте им `str`, и они сами обернут её в `TextContent`. Роль — это имя класса.
* `Message` — их общий базовый класс. Используйте его как аннотацию возвращаемого типа.

Теперь `debug_error` при рендеринге даёт три сообщения по порядку:

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

Обратите внимание на последнее. Заранее заполненная реплика `assistant` — это способ направить *следующий* ответ модели, не заставляя пользователя набирать эти указания самостоятельно.

## Заголовки и описания аргументов {#titles-and-argument-descriptions}

`review_code` — имя функции, а не подпись. Дайте клиенту что-нибудь получше для надписи на кнопке и опишите каждый аргумент, чтобы форма была понятна сама по себе:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` — человекочитаемое имя, ровно как `title` у инструмента.
* `Annotated[str, Field(description=...)]` — тот же приём, которым **[Инструменты](tools.md)** описывают параметры инструмента. Здесь описание попадает в аргумент, а не в схему.
* У `language` есть значение по умолчанию, поэтому он перестаёт быть обязательным.

Запись в `prompts/list` теперь содержит всё, что нужно клиенту, чтобы нарисовать хорошую форму:

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    Если вы читали страницу **[Инструменты](tools.md)**, всё сказанное до этого места вам уже знакомо. Тот же декоратор,
    та же строка документации в роли описания, те же `Annotated`/`Field`. Меняется только то, кто
    запускает промпт (пользователь), и куда идёт результат (в диалог).

## Больше, чем текст {#more-than-text}

`UserMessage` и `AssistantMessage` везде, где принимают `str`, принимают также блок содержимого или вспомогательный объект `Image` / `Audio`. В промптах встречаются два случая: вложить документ и вложить картинку.

### Встраивание файла {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* Руководство по стилю — это ресурс по адресу `style://python` (о ресурсах — на странице **[Ресурсы](resources.md)**), который читается из файла `style-guide.md` рядом с `server.py`. Положите туда любой файл Markdown.
* `EmbeddedResource(resource=TextResourceContents(...))` (оба из `mcp.types`) несёт файл вместе с его URI и MIME-типом первым сообщением; запрос, который на него ссылается, идёт следом обычным текстом.
* Встраивание, в отличие от вставки руководства прямо в f-строку, позволяет клиенту показать его как вложение и позже снова открыть `style://python`, а модель получает файл дословно. Для двоичного файла используйте `BlobResourceContents` с `blob` в base64.

После рендеринга `content` первого сообщения — это блок `resource`:

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### Вложение изображения {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image` — вспомогательный класс со страницы **[Изображения, аудио и иконки](media.md)**. `UserMessage` преобразует его в блок `ImageContent` (файл в base64, MIME-тип угадывается по `.png`) при рендеринге промпта; `Audio` точно так же становится `AudioContent`.
* Положите рядом с `server.py` любой PNG с именем `architecture.png`. Аргументы промпта — строки, поэтому картинка всегда берётся с сервера; `component` даёт только слова.

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## Изменение списка во время работы {#changing-the-list-at-runtime}

Промпты можно добавлять, пока клиенты подключены, — например, чтобы пользователь мог сохранить инструкцию как собственный пункт меню. Зарегистрируйте промпт, затем отправьте уведомление:

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))` регистрирует функцию ровно так же, как это сделал бы `@mcp.prompt()`, а `mcp.remove_prompt(name)` — обратная операция. `add_prompt` сохраняет существующую запись с тем же именем, а не перезаписывает её, поэтому инструмент сначала удаляет старую, чтобы сохранение работало как замена. `prompts/list` отражает изменение сразу.
* `await ctx.notify_prompts_changed()` отправляет `notifications/prompts/list_changed` каждому клиенту `2026-07-28`, который слушает поток `subscriptions/listen` (**[Подписки](../handlers/subscriptions.md)**). `await ctx.session.send_prompt_list_changed()` отправляет его вызывающему клиенту, если тот старше поколения 2026 (**[Обслуживание клиентов старого поколения](../run/legacy-clients.md)**). Вызывайте оба; каждый ничего не делает, когда сообщать некому.
* Клиент, получивший уведомление, снова вызывает `prompts/list`. В классе `Client` на Python это `async with client.listen(prompts_list_changed=True) as sub:`, который выдаёт событие `PromptsListChanged`.

## Итоги {#recap}

* `@mcp.prompt()` над функцией делает её промптом. Имя — из функции, описание — из строки документации.
* Промпты **управляются пользователем**: клиент их перечисляет, пользователь выбирает один и заполняет аргументы.
* Аргументы — плоский список именованных строк (без схемы). Параметр со значением по умолчанию необязателен.
* Верните `str` — и она станет одним сообщением пользователя. Верните список `UserMessage` / `AssistantMessage`, чтобы задать многоходовой диалог.
* `title=` и `Field(description=...)` — это то, что клиент показывает в интерфейсе.
* Отсутствующий обязательный аргумент проваливает весь запрос. Отдельного результата с ошибкой у промпта нет.
* Оберните `EmbeddedResource` или `Image` в `UserMessage`, чтобы вложить документ или картинку.
* Добавляйте и удаляйте промпты во время работы через `mcp.add_prompt(...)` / `mcp.remove_prompt(...)`, затем вызывайте `await ctx.notify_prompts_changed()` и `await ctx.session.send_prompt_list_changed()`.

Автодополнение аргументов промпта (или шаблона ресурса) на стороне сервера — на странице **[Автодополнение](completions.md)**.
