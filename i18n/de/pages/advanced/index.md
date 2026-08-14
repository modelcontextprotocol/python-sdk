---
translation:
  sections: [ca6988b7503cd2d3]
  tool: 1
---
# Für Fortgeschrittene {#advanced}

Alles, was ein gewöhnlicher Server oder Client braucht, hat in den Abschnitten oben sein thematisches Zuhause.
Dieser Abschnitt versammelt die Notausgänge, zu denen du greifst, wenn die Komfortschicht
von `MCPServer` im Weg ist:

* **[Der Low-Level-Server](low-level-server.md)**: die Klasse, auf der `MCPServer` aufbaut.
  Handgeschriebene Schemas, `on_*`-Handler, keine Prüfungen, die dir abgenommen werden, und
  eigene JSON-RPC-Methoden.
* **[Paginierung](pagination.md)** und **[Middleware](middleware.md)**: zwei Dinge, die
  *nur* auf dem Low-Level-`Server` gehen.
* **[Erweiterungen](extensions.md)** und **[MCP Apps](apps.md)**: die
  Erweiterungsfläche des Protokolls. Kombiniere Erweiterungspakete zu einem Server oder schreibe deine eigenen.

Einiges, was du mit gutem Grund hier suchen könntest, steht stattdessen dort, wo du es
tatsächlich einsetzt:

* **Autorisierung** steht unter **[Den Server betreiben](../run/index.md)**, weil du
  einen Server dort schützt, wo du ihn bereitstellst.
* **OAuth**, **Identity Assertion**, die Verbindung zu **mehreren Servern** und der
  Response-**Cache** stehen alle unter **[Clients](../client/index.md)**.
* **Multi-Roundtrip-Requests** (multi-round-trip requests) und **Abonnements** stehen unter
  **[Im Handler](../handlers/index.md)**, weil beides etwas ist, das ein
  Handler *tut*.
* **URI-Templates** steht unter **[Server](../servers/index.md)**, neben den Ressourcen.
* **[Protokollversionen](../protocol-versions.md)** und
  **[Veraltete Features](../deprecated.md)** haben jeweils eine eigene Seite auf oberster Ebene.

Wenn du nicht sicher bist, ob du diesen Abschnitt brauchst, brauchst du ihn nicht.
