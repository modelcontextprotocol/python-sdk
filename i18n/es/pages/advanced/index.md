---
translation:
  sections: [ca6988b7503cd2d3]
  tool: 1
---
# Avanzado {#advanced}

Todo lo que necesita un servidor o un cliente normal tiene su sitio temático en las secciones anteriores.
Esta sección reúne las vías de escape a las que recurres cuando la capa de conveniencia de `MCPServer`
te estorba:

* **[El Server de bajo nivel](low-level-server.md)**: la clase sobre la que está construido `MCPServer`.
  Esquemas escritos a mano, handlers `on_*`, nada se comprueba por ti, y métodos JSON-RPC
  personalizados propios.
* **[Paginación](pagination.md)** y **[Middleware](middleware.md)**: dos cosas que
  *solo* puedes hacer en el `Server` de bajo nivel.
* **[Extensiones](extensions.md)** y **[MCP Apps](apps.md)**: la superficie de
  extensión del protocolo. Compón paquetes de extensión en un servidor o escribe los tuyos.

Algunas cosas que sería razonable buscar aquí viven, en cambio, donde realmente las
usarías:

* **Autorización** está en **[Ejecutar tu servidor](../run/index.md)**, porque un
  servidor se protege donde se despliega.
* **OAuth**, la **aserción de identidad**, la conexión a **varios servidores** y la
  **caché** de respuestas están en **[Clientes](../client/index.md)**.
* Las **solicitudes de varias idas y vueltas (multi-round-trip)** y las **suscripciones** están en
  **[Dentro de tu handler](../handlers/index.md)**, porque ambas son cosas que un
  handler *hace*.
* Las **plantillas de URI** están en **[Servidores](../servers/index.md)**, junto a Recursos.
* **[Versiones del protocolo](../protocol-versions.md)** y
  **[Funcionalidades obsoletas](../deprecated.md)** tienen cada una su propia página de nivel superior.

Si no tienes claro si necesitas esta sección, no la necesitas.
