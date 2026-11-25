---
translation:
  sections: [09defc170a0da89d]
  tool: 1
---
# Server {#servers}

Ein `MCPServer` stellt einem verbundenen Client drei Primitive bereit. Sie
unterscheiden sich darin, wer über ihren Einsatz entscheidet:

* Ein **[Tool](tools.md)** ist eine Aktion, die das *Modell* auswählt und
  aufruft. Diese Seite wollen die meisten zuerst lesen, und
  **[Strukturierte Ausgabe](structured-output.md)** ist die zugehörige
  Referenz: alles über die Form dessen, was ein Tool zurückgibt.
* Eine **[Ressource](resources.md)** sind schreibgeschützte Daten, die die
  *Anwendung* zu lesen beschließt. **[URI-Templates](uri-templates.md)** ist
  die zugehörige Referenz: die vollständige Adressierungssyntax und die Regeln
  zur Pfadsicherheit.
* Ein **[Prompt](prompts.md)** ist eine Nachrichtenvorlage, die eine *Person*
  beim Namen aufruft – über ein Menü oder einen Slash-Befehl.

Rund um die drei Primitive liegt der Rest dessen, was ein Server deklariert:

* **[Vervollständigungen](completions.md)** ist serverseitige
  Autovervollständigung für Argumente von Prompts und Ressourcen-Templates.
* **[Bilder, Audio und Icons](media.md)** behandelt alles, was ein Tool
  außer Text zurückgeben kann, sowie die Icons, die ein Client neben deinem
  Server anzeigt.
* **[Fehler behandeln](handling-errors.md)** erklärt den Unterschied zwischen
  einem Fehler, von dem sich das Modell erholen kann, und einem, den es nie zu
  sehen bekommen darf.

Jede Seite hier steht für sich; spring direkt zu der, die du brauchst. Hast du
noch keinen Server gebaut, beginne stattdessen mit
**[Erste Schritte](../get-started/first-steps.md)**.

Was *innerhalb* der Funktionen passiert, die du registrierst (der `Context`,
Dependency Injection, die Person mitten im Aufruf um weitere Eingaben bitten),
ist Thema des nächsten Abschnitts, **[Im Handler](../handlers/index.md)**.
