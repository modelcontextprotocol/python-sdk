---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# Установка {#installation}

Python SDK опубликован на PyPI как [`mcp`](https://pypi.org/project/mcp/). Для работы нужен **Python 3.10+**.

Эта документация описывает **v2** — текущую стабильную линейку выпусков:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "Переходите с v1?"
    v2 — мажорная версия с несовместимыми изменениями; все они описаны в
    **[руководстве по миграции](../migration.md)**. Если ваш *пакет* зависит от `mcp` и ещё не готов
    к переходу, сохраните верхнюю границу `<2` (например, `mcp>=1.28,<2`), чтобы при разрешении
    зависимостей без фиксированных версий оставаться на линейке 1.x.

## Что устанавливается {#what-gets-installed}

Чтобы пользоваться SDK, всё это знать не обязательно, но если интересно, зачем нужна каждая зависимость:

* `mcp-types`: все типы протокола (запросы, результаты, блоки содержимого) в виде отдельного пакета, версии которого выходят синхронно с SDK. Код, зависящий от `mcp`, импортирует его через псевдоним `mcp.types` (каждый `from mcp.types import ...` в этой документации); импортируйте `mcp_types` напрямую только в проекте, который устанавливает `mcp-types` без SDK.
* [`anyio`](https://anyio.readthedocs.io/): асинхронная среда выполнения. Весь SDK написан поверх anyio, поэтому работает как на `asyncio`, так и на `trio`.
* [`pydantic`](https://docs.pydantic.dev/): основа всех моделей `mcp.types`, а также вся генерация схем и валидация.
* [`httpx2`](https://pypi.org/project/httpx2/): HTTP-клиент, на котором построены *клиентские* транспорты Streamable HTTP и SSE, со встроенной поддержкой server-sent events.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/) и [`python-multipart`](https://pypi.org/project/python-multipart/): *серверные* HTTP-транспорты.
* [`jsonschema`](https://pypi.org/project/jsonschema/): проверяет структурированный вывод инструмента на соответствие объявленной выходной схеме.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): работа с OAuth-токенами для авторизации.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): только лёгкий API, поэтому middleware трассировки в SDK ничего не стоит, пока вы сами не установите SDK и экспортёр OpenTelemetry.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) и [`typing-inspection`](https://pypi.org/project/typing-inspection/): современные возможности типизации на Python 3.10.
* [`pywin32`](https://pypi.org/project/pywin32/): только для Windows, используется для управления подпроцессами `stdio`.

## Дополнительные компоненты {#optional-extras}

* `mcp[cli]` добавляет [`typer`](https://typer.tiangolo.com/) и [`python-dotenv`](https://pypi.org/project/python-dotenv/) для утилиты командной строки `mcp` (`mcp dev`, `mcp run`, `mcp install`). Во время разработки она пригодится; в развёрнутом сервере может и не понадобиться.
* `mcp[rich]` добавляет [`rich`](https://rich.readthedocs.io/) для более красивых логов сервера.
