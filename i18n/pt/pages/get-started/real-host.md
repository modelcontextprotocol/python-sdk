---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# Conecte-se a um host de verdade {#connect-to-a-real-host}

Um **host** é a aplicação dentro da qual seu servidor acaba rodando: Claude Desktop, Claude Code, uma IDE. O host é aquilo com que o usuário conversa. Dentro dele, um **cliente** MCP inicia seu servidor como um processo filho e fala com ele pelo stdin e stdout desse processo.

Ou seja, conectar a um host é um ato só: você informa a ele **o comando que inicia seu servidor**. Tudo nesta página (dois comandos de CLI, três arquivos JSON) é um lugar diferente para colocar esse mesmo comando.

## Um servidor, todos os hosts {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

Duas ferramentas (tools) e um recurso, um arquivo só. Três coisas sobre esse arquivo importam para todos os hosts abaixo:

* `mcp.run()` sem argumentos inicia um servidor **stdio**: ele bloqueia, lê mensagens do protocolo no stdin e as escreve no stdout. Esse é o transporte que todos os hosts desta página falam. O host inicia seu arquivo como um processo filho e é dono desses dois pipes, e é por isso que conectar nunca passa de "aqui está o comando". Você nunca escolhe uma porta, e nada fica escutando em uma.
* `run()` fica dentro de `if __name__ == "__main__":`. Tudo abaixo **importa** este arquivo em vez de executá-lo, então um `run()` sem essa proteção iniciaria um servidor no instante em que qualquer coisa carregasse o módulo.
* O objeto do servidor é uma global de nível de módulo chamada `mcp`. É esse o nome que `mcp run` procura (`server` e `app` também funcionam). Dê outro nome a ele e você precisa informá-lo explicitamente: `mcp run server.py:bookshop`.

Essa é a última linha de Python nesta página. Daqui para baixo é tudo configuração de host.

## O comando de inicialização {#the-launch-command}

Todos os hosts abaixo recebem o mesmo comando:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Um comando só para todos eles porque `uv run --with` resolve o SDK em um ambiente novo na hora: funciona a partir de qualquer diretório e não precisa de projeto nem de ambiente virtual para ativar. Isso importa aqui mais do que em qualquer outro lugar, porque um host inicia seu servidor a partir do diretório de trabalho *dele*, com um ambiente quase vazio, e não a partir do seu shell.

É também o comando que `mcp install` grava na configuração do Claude Desktop para você (abaixo), então o que você digita à mão e o que o utilitário gera coincidem, fora o pin exato de versão que o utilitário adiciona.

!!! tip "Se um host não encontrar o `uv`"
    Um host inicia seu servidor com um `PATH` mínimo, e o `uv` pode não estar nele. Troque o
    `uv` sozinho pelo caminho absoluto que `which uv` (macOS/Linux) ou `where uv` (Windows)
    retorna. É exatamente isso que `mcp install` grava.

!!! note "Esta página é o cenário local"
    Tudo aqui executa seu servidor na máquina em que o host está: o host inicia seu
    arquivo, via stdio. Isso é exatamente o certo para uma ferramenta pessoal ou de uma máquina
    só. Para entregar um servidor a pessoas que *não* têm seu arquivo, você distribui uma
    **URL**, não um comando: o mesmo objeto `mcp` servido via Streamable HTTP.
    **[Executando seu servidor](../run/index.md)** é essa decisão em uma tabela só, e
    **[Deploy e escala](../run/deploy.md)** é o caminho dali até um hostname de verdade.

    E um host nada mais é que uma aplicação com um cliente MCP dentro, então seu próprio
    código Python pode fazer o papel do host: **[Transportes do cliente](../client/transports.md)**
    inicia este mesmo arquivo como subprocesso com `stdio_client(...)`, e **[Testes](testing.md)**
    se conecta a ele em memória, sem processo nenhum.

## Claude Desktop {#claude-desktop}

O único host que o SDK consegue configurar para você:

```bash
uv run mcp install server.py
```

É só isso. `mcp install` importa o arquivo para ler o nome do servidor, encontra o arquivo de configuração do Claude Desktop e grava o comando de inicialização nele. De passagem, já converte o caminho para absoluto, então você não precisa fazer isso.

Não há mistério nenhum. Esta é a entrada que ele grava:

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

É o comando de inicialização da seção acima com três acréscimos: o caminho absoluto do `uv`, `--frozen` para que o `uv` nunca reescreva um lockfile que por acaso esteja por perto, e um pin exato na versão do `mcp` que você tem instalada. Ele vai parar em `claude_desktop_config.json`, que fica em:

* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Você pode escrever esse arquivo à mão. `mcp install` existe para você não cometer o erro clássico (um caminho relativo) ao fazer isso.

Encerre o Claude Desktop por completo (não só a janela) e abra-o de novo.

!!! warning
    `mcp install` falha com `Claude app not found` se o *diretório* de configuração do Claude
    Desktop ainda não existir. Instale o Claude Desktop e execute-o uma vez: é isso que cria o
    diretório.

!!! tip
    O Claude Desktop inicia seu servidor em um processo próprio, então as variáveis de ambiente do
    seu shell não estão lá. `uv run mcp install server.py -v API_KEY=abc123` (ou `-f .env`) as
    registra no campo `env` da entrada. `--name` sobrescreve o nome da entrada; o padrão é o
    `name` do servidor.

## Claude Code {#claude-code}

Não há arquivo para editar. Registre o servidor com a CLI `claude`; tudo depois de `--` é o comando de inicialização.

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Execute `/mcp` dentro de uma sessão do Claude Code para confirmar que `bookshop` está conectado e que suas ferramentas aparecem listadas.

## Cursor {#cursor}

Crie `.cursor/mcp.json` na raiz do seu projeto.

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

Os mesmos `command` e `args`, sob a mesma chave `mcpServers` que o Claude Desktop usa. O servidor aparece nas configurações de MCP do Cursor com as duas ferramentas listadas.

## VS Code {#vs-code}

Crie `.vscode/mcp.json` na raiz do seu projeto.

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

Duas diferenças em relação ao arquivo do Cursor, e são as únicas duas: a chave externa é `servers`, não `mcpServers`, e cada entrada declara seu `type`. Confirme o diálogo de confiança e, em seguida, **MCP: List Servers** na paleta de comandos mostra `bookshop` rodando.

!!! note
    Você precisa do VS Code 1.99 ou posterior, com login feito na extensão **GitHub Copilot**
    (o Copilot Free basta), e o Copilot Chat precisa estar no modo **Agent**, porque nenhum
    outro modo chama ferramentas.

## Não aparece {#it-doesnt-show-up}

Antes de mexer em qualquer configuração de host, execute você mesmo o comando de inicialização:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Nada é impresso, e ele não retorna. Esse silêncio está certo: um servidor stdio está esperando um host falar primeiro no stdin (`Ctrl-C` para pará-lo). Um traceback ou uma saída imediata é o bug de verdade, e agora você consegue lê-lo em vez de tentar adivinhá-lo através de um host.

Uma vez que esse comando fica parado esperando, o que sobra é quase sempre uma de três coisas:

* **Um caminho relativo.** O host inicia seu servidor a partir do diretório de trabalho *dele*, não daquele de onde você fez o registro. `server.py` onde é preciso `/absolute/path/to/server.py` é, de longe, a falha mais comum. Se o host também não encontrar o `uv`, esse caminho precisa ser absoluto também.
* **O host ainda está rodando a configuração antiga.** Os hosts leem a configuração ao iniciar. O Claude Desktop, em particular, precisa ser *encerrado por completo* (não basta fechar a janela) e reaberto para que uma edição em `claude_desktop_config.json` tenha efeito.
* **Algo chegou ao stdout fora do intervalo de desvio.** No stdio, o stdout *é* o protocolo. O SDK desvia para o stderr a saída avulsa descarregada (com flush) enquanto está servindo, mas uma saída descarregada no stdout antes disso (um script wrapper que ecoa algo, um `print()` em tempo de importação em um processo sem buffer), ou um `print()` em buffer que só é descarregado quando o interpretador encerra, entrega ao host uma mensagem corrompida, e ele derruba a conexão. Registre os logs usando a configuração padrão do `logging`, cujo handler de stderr faz flush de cada registro; handlers personalizados também precisam evitar o stdout. **[Logging](../handlers/logging.md)** tem a história completa.

O Claude Desktop mantém um log por servidor: `mcp-server-<NAME>.log` é o stderr do seu servidor, ao lado de `mcp.log` para as conexões, em `~/Library/Logs/Claude` no macOS e `%APPDATA%\Claude\logs` no Windows.

Para qualquer coisa além dessas três, a página é **[Solução de problemas](../troubleshooting.md)**.

## Recapitulando {#recap}

* Um **host** (Claude Desktop, uma IDE) executa um cliente MCP que inicia seu servidor como processo filho via stdio. Conectar significa dar a ele um comando de inicialização.
* Esse comando é `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`: nenhum venv para ativar, funciona a partir de qualquer diretório.
* **Claude Desktop** é o único host que `mcp install` configura para você. Ele grava esse mesmo comando (mais o caminho absoluto do `uv`, `--frozen` e um pin exato na versão que você tem instalada) em `claude_desktop_config.json`, para você nunca precisar fazer isso.
* **Claude Code** é `claude mcp add bookshop -- <launch command>`. **Cursor** é `.cursor/mcp.json` sob `mcpServers`. **VS Code** é `.vscode/mcp.json` sob `servers`, cada entrada com um `type`.
* Caminhos absolutos em todo lugar, reinicie o host depois de editar a configuração dele, e nunca deixe nada além do SDK escrever no stdout.

Todos os hosts desta página se conectaram ao mesmo arquivo, com o mesmo comando. O que esse arquivo pode *expor* é o resto desta documentação: **[Ferramentas](../servers/tools.md)**, **[Recursos](../servers/resources.md)** e todos os transportes além do stdio em **[Executando seu servidor](../run/index.md)**.
