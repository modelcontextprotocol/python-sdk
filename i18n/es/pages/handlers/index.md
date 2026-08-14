---
translation:
  sections: [424930166c4bc6f3]
  tool: 1
---
# Dentro de tu handler {#inside-your-handler}

Los argumentos de un handler vienen del cliente. Todo lo *demás* que puede leer, y todo lo que puede hacer mientras se ejecuta, está aquí.

Lo que puede leer:

* **[El Context](context.md)** es el único parámetro extra que cualquier handler puede pedir: la solicitud en curso, sus cabeceras, su sesión y los verbos de progreso y de notificación de cambios.
* **[Dependencias](dependencies.md)** son parámetros que el modelo nunca ve, rellenados por tus propias funciones con `Resolve`.
* **[Lifespan](lifespan.md)** cubre el estado que el servidor construye una sola vez al arrancar, y cómo un handler llega a él a través del `Context`.

Lo que puede hacer mientras se ejecuta:

* Pedir más datos al usuario con **[Elicitación](elicitation.md)**, y con **[Solicitudes de varias idas y vueltas](multi-round-trip.md)**, el patrón de 2026-07-28 que la transporta.
* Pedir al cliente una respuesta de su LLM o sus carpetas de trabajo con **[Muestreo y roots](sampling-and-roots.md)**, obsoletos pero todavía atendidos.
* Informar del **[Progreso](progress.md)** de algo lento.
* Escribir logs (en el error estándar, para quien opere el servidor) con **[Logging](logging.md)**.
* Avisar a los clientes suscritos de que algo cambió con **[Suscripciones](subscriptions.md)**.

Si todavía no has registrado ningún handler, empieza por **[Herramientas](../servers/tools.md)**. Todas las páginas de esta sección suponen que ya tienes uno.
