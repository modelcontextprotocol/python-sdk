---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# Paginierung {#pagination}

Die meisten Server brauchen das nie.

`MCPServer` beantwortet jeden `list_*`-Request mit allem, was er hat, auf einer Seite, `next_cursor=None`. Bei ein paar Dutzend Tools, Ressourcen oder Prompts ist das die richtige Antwort, und es gibt nichts zu konfigurieren.

Paginierung ist für den Server gedacht, dessen Ressourcenliste in Wahrheit eine Datenbank ist: Tausende Zeilen, die er nicht in einer einzigen Response serialisieren will. Die Antwort des Protokolls darauf ist ein **Cursor**: Der Server gibt eine Seite plus ein opakes Token zurück, und der Client schickt dieses Token zurück, um die nächste Seite zu bekommen.

`@mcp.resource()` hat dafür keinen Einstiegspunkt. Um seitenweise auszuliefern, schreibst du den List-Handler selbst, auf dem **[Low-Level-Server](low-level-server.md)**.

## Ein Server, der paginiert {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* Auf einem Low-Level-`Server` sind Handler Konstruktorargumente, keine Dekoratoren. `on_list_resources` beantwortet jeden `resources/list`-Request; mehr Verkabelung gibt es nicht.
* Jeder paginierte Handler ist als `params: PaginatedRequestParams | None` typisiert, und das Beispiel akzeptiert beides. Über eine Verbindung übergibt dir das SDK jedoch nie `None` (ein Request ohne `params`-Member erreicht den Handler als Modell mit seinen Standardwerten). Das Signal, auf das es ankommt, ist daher `params.cursor is None`: **von vorne beginnen**.
* Du entscheidest, was ein Cursor *ist*. Hier ist es ein Offset, als String dargestellt. Ein Zeitstempel, ein Primärschlüssel, ein Base64-Blob: alles, was du beim Herausgeben erzeugen und beim Zurückkommen wiedererkennen kannst.
* Mit `next_cursor=None` sagst du „das war die letzte Seite“. Es gibt keine Anzahl, keine Gesamtsumme, kein `has_more`. `None` ist das ganze Signal.

!!! tip
    Eine `PAGE_SIZE` von 10 macht das Beispiel lesbar. Wähle deine pro Endpunkt: Eine Liste
    einzeiliger Ressourcen verträgt eine Seite mit 500 Einträgen; eine Liste fetter Prompt-Templates nicht.
    Der Client hat dabei nichts mitzureden, und das ist Absicht.

### Ausprobieren {#try-it}

`Client(server)` verbindet sich im Speicher mit einem Low-Level-`Server` genau so, wie er sich mit einem `MCPServer` verbindet.

Rufe `list_resources()` ohne Argumente auf. Du bekommst zehn Ressourcen, `book-1` bis `book-10`, und `next_cursor` ist der String `"10"`.

Gib ihn mit `list_resources(cursor="10")` zurück, und die erste Ressource ist `book-11`, der neue `next_cursor` ist `"20"`.

Die zehnte Seite kommt mit `next_cursor` auf `None` zurück. Fertig.

## Die Client-Schleife {#the-client-loop}

Jede `list_*`-Methode auf `Client` (`list_tools`, `list_resources`, `list_resource_templates`, `list_prompts`) nimmt ein Keyword-Argument `cursor=`. Eine paginierte Liste leerzulesen ist ein einziges `while True`:

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor` beginnt als `None`, der erste Request trägt also keinen Cursor.
* Erweitere die Liste, **bevor** du auf `next_cursor` schaust: Auch die letzte Seite enthält Ressourcen.
* `next_cursor is None` ist der Ausstieg. Alles andere geht unverändert direkt zurück in `cursor=`.

Führe sein `main()` aus, und es gibt `100 resources` aus: zehn Seiten zu je zehn, zusammengefügt von einer Schleife, die nie wusste, dass es zehn Seiten waren.

Das ist dieselbe Schleife, die **[Der Client](../client/index.md)** für jedes `list_*`-Verb zeigt, und sie kostet nichts gegenüber einem Server, der nicht paginiert: `next_cursor` ist schon in der ersten Response `None`, und die Schleife läuft genau einmal.

## Die drei Regeln {#the-three-rules}

**Cursor sind opak.** Ein Client darf einen Cursor nie parsen, bauen oder erraten. Die einzige zulässige Quelle eines Cursors ist der `next_cursor` der vorherigen Seite, wortwörtlich.

**Der Server bestimmt die Seitengröße.** Es gibt kein `limit=` im Protokoll. Wenn du eine andere Seitengröße brauchst, änderst du den Server.

**Ein Client, der Paginierung ignoriert, funktioniert trotzdem.** Er ruft `list_resources()` einmal auf, bekommt die ersten zehn und bemerkt den `next_cursor`, den er weggeworfen hat, nie. Nichts geht kaputt; er sieht nur weniger.

!!! check
    Opak heißt opak. Erfinde einen Cursor (`list_resources(cursor="page-2")`), und das
    Protokoll kann nichts für dich tun. Dieser Server versucht `int("page-2")`, der Handler löst eine Exception aus,
    und beim Client kommt an:

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    Ein Cursor, den du nicht vom Server bekommen hast, ist ein Bug, kein Feature-Wunsch.

## Zusammenfassung {#recap}

* `MCPServer` gibt alles auf einer Seite zurück. Paginierung ist optional, und du aktivierst sie auf dem Low-Level-`Server`.
* `on_list_resources` (und `on_list_tools`, `on_list_prompts`, `on_list_resource_templates`) erhält `PaginatedRequestParams | None`; `params.cursor` ist bei der ersten Seite `None`.
* Du gibst eine Seite plus `next_cursor` zurück: einen beliebigen String, den du später wiedererkennst, oder `None`, wenn nichts mehr übrig ist.
* Die Client-Schleife: `cursor=` übergeben, sammeln, wiederholen, bis `next_cursor is None`.
* Cursor sind opak, die Seitengröße gehört dem Server, und ein Client ohne Paginierung bekommt trotzdem Seite eins.

Der Rest der handgeschriebenen `Server`-API (`on_call_tool`, `input_schema`-Dicts, `_meta`) steht in **[Der Low-Level-Server](low-level-server.md)**.
