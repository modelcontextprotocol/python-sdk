---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# Встановлення {#installation}

Python SDK опубліковано на PyPI як [`mcp`](https://pypi.org/project/mcp/). Потрібен **Python 3.10+**.

Ця документація описує **v2** — поточну стабільну лінійку випусків:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "Переходите з v1?"
    v2 — мажорна версія з несумісними змінами; **[Посібник з міграції](../migration.md)**
    описує кожну з них. Якщо ваш *пакет* залежить від `mcp` і ще не готовий до міграції, залиште
    верхню межу `<2` (наприклад, `mcp>=1.28,<2`), щоб розв'язання залежностей без фіксованої версії залишалося на лінійці 1.x.

## Що встановлюється {#what-gets-installed}

Щоб користуватися SDK, нічого з цього знати не потрібно, але якщо цікаво, навіщо кожна залежність:

* `mcp-types`: усі типи протоколу (запити, результати, блоки вмісту) окремим пакетом, версія якого йде в ногу з SDK. Код, що залежить від `mcp`, імпортує його через псевдонім `mcp.types` (кожне `from mcp.types import ...` у цій документації); імпортуйте `mcp_types` напряму лише в проєкті, який встановлює `mcp-types` без SDK.
* [`anyio`](https://anyio.readthedocs.io/): асинхронне середовище виконання. Увесь SDK написано поверх anyio, тож він працює і на `asyncio`, і на `trio`.
* [`pydantic`](https://docs.pydantic.dev/): основа кожної моделі в `mcp.types`, а також уся генерація схем і валідація.
* [`httpx2`](https://pypi.org/project/httpx2/): HTTP-клієнт, на якому працюють *клієнтські* транспорти Streamable HTTP і SSE, із вбудованою підтримкою server-sent events.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/) і [`python-multipart`](https://pypi.org/project/python-multipart/): *серверні* HTTP-транспорти.
* [`jsonschema`](https://pypi.org/project/jsonschema/): перевіряє структурований вивід інструмента на відповідність оголошеній схемі виводу.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): робота з OAuth-токенами для авторизації.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): лише легкий API, тож middleware трасування в SDK нічого не коштує, доки ви самі не встановите OpenTelemetry SDK і експортер.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) і [`typing-inspection`](https://pypi.org/project/typing-inspection/): сучасні можливості типізації на Python 3.10.
* [`pywin32`](https://pypi.org/project/pywin32/): лише для Windows, використовується для керування підпроцесами `stdio`.

## Необов'язкові доповнення {#optional-extras}

* `mcp[cli]` додає [`typer`](https://typer.tiangolo.com/) і [`python-dotenv`](https://pypi.org/project/python-dotenv/) для інструмента командного рядка `mcp` (`mcp dev`, `mcp run`, `mcp install`). Під час розробки він знадобиться; на розгорнутому сервері може бути зайвим.
* `mcp[rich]` додає [`rich`](https://rich.readthedocs.io/) для охайніших логів сервера.
