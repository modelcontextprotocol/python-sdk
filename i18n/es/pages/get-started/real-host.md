---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# Conectarse a un host real {#connect-to-a-real-host}

Un **host** es la aplicación dentro de la que acaba tu servidor: Claude Desktop, Claude Code, un IDE. El host es con lo que habla el usuario. Dentro de él, un **cliente** MCP lanza tu servidor como un proceso hijo y se comunica con él a través del stdin y el stdout de ese proceso.

Esto significa que conectarse a un host es un único acto: le indicas **el comando que arranca tu servidor**. Todo lo que hay en esta página (dos comandos de CLI, tres archivos JSON) es un lugar distinto donde poner ese mismo comando.

## Un servidor, todos los hosts {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

Dos herramientas y un recurso, un solo archivo. Tres cosas de ese archivo importan para todos los hosts de abajo:

* `mcp.run()` sin argumentos arranca un servidor **stdio**: se bloquea, lee los mensajes del protocolo por stdin y los escribe por stdout. Ese es el transporte que hablan todos los hosts de esta página. El host arranca tu archivo como proceso hijo y es dueño de esas dos tuberías, y por eso conectarse siempre se reduce a "aquí tienes el comando". Nunca eliges un puerto, y nada escucha en ninguno.
* `run()` está bajo `if __name__ == "__main__":`. Todo lo de abajo **importa** este archivo en lugar de ejecutarlo, así que un `run()` sin protección arrancaría un servidor en cuanto cualquier cosa cargara el módulo.
* El objeto servidor es una variable global del módulo llamada `mcp`. Ese es el nombre que busca `mcp run` (`server` y `app` también funcionan). Si lo llamas de otra forma, lo nombras explícitamente: `mcp run server.py:bookshop`.

Esa es la última línea de Python de esta página. De aquí en adelante todo es configuración del host.

## El comando de arranque {#the-launch-command}

Todos los hosts de abajo reciben el mismo comando:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Un solo comando para todos porque `uv run --with` resuelve el SDK en un entorno nuevo al momento: funciona desde cualquier directorio y no necesita ni proyecto ni entorno virtual que activar. Aquí eso importa más que en ningún otro sitio, porque un host lanza tu servidor desde *su* directorio de trabajo con un entorno casi vacío, no desde tu shell.

También es el comando que `mcp install` escribe por ti en la configuración de Claude Desktop (abajo), así que lo que escribes a mano y lo que genera la herramienta coinciden, salvo por la versión exacta que fija la herramienta.

!!! tip "Si un host no encuentra `uv`"
    Un host lanza tu servidor con un `PATH` mínimo, y puede que `uv` no esté en él. Sustituye el
    `uv` a secas por la ruta absoluta que da `which uv` (macOS/Linux) o `where uv` (Windows). Eso es
    exactamente lo que escribe `mcp install`.

!!! note "Esta página es la historia local"
    Todo lo de aquí ejecuta tu servidor en la máquina donde está el host: el host lanza tu
    archivo, por stdio. Eso es justo lo correcto para una herramienta personal o de una sola
    máquina. Para dar un servidor a personas que *no* tienen tu archivo, repartes una **URL**, no un
    comando: el mismo objeto `mcp` servido por Streamable HTTP. **[Ejecutar tu servidor](../run/index.md)**
    es esa decisión en una sola tabla, y **[Desplegar y escalar](../run/deploy.md)** es el camino desde
    ahí hasta un nombre de host real.

    Y un host no es más que una aplicación con un cliente MCP dentro, así que tu propio código
    Python puede hacer el papel del host: **[Transportes del cliente](../client/transports.md)** lanza
    este mismo archivo como subproceso con `stdio_client(...)`, y **[Pruebas](testing.md)**
    se conecta a él en memoria, sin ningún proceso.

## Claude Desktop {#claude-desktop}

El único host que el SDK puede configurar por ti:

```bash
uv run mcp install server.py
```

Eso es todo. `mcp install` importa el archivo para leer el nombre del servidor, encuentra el archivo de configuración de Claude Desktop y escribe en él el comando de arranque. De paso convierte tu ruta en absoluta, así que no tienes que hacerlo.

No hay nada misterioso. Esta es la entrada que escribe:

```json
{
  "mcpServers": {
    "Bookshop": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--frozen",
        "--with",
        "mcp[cli]==2.0.0",
        "mcp",
        "run",
        "/absolute/path/to/server.py"
      ]
    }
  }
}
```

Es el comando de arranque de la sección anterior con tres añadidos: la ruta absoluta a `uv`, `--frozen` para que `uv` nunca reescriba un archivo de bloqueo que tenga cerca por casualidad, y una versión fijada exactamente a la de `mcp` que tienes instalada. Va a parar a `claude_desktop_config.json`, que vive en:

* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Puedes escribir ese archivo a mano. `mcp install` existe para que no cometas el error clásico (una ruta relativa) al hacerlo.

Cierra Claude Desktop por completo (no solo su ventana) y vuelve a abrirlo.

!!! warning
    `mcp install` falla con `Claude app not found` si el *directorio* de configuración de Claude Desktop
    todavía no existe. Instala Claude Desktop y ejecútalo una vez: eso es lo que crea el directorio.

!!! tip
    Claude Desktop arranca tu servidor en su propio proceso, así que las variables de entorno de tu
    shell no están ahí. `uv run mcp install server.py -v API_KEY=abc123` (o `-f .env`) las registra en el
    campo `env` de la entrada. `--name` sobrescribe el nombre de la entrada; por defecto es el `name` del servidor.

## Claude Code {#claude-code}

No hay ningún archivo que editar. Registra el servidor con la CLI `claude`; todo lo que va después de `--` es el comando de arranque.

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Ejecuta `/mcp` dentro de una sesión de Claude Code para confirmar que `bookshop` está conectado y sus herramientas aparecen listadas.

## Cursor {#cursor}

Crea `.cursor/mcp.json` en la raíz de tu proyecto.

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

El mismo `command` más `args`, bajo la misma clave `mcpServers` que usa Claude Desktop. El servidor aparece en los ajustes de MCP de Cursor con ambas herramientas listadas.

## VS Code {#vs-code}

Crea `.vscode/mcp.json` en la raíz de tu proyecto.

```json
{
  "servers": {
    "bookshop": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

Dos diferencias con el archivo de Cursor, y son las únicas dos: la clave contenedora es `servers`, no `mcpServers`, y cada entrada declara su `type`. Confirma el aviso de confianza y luego **MCP: List Servers** en la paleta de comandos muestra `bookshop` en ejecución.

!!! note
    Necesitas VS Code 1.99 o posterior con la extensión **GitHub Copilot** con sesión iniciada (basta con
    Copilot Free), y Copilot Chat debe estar en modo **Agent**, porque ningún otro modo llama a herramientas.

## No aparece {#it-doesnt-show-up}

Antes de tocar ninguna configuración de host, ejecuta tú mismo el comando de arranque:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

No imprime nada y no termina. Ese silencio es correcto: un servidor stdio está esperando a que un host hable primero por stdin (`Ctrl-C` para detenerlo). Un traceback o una salida inmediata es el error real, y ahora puedes leerlo en vez de adivinarlo a través de un host.

Una vez que ese comando se queda esperando, lo que queda es casi siempre una de estas tres cosas:

* **Una ruta relativa.** El host lanza tu servidor desde *su* directorio de trabajo, no desde aquel en el que lo registraste. `server.py` donde hace falta `/absolute/path/to/server.py` es el fallo más común de todos. Si el host tampoco encuentra `uv`, esa ruta también tiene que ser absoluta.
* **El host sigue ejecutando su configuración anterior.** Los hosts leen su configuración al arrancar. Claude Desktop en particular hay que *cerrarlo por completo* (no solo cerrar su ventana) y volver a abrirlo para que un cambio en `claude_desktop_config.json` surta efecto.
* **Algo llegó a stdout fuera de la ventana desviada.** En stdio, stdout *es* el protocolo. El SDK desvía a stderr la salida extraviada que se vacía mientras sirve, pero la salida vaciada a stdout antes de eso (un script contenedor que hace echo, un `print()` en tiempo de importación en un proceso sin búfer), o un `print()` en búfer que se drena al salir el intérprete, le entrega al host un mensaje corrupto y este corta la conexión. Registra con la configuración por defecto de `logging`, cuyo handler de stderr vacía cada registro; los handlers personalizados también deben evitar stdout. **[Registro](../handlers/logging.md)** tiene todos los detalles.

Claude Desktop guarda un log por servidor: `mcp-server-<NAME>.log` es el stderr de tu servidor, junto a `mcp.log` para las conexiones, bajo `~/Library/Logs/Claude` en macOS y `%APPDATA%\Claude\logs` en Windows.

Para cualquier cosa más allá de esas tres, **[Solución de problemas](../troubleshooting.md)** es la página.

## Resumen {#recap}

* Un **host** (Claude Desktop, un IDE) ejecuta un cliente MCP que lanza tu servidor como proceso hijo por stdio. Conectarse significa darle un comando de arranque.
* Ese comando es `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`: ningún entorno virtual que activar, funciona desde cualquier directorio.
* **Claude Desktop** es el único host que `mcp install` configura por ti. Escribe ese mismo comando (más la ruta absoluta a `uv`, `--frozen` y una versión fijada exactamente a la que tienes instalada) en `claude_desktop_config.json`, así que nunca tienes que hacerlo tú.
* **Claude Code** es `claude mcp add bookshop -- <launch command>`. **Cursor** es `.cursor/mcp.json` bajo `mcpServers`. **VS Code** es `.vscode/mcp.json` bajo `servers`, cada entrada con un `type`.
* Rutas absolutas en todas partes, reinicia el host tras editar su configuración y nunca dejes que nada salvo el SDK escriba en stdout.

Todos los hosts de esta página se conectaron al mismo archivo, con el mismo comando. Lo que ese archivo puede *exponer* es el resto de esta documentación: **[Herramientas](../servers/tools.md)**, **[Recursos](../servers/resources.md)** y todos los transportes aparte de stdio en **[Ejecutar tu servidor](../run/index.md)**.
