---
translation:
  sections: [424930166c4bc6f3]
  tool: 1
---
# Im Handler {#inside-your-handler}

Die Argumente eines Handlers kommen vom Client. Alles *andere*, was er lesen kann, und alles, was er tun kann, während er läuft, steht hier.

Was er lesen kann:

* **[Der Context](context.md)** ist der eine zusätzliche Parameter, den jeder Handler anfordern kann: der laufende Request, seine Header, seine Session sowie die Verben für Fortschritt und Änderungsbenachrichtigungen.
* **[Abhängigkeiten](dependencies.md)** sind Parameter, die das Modell nie sieht – deine eigenen Funktionen füllen sie mit `Resolve`.
* **[Lifespan](lifespan.md)** behandelt Zustand, den dein Server einmal beim Start aufbaut, und wie ein Handler ihn über den `Context` erreicht.

Was er tun kann, während er läuft:

* Die Person am Host um weitere Eingaben bitten – mit **[Elicitation](elicitation.md)** (Rückfrage bei der Person am Host) und **[Multi-Roundtrip-Requests](multi-round-trip.md)** (multi-round-trip requests), dem Muster aus 2026-07-28, das sie transportiert.
* Den Client um die Antwort eines LLM oder um seine Arbeitsverzeichnisse bitten – mit **[Sampling und Roots](sampling-and-roots.md)**, veraltet, aber weiterhin bedient.
* **[Fortschritt](progress.md)** bei etwas Langsamem melden.
* Logs schreiben (auf die Standardfehlerausgabe, für alle, die den Server betreiben) – mit **[Logging](logging.md)**.
* Abonnierten Clients mitteilen, dass sich etwas geändert hat – mit **[Abonnements](subscriptions.md)**.

Wenn du noch keinen Handler registriert hast, beginne mit **[Tools](../servers/tools.md)**. Jede Seite hier setzt voraus, dass du einen hast.
