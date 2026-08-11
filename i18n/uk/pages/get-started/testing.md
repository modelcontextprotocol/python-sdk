---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# Тестування {#testing}

Python SDK містить клас `Client` із **транспортом у пам'яті**: передайте йому об'єкт сервера — і він під'єднається до нього напряму.

Жодного підпроцесу. Жодного порту. Узагалі жодного транспорту. Та сама ідея, що й `TestClient` у FastAPI.

## Базове використання {#basic-usage}

Припустімо, є простий сервер з одним інструментом:

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

Щоб запустити тест нижче, знадобляться дві додаткові залежності (для розробки):

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    Ця документація припускає, що ви вже знайомі з [`pytest`](https://docs.pytest.org/en/stable/).

    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) — це те, чим тест нижче
    перевіряє весь об'єкт результату одним рядком. Він записує вивід тесту у вигляді
    літерала `snapshot(...)`, який ви бачите. Якщо не хочете ним користуватися, приберіть імпорт і
    перевіряйте потрібні поля (`result.content[0].text == "3"`), як у будь-якому іншому тесті.

Тепер сам тест:

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

1. Якщо ви використовуєте `trio`, поверніть натомість `"trio"`. Подробиці — у [документації anyio](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on).
2. Фікстура віддає під'єднаного клієнта. Кожен тест, що приймає `client`, отримує нове з'єднання в пам'яті з тим самим сервером.

Готово! Тепер можна розширювати тести, щоб охопити більше сценаріїв.

## Навіщо `raise_exceptions=True`? {#why-raise_exceptionstrue}

Піти не так можуть дві різні речі, і цей прапорець стосується лише однієї з них.

Виняток усередині одного з **ваших інструментів** — це не збій протоколу. Він стає звичайним результатом
з `is_error=True`, і модель читає повідомлення. `raise_exceptions` цього не змінює: з ним чи
без нього `call_tool` повертає той самий результат з `is_error=True`. Про це є ціла сторінка:
**[Обробка помилок](../servers/handling-errors.md)**.

Збій **поза** тілом інструмента — інша річ. На з'єднанні, яке дає `Client(mcp)`, сервер
замінює його загальним `"Internal server error"`, перш ніж його побачить клієнт. Ніколи не слід
розкривати подробиці неочікуваного падіння віддаленій стороні, що викликає. У тесті це саме те,
чого ви *не* хочете, і саме це змінює `raise_exceptions=True`: тест бачить справжнє повідомлення
замість узагальненого.

Залишайте його ввімкненим у тестах. У робочому коді він не має сенсу.

## У тому самому процесі за замовчуванням {#in-process-by-default}

!!! note
    `Client(mcp)` під'єднується в межах процесу й за замовчуванням **нейтральний щодо покоління**: він зондує сервер і
    обирає відповідний шлях протоколу. Зафіксуйте `mode="legacy"`, якщо тест перевіряє семантику, специфічну для
    старого покоління — push семплювання (sampling) чи еліцитації (elicitation), `message_handler`, — і приберіть там `raise_exceptions=True`:
    з'єднання старого покоління взагалі нічого не узагальнює, а прапорець повторно викидає
    збій усередині завдання сервера, а не у вашому тесті.

Цей один рядок — ще й причина, чому ця документація може обіцяти, що її приклади працюють: кожен
файл прикладу проганяється власним набором тестів SDK, майже всі — саме через цей
клієнт. Ви користуєтеся тим самим інструментом, яким SDK перевіряє сам себе.

У вас є робочий, протестований сервер. Як помістити його в справжній застосунок (Claude Desktop,
IDE) — на сторінці **[Під'єднання до справжнього хоста](real-host.md)**; усі інші способи його запустити —
у розділі **[Запуск сервера](../run/index.md)**.
