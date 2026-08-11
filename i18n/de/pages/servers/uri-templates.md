---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# URI-Templates und Pfadsicherheit {#uri-templates-and-path-safety}

Dies ist die Referenz für die URI-Template-Syntax, die
[`@mcp.resource`](resources.md) akzeptiert, und für die
Pfadsicherheitsrichtlinie, die das SDK auf extrahierte Werte anwendet. Eine
Einführung, was Ressourcen sind und wann du sie einsetzt, findest du in
**[Ressourcen](resources.md)**; diese Seite setzt voraus, dass du bereits
sicher im Deklarieren einer Ressource bist und den vollständigen
Operatorsatz, die Sicherheitseinstellungen oder die Low-Level-Verdrahtung
suchst.

Die Template-Syntax ist [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570).
Das SDK unterstützt eine Teilmenge, die für das Matching eingehender
`resources/read`-URIs ausgewählt wurde, plus eine Sicherheitsschicht, die
Werte ablehnt, die außerhalb des Verzeichnisses landen würden, das du
bereitstellen willst. Die Details auf Protokollebene (Nachrichtenformate,
Lebenszyklus, Paginierung) stehen in der
[MCP-Ressourcen-Spezifikation](https://modelcontextprotocol.io/specification/latest/server/resources).

## Der vollständige Operatorsatz {#the-full-operator-set}

Der einfache Platzhalter `{user_id}` ist der, den **[Ressourcen](resources.md)** einführt. Es gibt vier weitere
Operatorformen; hier stehen sie alle auf einem Server, damit du sie
nebeneinander siehst:

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

Jeder hervorgehobene Dekorator zerlegt den URI auf eine andere Weise.
Die folgenden Abschnitte gehen sie von oben nach unten durch.

### Einfache Expansion: `{name}` {#simple-expansion-name}

`books://{isbn}` ist die schlichte Alltagsform. Der Platzhalter wird auf
den Parameter `isbn` abgebildet, sodass ein Client, der
`books://978-0441172719` liest, `get_book("978-0441172719")` aufruft.

Ein einfaches `{name}` endet am ersten `/`. `books://978/extra` passt
nicht, weil der Schrägstrich nach `978` die Erfassung beendet und `/extra`
übrig bleibt.

### Typkonvertierung {#type-conversion}

Extrahierte Werte kommen als Strings an, aber du kannst einen genaueren
Typ deklarieren, und das SDK konvertiert. `orders://{order_id}` landet in
einer Funktion, deren Parameter `order_id: int` ist, sodass das Lesen von
`orders://12345` `get_order(12345)` aufruft, nicht `get_order("12345")`. Der
Handler rechnet damit (`order_id + 1`), ohne zu casten.

### Mehrteilige Pfade: `{+name}` {#multi-segment-paths-name}

Um einen Wert zu erfassen, der Schrägstriche enthält, verwende `{+name}`. Mit
`manuals://{+path}`:

* `manuals://returns.md` ergibt `path = "returns.md"`
* `manuals://printing/setup.md` ergibt `path = "printing/setup.md"`

Greif zu `{+name}`, wann immer der Wert hierarchisch ist: Dateisystempfade,
verschachtelte Objektschlüssel, URL-Pfade, die du als Proxy weiterreichst.

### Query-Parameter: `{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}` setzt `limit` und `sort` hinter das `?`.
Der Pfad bestimmt, *welches* Buch; die Query steuert, *wie* du es liest.

Query-Parameter werden nachsichtig abgeglichen: Die Reihenfolge spielt keine
Rolle, zusätzliche werden ignoriert, und weggelassene fallen auf die
Standardwerte deiner Funktion zurück. `reviews://978-0441172719` verwendet
also `limit=10, sort="newest"`, und
`reviews://978-0441172719?sort=top` überschreibt nur `sort`.

### Pfadsegmente als Liste: `{/name*}` {#path-segments-as-a-list-name}

Wenn du jedes Pfadsegment als eigenes Listenelement haben willst statt als
einen String mit Schrägstrichen, verwende `{/name*}`. Mit
`shelves://browse{/path*}` ruft ein Client, der
`shelves://browse/fiction/sci-fi` liest,
`browse_shelf(["fiction", "sci-fi"])` auf.

### Template-Referenz {#template-reference}

Die häufigsten Muster:

| Muster       | Beispieleingabe       | Du bekommst             |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | *kein Treffer* (endet am `/`) |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### Was der Parser ablehnt {#what-the-parser-rejects}

Einige Template-Formen werden vorab abgefangen, statt beim ersten Request
zu scheitern. `@mcp.resource` parst das Template, wenn der Dekorator läuft,
sodass keine davon je einen laufenden Server erreicht.

`UriTemplate.parse()` löst `InvalidUriTemplate` aus bei:

* **Zwei Variablen ohne etwas dazwischen.** `manuals://{+path}{ext}`
  wird abgelehnt: Das Matching kann nicht erkennen, wo `path` endet und `ext`
  beginnt. Setze ein Literal dazwischen (`manuals://{+path}/{ext}`) oder
  verwende einen Operator, der seinen eigenen Trenner mitbringt.
  `manuals://{+path}{.ext}` wird akzeptiert, weil `{.ext}` den `.` selbst
  beisteuert.
* **Mehr als eine mehrteilige Variable.** Höchstens eines von `{+var}`,
  `{#var}` oder einer explodierten Variable (`{/var*}`, `{.var*}`, `{;var*}`)
  pro Template. Zwei sind grundsätzlich mehrdeutig: Es gibt keinen
  begründbaren Weg zu entscheiden, welche ein zusätzliches Segment aufnimmt.
* **Den üblichen Syntaxfehlern**: eine nicht geschlossene geschweifte
  Klammer, ein doppelt verwendeter Variablenname oder ein RFC-6570-Feature,
  das das SDK nicht unterstützt, etwa der Präfix-Modifikator `{var:3}` oder
  die Query-Explosion `{?vars*}`.

Darüber hinaus löst `@mcp.resource` einen `ValueError` aus, wenn ein
Handler-Parameter an eine Query-Variable im abschließenden
`{?...}`/`{&...}`-Lauf des Templates gebunden ist, aber keinen
Python-Standardwert hat. Diese Variablen werden nachsichtig abgeglichen
(ein Client darf jede davon weglassen), sodass ein Parameter ohne
Standardwert erst beim ersten Request, der ihn weglässt, als
undurchsichtiger interner Fehler auftauchen würde.
`reviews://{isbn}{?limit,sort}` im Server oben ist die wohlgeformte
Variante: `limit` und `sort` tragen beide Standardwerte.

## Sicherheit {#security}

Template-Parameter kommen vom Client. Fließen sie ungeprüft in
Dateisystem- oder Datenbankoperationen, können Werte wie
`../../etc/passwd` außerhalb des Verzeichnisses landen, das du
bereitstellen wolltest.

### Was das SDK standardmäßig prüft {#what-the-sdk-checks-by-default}

Bevor dein Handler läuft, lehnt das SDK jeden Parameter ab, der:

* sein Ausgangsverzeichnis über `..`-Komponenten verlassen würde
* wie ein absoluter Pfad aussieht (`/etc/passwd`, `C:\Windows`) oder wie
  ein laufwerksrelativer Windows-Pfad (`C:foo`). Ein laufwerksrelativer
  Wert und ein Bezeichner mit Namensraum wie `x:y` sind als Strings nicht
  zu unterscheiden, daher wird standardmäßig jeder Wert aus einem einzelnen
  Buchstaben plus Doppelpunkt abgelehnt; nimm den Parameter aus, wenn er
  solche Werte legitim erhält
* ein Nullbyte (`\x00`) enthält

Die `..`-Prüfung arbeitet komponentenbasiert, nicht als Teilstringsuche.
Werte wie `v1.0..v2.0` oder `HEAD~3..HEAD` kommen durch, weil `..` dort
kein eigenständiges Pfadsegment ist.

Diese Prüfungen gelten für den dekodierten Wert, sie fangen Traversal also
unabhängig davon ab, wie es im URI kodiert war (`../etc`, `..%2Fetc`,
`%2E%2E/etc`, `..%5Cetc`, `%00` werden alle abgefangen).

!!! check
    Lies `manuals://../etc/passwd` vom Server oben, und der Request wird
    rundweg abgelehnt: Das Template-Matching stoppt beim ersten Fehlschlag,
    sodass kein späteres (womöglich großzügigeres) Template als Fallback
    probiert wird. Der Client sieht denselben `-32602`-Fehler „Unknown
    resource“ wie bei einem URI, der auf gar kein Template passt, und
    `read_manual` läuft nie.

### Dateisystem-Handler: safe_join verwenden {#filesystem-handlers-use-safe_join}

Die eingebauten Prüfungen stoppen die häufigen Fälle, können aber deine
Sandbox-Grenze nicht kennen. Für Dateisystemzugriffe verwende `safe_join`,
um den Pfad aufzulösen und zu verifizieren, dass er innerhalb deines
Basisverzeichnisses bleibt:

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join` fängt Symlink-Ausbrüche, `..`-Sequenzen und Tricks mit
absoluten Pfaden ab, die eine einfache Stringprüfung übersehen würde.
Verlässt der aufgelöste Pfad `DOCS_ROOT`, löst es `PathEscapeError` aus,
der beim Client als `ResourceError` ankommt.

### Wenn die Standardwerte im Weg stehen {#when-the-defaults-get-in-the-way}

Manchmal blockieren die Prüfungen legitime Werte. Ein Tool für den
Katalogimport könnte absichtlich einen absoluten Pfad erhalten, oder ein
Parameter könnte eine relative Referenz wie `../sibling` sein, die dein
Handler sicher interpretiert, ohne das Dateisystem anzufassen. Nimm diesen
Parameter aus oder lockere die Richtlinie für den ganzen Server:

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* `security=ResourceSecurity(exempt_params={"source"})` am Dekorator
  überspringt die Prüfungen für diesen einen Parameter auf dieser einen
  Ressource. Der Rest des Servers behält die Standardrichtlinie.
* `resource_security=` am `MCPServer`-Konstruktor setzt den Standard
  für jede Ressource. Hier schaltet `relaxed` die `..`-Prüfung ganz ab.

Die konfigurierbaren Prüfungen:

| Einstellung             | Standardwert | Was sie tut                    |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | Lehnt `..`-Sequenzen ab, die das Ausgangsverzeichnis verlassen |
| `reject_absolute_paths` | `True`  | Lehnt `/foo`, `C:\foo`, UNC-Pfade und laufwerksrelatives `C:foo` ab (fängt auch `x:y` ab) |
| `reject_null_bytes`     | `True`  | Lehnt Werte ab, die `\x00` enthalten |
| `exempt_params`         | leer    | Parameternamen, für die Prüfungen übersprungen werden |

Diese Prüfungen sind ein heuristischer Vorfilter; für Dateisystemzugriffe
bleibt `safe_join` die Eindämmungsgrenze.

!!! tip
    Kann dein Handler den Request nicht erfüllen (die Datei existiert nicht,
    die ID ist unbekannt), löse eine Exception aus. Das SDK macht daraus eine
    Fehler-Response. Den Unterschied zwischen einem Protokollfehler und einem
    Tool-Fehler erklärt **[Fehler behandeln](handling-errors.md)**.

## Ressourcen auf dem Low-Level-Server {#resources-on-the-low-level-server}

Wenn du auf dem Low-Level-`Server` aufbaust (siehe **[Der
Low-Level-Server](../advanced/low-level-server.md)**), registrierst du Handler für die
Protokollmethoden `resources/list` und `resources/read` direkt. Es gibt
keinen Dekorator; du gibst die Protokolltypen selbst zurück.

### Statische Ressourcen {#static-resources}

Für feste URIs führe eine Registry und verteile anhand exakter
Übereinstimmung:

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

Der List-Handler teilt Clients mit, was verfügbar ist; der Read-Handler
liefert den Inhalt. Prüfe zuerst deine Registry, falle auf Templates
(unten) zurück, falls du welche hast, und löse für alles andere eine
Exception aus.

### Templates {#templates}

Die Template-Engine, die `MCPServer` verwendet, liegt in
`mcp.shared.uri_template` und funktioniert eigenständig. Du bekommst
dasselbe Parsing und Matching; Routing und Sicherheitsrichtlinie
verdrahtest du selbst.

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

In den hervorgehobenen Zeilen passieren drei Dinge:

* **Einmal parsen, pro Request matchen.** `UriTemplate.parse()` baut das
  Template; `template.match(uri)` gibt die extrahierten Variablen als
  `dict` zurück, oder `None`, wenn der URI nicht passt. Die URL-Dekodierung
  geschieht innerhalb von `match()`; die dekodierten Werte werden unverändert
  zurückgegeben, ohne Pfadsicherheitsprüfung. Die Werte kommen als Strings
  heraus: Konvertiere sie selbst
  (`int(matched["id"])`, `Path(matched["path"])`).
* **Die Sicherheitsprüfungen selbst anwenden.** Die `..`- und
  Absolutpfad-Prüfungen, die `MCPServer` standardmäßig ausführt, liegen in
  `mcp.shared.path_security`. `read_manual_safely` ruft sie auf, bevor es
  `MANUALS` anfasst. Ist ein Parameter kein Dateisystempfad (eine ISBN, eine
  Suchanfrage), überspring die Prüfungen für diesen Wert: Du steuerst die
  Richtlinie pro Handler statt über ein Konfigurationsobjekt.
* **Die Templates aus derselben Quelle auflisten.** Clients entdecken
  Templates über `resources/templates/list`. `str(template)` gibt den
  ursprünglichen Template-String zurück, sodass Auflistung und Matcher
  eine einzige Quelle der Wahrheit teilen.

## Zusammenfassung {#recap}

* `{name}` passt auf ein Segment; `{+name}` behält die Schrägstriche;
  `{?a,b}` zieht aus dem Query-String; `{/name*}` teilt Segmente in eine
  Liste auf.
* Zwei Variablen ohne etwas dazwischen oder eine zweite mehrteilige
  Variable werden beim Parsen abgelehnt. Ein Parameter, der an eine
  abschließende `{?...}`/`{&...}`-Query-Variable gebunden ist, muss einen
  Python-Standardwert deklarieren.
* Annotiere den Parameter (`order_id: int`), und das SDK konvertiert.
* Die Standard-Sicherheitsrichtlinie lehnt `..`, absolute Pfade und
  Nullbytes ab, bevor dein Handler läuft; überschreibe sie pro Ressource
  mit `security=ResourceSecurity(...)` oder serverweit mit
  `resource_security=`.
* Für Dateisystemzugriffe ist `safe_join` die Eindämmungsgrenze.
* Auf dem Low-Level-`Server` parst du mit `UriTemplate.parse()`, matchst
  mit `.match()` und wendest `mcp.shared.path_security` selbst an.
