---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# Тестирование {#testing}

В Python SDK есть класс `Client` со **встроенным in-memory транспортом**: передайте ему объект сервера, и он подключится к нему напрямую.

Ни подпроцесса. Ни порта. Вообще никакого транспорта. Та же идея, что и `TestClient` в FastAPI.

## Базовое использование {#basic-usage}

Предположим, есть простой сервер с одним инструментом:

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

Чтобы запустить тест ниже, понадобятся две дополнительные зависимости (для разработки):

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    Эта документация предполагает, что вы уже знакомы с [`pytest`](https://docs.pytest.org/en/stable/).

    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) — то, с помощью чего
    тест ниже проверяет весь объект результата одной строкой. Библиотека записывает вывод теста
    в виде литерала `snapshot(...)`, который вы видите. Если не хотите её использовать, уберите
    импорт и проверяйте нужные поля (`result.content[0].text == "3"`), как в любом другом тесте.

Теперь сам тест:

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. Если используете `trio`, верните вместо этого `"trio"`. Подробности — в [документации anyio](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on).
2. Фикстура отдаёт подключённый клиент. Каждый тест, принимающий `client`, получает свежее in-memory подключение к тому же серверу.

Готово! Теперь можно расширять тесты, чтобы покрыть больше сценариев.

## Зачем `raise_exceptions=True`? {#why-raise_exceptionstrue}

Пойти не так могут две разные вещи, и этот флаг касается только одной из них.

Исключение внутри одного из **ваших инструментов** — не сбой протокола. Оно превращается в
обычный результат с `is_error=True`, и модель читает сообщение. `raise_exceptions` этого не
меняет: с ним или без него `call_tool` возвращает один и тот же результат с `is_error=True`.
Этому посвящена целая страница: **[Обработка ошибок](../servers/handling-errors.md)**.

Сбой **вне** тела инструмента — другое дело. На подключении, которое даёт `Client(mcp)`, сервер
очищает его до обобщённого `"Internal server error"`, прежде чем оно дойдёт до клиента. Детали
неожиданного падения никогда не должны утекать к удалённому вызывающему. В тесте это ровно то,
чего вы *не* хотите, и именно это меняет `raise_exceptions=True`: тест видит настоящее сообщение
вместо очищенного.

В тестах оставляйте его включённым. В продакшен-коде он не имеет смысла.

## Внутри процесса по умолчанию {#in-process-by-default}

!!! note
    `Client(mcp)` подключается внутри процесса и по умолчанию **не привязан к поколению
    протокола**: он опрашивает сервер и выбирает подходящий путь протокола. Зафиксируйте
    `mode="legacy"`, если тест проверяет семантику, специфичную для подключений старого
    поколения (push-сообщения сэмплирования (sampling) или элицитации (elicitation),
    `message_handler`), и уберите там `raise_exceptions=True`: подключение старого поколения
    вообще ничего не очищает, а флаг повторно выбрасывает сбой внутри задачи сервера, а не в
    вашем тесте.

Именно благодаря этой одной строке документация может обещать, что её примеры работают: каждый
файл с примером прогоняется собственным набором тестов SDK, и почти все — ровно через этот
клиент. Вы пользуетесь тем же инструментом, которым SDK проверяет сам себя.

У вас есть работающий, протестированный сервер. Как поместить его в настоящее приложение
(Claude Desktop, IDE) — на странице **[Подключение к настоящему хосту](real-host.md)**; все
остальные способы его запустить — в разделе **[Запуск сервера](../run/index.md)**.
