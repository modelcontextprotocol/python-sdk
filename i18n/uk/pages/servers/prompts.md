---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
  tool: 1
---
# Промпти {#prompts}

**Промпт** — це шаблон повідомлення, який обирає користувач.

Інструменти призначені для моделі. Промпт — навпаки: користувач обирає його з меню у своєму клієнті (слеш-команда, кнопка), заповнює аргументи, і згенеровані повідомлення потрапляють у розмову так, ніби він набрав їх сам.

Щоб оголосити промпт, поставте `@mcp.prompt()` над функцією, яка повертає текст.

## Ваш перший промпт {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

SDK зчитує ті самі три речі, що й з інструмента:

* **Ім'я** — це ім'я функції: `review_code`.
* **Опис**, який показує клієнт, — це docstring: `Review a piece of code.`
* **Аргументи** беруться з параметрів. `code` не має типового значення, тому він обов'язковий.

Ось що клієнт отримує у відповідь на `prompts/list`:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

Тут немає JSON Schema. Аргументи промпту — це плоский список **іменованих рядкових значень**: форма, яку заповнює людина, а не дані, які конструює модель.

### Генерування {#rendering-it}

Клієнт генерує повідомлення за шаблоном через `prompts/get`, передаючи аргументи. Ваша функція виконується, і повернутий `str` стає **одним повідомленням користувача**:

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

Оце й усе життя промпту: його показують у списку за іменем, генерують на вимогу і вставляють у чат.

!!! check
    `required` перевіряється ще до запуску вашої функції. Згенеруйте `review_code` без `code` —
    і сам запит завершиться помилкою JSON-RPC (код `-32603`):

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    Результату з помилкою на кшталт інструмента, який можна було б передати моделі, тут немає, бо моделі в цьому ланцюжку немає взагалі:
    виклик викидає виняток. Причина (`Missing required arguments: {'code'}`) потрапляє в лог вашого сервера.

### Спробуйте самі {#try-it}

Запустіть сервер із MCP Inspector:

```console
uv run mcp dev server.py
```

Відкрийте вкладку **Prompts** і виберіть `review_code`. Inspector намалює форму з одним обов'язковим полем `code`. Заповніть його, згенеруйте промпт — і отримаєте точно те повідомлення користувача, що наведене вище.

## Більше ніж одне повідомлення {#more-than-one-message}

Рев'ю коду — це одне повідомлення. Сеанс налагодження — це розмова, і промпт може закласти її цілком.

Поверніть список повідомлень замість `str`:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` і `AssistantMessage` імпортуються з `mcp.server.mcpserver.prompts.base`. Передайте їм `str`, і вони самі загорнуть його в `TextContent`. Роль — це ім'я класу.
* `Message` — їхній спільний базовий клас. Використовуйте його як анотацію типу результату.

Генерування `debug_error` тепер дає три повідомлення по порядку:

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

Зверніть увагу на останнє. Заздалегідь заповнена репліка `assistant` — це спосіб спрямувати *наступну* відповідь моделі, не змушуючи користувача набирати ці настанови самому.

## Заголовки та описи аргументів {#titles-and-argument-descriptions}

`review_code` — це ім'я функції, а не підпис. Дайте клієнту щось краще для напису на кнопці й опишіть кожен аргумент, щоб форма пояснювала себе сама:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` — це зрозуміла людині назва, точно як `title` в інструмента.
* `Annotated[str, Field(description=...)]` — той самий шаблон, яким на сторінці **[Інструменти](tools.md)** описано параметри інструмента. Тут опис потрапляє на аргумент, а не в схему.
* `language` має типове значення, тому перестає бути обов'язковим.

Запис у `prompts/list` тепер містить усе, що потрібно клієнту, щоб намалювати хорошу форму:

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
    Якщо ви читали сторінку **[Інструменти](tools.md)**, то вже знаєте все, про що йшлося досі. Той самий декоратор, той самий
    docstring як опис, ті самі `Annotated`/`Field`. Змінюється лише те, хто
    його запускає (користувач) і куди йде результат (у розмову).

## Більше ніж текст {#more-than-text}

`UserMessage` і `AssistantMessage` також приймають блок вмісту або допоміжний об'єкт `Image` / `Audio` всюди, де приймають `str`. У промптах трапляються два випадки: прикріпити документ і прикріпити зображення.

### Вбудовування файлу {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* Посібник зі стилю — це ресурс за адресою `style://python` (про них — на сторінці **[Ресурси](resources.md)**), який читається з файлу `style-guide.md` поруч із `server.py`. Покладіть туди будь-який Markdown-файл.
* `EmbeddedResource(resource=TextResourceContents(...))`, обидва з `mcp.types`, несе файл разом із його URI та MIME-типом як перше повідомлення; запит, що на нього посилається, іде слідом як звичайний текст.
* Вбудовування замість вставлення посібника в f-рядок дає клієнту змогу показати його як вкладення й пізніше знову відкрити `style://python`, а модель отримує файл дослівно. Для двійкового файлу використовуйте `BlobResourceContents` із `blob` у base64.

Після генерування `content` першого повідомлення — це блок `resource`:

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### Прикріплення зображення {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image` — допоміжний клас зі сторінки **[Зображення, аудіо та піктограми](media.md)**. `UserMessage` перетворює його на блок `ImageContent` (файл закодовано в base64, MIME-тип вгадано з `.png`), коли промпт генерується; `Audio` так само стає `AudioContent`.
* Покладіть будь-який PNG з іменем `architecture.png` поруч із `server.py`. Аргументи промпту — рядки, тому зображення завжди надходить із сервера; `component` лише дає слова.

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## Зміна списку під час роботи {#changing-the-list-at-runtime}

Промпти можна додавати, поки клієнти під'єднані, наприклад щоб користувач міг зберегти інструкцію як власний пункт меню. Зареєструйте промпт, а тоді надішліть сповіщення:

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))` реєструє функцію точно так, як це зробив би `@mcp.prompt()`, а `mcp.remove_prompt(name)` — зворотна дія. `add_prompt` залишає наявний запис із тим самим іменем, а не перезаписує його, тому інструмент спершу видаляє старий, щоб збереження працювало як заміна. `prompts/list` відображає зміну одразу.
* `await ctx.notify_prompts_changed()` надсилає `notifications/prompts/list_changed` кожному клієнту `2026-07-28`, що слухає потік `subscriptions/listen` (**[Підписки](../handlers/subscriptions.md)**). `await ctx.session.send_prompt_list_changed()` надсилає його клієнту, який зробив виклик, якщо той старший за 2026 (**[Обслуговування клієнтів старого покоління](../run/legacy-clients.md)**). Викликайте обидва; кожен нічого не робить, коли сповіщати нікого.
* Клієнт, що отримав сповіщення, знову викликає `prompts/list`. У Python-класі `Client` це `async with client.listen(prompts_list_changed=True) as sub:`, що видає подію `PromptsListChanged`.

## Підсумки {#recap}

* `@mcp.prompt()` над функцією робить її промптом. Ім'я — з функції, опис — з docstring.
* Промптами **керує користувач**: клієнт показує їхній список, користувач обирає один і заповнює аргументи.
* Аргументи — це плоский список іменованих рядків (без схеми). Параметр із типовим значенням необов'язковий.
* Поверніть `str` — і він стане одним повідомленням користувача. Поверніть список `UserMessage` / `AssistantMessage`, щоб закласти багатоходову розмову.
* `title=` і `Field(description=...)` — це те, що клієнт показує у своєму інтерфейсі.
* Відсутній обов'язковий аргумент провалює весь запит. Окремого результату з помилкою для промпту немає.
* Загорніть `EmbeddedResource` або `Image` у `UserMessage`, щоб прикріпити документ чи зображення.
* Додавайте або видаляйте промпти під час роботи через `mcp.add_prompt(...)` / `mcp.remove_prompt(...)`, а тоді викликайте `await ctx.notify_prompts_changed()` і `await ctx.session.send_prompt_list_changed()`.

Серверне автодоповнення аргументів промпту (або шаблону ресурсу) — це **[Автодоповнення](completions.md)**.
