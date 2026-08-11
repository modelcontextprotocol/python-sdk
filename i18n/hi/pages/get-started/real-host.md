---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# असली host से connect करना {#connect-to-a-real-host}

**host** वह application है जिसके अंदर आपका server आखिरकार चलता है: Claude Desktop, Claude Code, कोई IDE। user इसी host से बात करता है। इसके अंदर एक MCP **client** आपके server को child process के रूप में launch करता है और उसी process के stdin और stdout पर उससे बात करता है।

यानी host से connect करना बस एक काम है: आप उसे **वह command बताते हैं जो आपका server शुरू करता है**। इस page पर जो कुछ है (दो CLI commands, तीन JSON files), वह उसी एक command को रखने की अलग-अलग जगहें हैं।

## एक server, हर host {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

दो tools और एक resource, एक ही file में। इस file की तीन बातें नीचे के हर host के लिए मायने रखती हैं:

* बिना arguments के `mcp.run()` एक **stdio** server शुरू करता है: यह block होता है, stdin पर protocol messages पढ़ता है और stdout पर लिखता है। इस page का हर host यही transport बोलता है। host आपकी file को child process के रूप में शुरू करता है और उन दोनों pipes का मालिक होता है, इसीलिए connect करना हमेशा बस "यह रहा command" ही होता है। आप कभी port नहीं चुनते, और किसी port पर कुछ listen नहीं करता।
* `run()` `if __name__ == "__main__":` के नीचे है। नीचे की हर चीज़ इस file को execute करने के बजाय **import** करती है, इसलिए बिना guard वाला `run()` module के load होते ही server शुरू कर देता।
* server object module-level global है जिसका नाम `mcp` है। `mcp run` इसी नाम को ढूँढता है (`server` और `app` भी चलते हैं)। कोई और नाम रखें तो उसे साफ़-साफ़ बताना होगा: `mcp run server.py:bookshop`।

इस page पर Python की यह आख़िरी line है। यहाँ से नीचे सब host configuration है।

## Launch command {#the-launch-command}

नीचे के हर host को यही एक command मिलता है:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

सबके लिए एक ही command, क्योंकि `uv run --with` उसी वक़्त SDK को एक नए environment में resolve कर देता है: यह किसी भी directory से चलता है और इसे न कोई project चाहिए, न activate करने के लिए कोई virtual environment। यहाँ यह बात कहीं और से ज़्यादा मायने रखती है, क्योंकि host आपके server को आपके shell से नहीं, बल्कि **अपनी** working directory से, लगभग खाली environment के साथ launch करता है।

यही वह command है जो `mcp install` आपके लिए Claude Desktop के config में लिखता है (नीचे देखें), इसलिए जो आप हाथ से लिखते हैं और जो tool बनाता है, दोनों मेल खाते हैं, सिवाय उस exact version pin के जो tool जोड़ता है।

!!! tip "अगर host को `uv` न मिले"
    host आपके server को बहुत छोटे `PATH` के साथ spawn करता है, और हो सकता है `uv` उसमें न हो। सिर्फ़
    `uv` की जगह `which uv` (macOS/Linux) या `where uv` (Windows) से मिला absolute path लिखें। `mcp install`
    ठीक यही लिखता है।

!!! note "यह page local setup की बात है"
    यहाँ की हर चीज़ आपके server को उसी machine पर चलाती है जिस पर host है: host आपकी
    file को stdio पर launch करता है। निजी या एक ही machine वाले tool के लिए यह बिल्कुल सही है। जिन
    लोगों के पास आपकी file **नहीं** है, उन्हें server देने के लिए आप command नहीं, **URL** देते हैं: वही
    `mcp` object, Streamable HTTP पर serve किया हुआ। **[अपना server चलाना](../run/index.md)**
    वह फ़ैसला एक table में रखता है, और **[Deploy और scale](../run/deploy.md)** वहाँ से
    असली hostname तक का रास्ता है।

    और host किसी application से ज़्यादा कुछ नहीं जिसके अंदर MCP client हो, इसलिए आपका अपना
    Python भी host की भूमिका निभा सकता है: **[Client transports](../client/transports.md)** इसी
    file को `stdio_client(...)` से subprocess के रूप में launch करता है, और **[Testing](testing.md)**
    बिना किसी process के, memory में ही उससे connect करता है।

## Claude Desktop {#claude-desktop}

वह इकलौता host जिसे SDK आपके लिए configure कर सकता है:

```bash
uv run mcp install server.py
```

बस इतना ही। `mcp install` server का नाम पढ़ने के लिए file को import करता है, Claude Desktop की config file ढूँढता है और उसमें launch command लिख देता है। साथ ही यह आपके path को absolute बना देता है, ताकि आपको न करना पड़े।

इसमें कोई रहस्य नहीं है। यह रही वह entry जो यह लिखता है:

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

यह ऊपर वाले section का launch command ही है, तीन चीज़ें जोड़कर: `uv` का absolute path, `--frozen` ताकि `uv` आस-पास पड़ी किसी lockfile को कभी दोबारा न लिखे, और आपके install किए हुए `mcp` version का exact pin। यह `claude_desktop_config.json` में जाता है, जो यहाँ रहती है:

* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

यह file आप हाथ से भी लिख सकते हैं। `mcp install` इसलिए है ताकि ऐसा करते समय आप वह जानी-पहचानी गलती (relative path) न करें।

Claude Desktop को पूरी तरह quit करें (सिर्फ़ उसकी window नहीं) और दोबारा खोलें।

!!! warning
    अगर Claude Desktop की config **directory** अभी मौजूद नहीं है तो `mcp install` `Claude app not found` के साथ
    fail होता है। Claude Desktop install करें और एक बार चलाएँ: directory उसी से बनती है।

!!! tip
    Claude Desktop आपके server को अपने process में शुरू करता है, इसलिए आपके shell के environment variables
    वहाँ नहीं होते। `uv run mcp install server.py -v API_KEY=abc123` (या `-f .env`) उन्हें entry के
    `env` field में दर्ज कर देता है। `--name` entry का नाम override करता है; default server का `name` है।

## Claude Code {#claude-code}

edit करने के लिए कोई file नहीं है। server को `claude` CLI से register करें; `--` के बाद जो कुछ है वही launch command है।

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

यह पक्का करने के लिए कि `bookshop` connected है और उसके tools सूची में दिख रहे हैं, Claude Code session के अंदर `/mcp` चलाएँ।

## Cursor {#cursor}

अपने project root में `.cursor/mcp.json` बनाएँ।

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

वही `command` और `args`, उसी `mcpServers` key के नीचे जो Claude Desktop इस्तेमाल करता है। server दोनों tools के साथ Cursor की MCP settings में दिखता है।

## VS Code {#vs-code}

अपने project root में `.vscode/mcp.json` बनाएँ।

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

Cursor की file से दो फ़र्क़ हैं, और बस यही दो: wrapper key `mcpServers` नहीं, `servers` है, और हर entry अपना `type` बताती है। trust prompt को confirm करें, फिर Command Palette में **MCP: List Servers** `bookshop` को चलता हुआ दिखाता है।

!!! note
    आपको VS Code 1.99 या उससे नया चाहिए, जिसमें **GitHub Copilot** extension signed in हो (Copilot Free
    काफ़ी है), और Copilot Chat **Agent** mode में होना चाहिए, क्योंकि कोई और mode tools को call नहीं करता।

## यह दिख नहीं रहा {#it-doesnt-show-up}

किसी भी host config को छूने से पहले, launch command खुद चलाएँ:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

कुछ print नहीं होता, और यह लौटता नहीं। यह चुप्पी सही है: stdio server इंतज़ार कर रहा है कि host पहले stdin पर बोले (रोकने के लिए `Ctrl-C`)। traceback या तुरंत exit ही असली bug है, और अब आप उसे host के ज़रिए अंदाज़ा लगाने के बजाय सीधे पढ़ सकते हैं।

जब वह command बैठकर इंतज़ार करने लगे, तो बाकी समस्या लगभग हमेशा इन तीन में से एक होती है:

* **Relative path।** host आपके server को **अपनी** working directory से launch करता है, उस directory से नहीं जहाँ से आपने register किया था। जहाँ `/absolute/path/to/server.py` चाहिए वहाँ `server.py` लिखना सबसे आम गड़बड़ी है। अगर host को `uv` भी न मिले, तो वह path भी absolute होना चाहिए।
* **host अब भी पुराने config पर चल रहा है।** hosts अपना config launch के समय पढ़ते हैं। ख़ासकर Claude Desktop को **पूरी तरह quit** करना (सिर्फ़ window बंद करना नहीं) और दोबारा खोलना पड़ता है, तभी `claude_desktop_config.json` में किया गया बदलाव लागू होता है।
* **divert की गई window के बाहर कुछ stdout तक पहुँच गया।** stdio पर stdout **ही** protocol है। serve करते समय SDK flush हुए भटके हुए output को stderr की ओर मोड़ देता है, लेकिन उससे पहले stdout पर flush हुआ output (कोई wrapper script जो echo करती है, unbuffered process में import के समय चला `print()`), या interpreter exit पर खाली होने वाला buffered `print()`, host को corrupt message थमा देता है और host connection छोड़ देता है। default `logging` configuration से log करें, जिसका stderr handler हर record को flush करता है; custom handlers को भी stdout से बचना ही है। पूरी जानकारी **[Logging](../handlers/logging.md)** में है।

Claude Desktop हर server का अलग log रखता है: `mcp-server-<NAME>.log` आपके server का stderr है, connections के लिए `mcp.log` के बगल में, macOS पर `~/Library/Logs/Claude` में और Windows पर `%APPDATA%\Claude\logs` में।

इन तीनों के आगे कुछ भी हो, तो **[Troubleshooting](../troubleshooting.md)** वाला page देखें।

## सारांश {#recap}

* **host** (Claude Desktop, कोई IDE) एक MCP client चलाता है जो आपके server को stdio पर child process के रूप में launch करता है। connect करने का मतलब है उसे एक launch command देना।
* वह command है `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`: कोई venv activate नहीं करना, किसी भी directory से चलता है।
* **Claude Desktop** वह इकलौता host है जिसे `mcp install` आपके लिए configure करता है। यह वही command (साथ में `uv` का absolute path, `--frozen`, और आपके install किए हुए version का exact pin) `claude_desktop_config.json` में लिख देता है, ताकि आपको कभी न लिखना पड़े।
* **Claude Code** के लिए `claude mcp add bookshop -- <launch command>`। **Cursor** के लिए `mcpServers` के नीचे `.cursor/mcp.json`। **VS Code** के लिए `servers` के नीचे `.vscode/mcp.json`, हर entry में एक `type`।
* हर जगह absolute paths, config edit करने के बाद host को restart करें, और SDK के अलावा किसी को stdout पर न लिखने दें।

इस page का हर host उसी एक file से, उसी एक command से connect हुआ। वह file क्या **expose** कर सकती है, यही बाकी docs हैं: **[Tools](../servers/tools.md)**, **[Resources](../servers/resources.md)**, और stdio के अलावा हर transport **[अपना server चलाना](../run/index.md)** में।
