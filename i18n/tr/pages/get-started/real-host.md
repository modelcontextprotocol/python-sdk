---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# Gerçek bir host'a bağlanma {#connect-to-a-real-host}

**Host**, sunucunuzun sonunda içine girdiği uygulamadır: Claude Desktop, Claude Code, bir IDE. Kullanıcının konuştuğu şey host'tur. Onun içinde bir MCP **istemcisi** sunucunuzu bir alt süreç olarak başlatır ve onunla o sürecin stdin'i ve stdout'u üzerinden konuşur.

Yani bir host'a bağlanmak tek bir eylemdir: ona **sunucunuzu başlatan komutu** söylersiniz. Bu sayfadaki her şey (iki CLI komutu, üç JSON dosyası) aynı komutu koyacağınız farklı bir yerdir.

## Tek sunucu, her host {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

İki araç ve bir kaynak, tek dosya. Bu dosyayla ilgili üç şey aşağıdaki her host için önemlidir:

* Argümansız `mcp.run()` bir **stdio** sunucusu başlatır: bloklar, protokol mesajlarını stdin'den okur ve stdout'a yazar. Bu sayfadaki her host'un konuştuğu aktarım budur. Host dosyanızı bir alt süreç olarak başlatır ve bu iki kanalın sahibidir; bağlanmanın her zaman yalnızca "işte komut" olmasının nedeni de budur. Hiçbir zaman port seçmezsiniz ve hiçbir şey bir portu dinlemez.
* `run()`, `if __name__ == "__main__":` altındadır. Aşağıdaki her şey bu dosyayı çalıştırmak yerine **import eder**; bu yüzden korumasız bir `run()`, modülü herhangi bir şey yüklediği anda bir sunucu başlatırdı.
* Sunucu nesnesi, `mcp` adında modül düzeyinde bir globaldir. `mcp run`'ın aradığı ad budur (`server` ve `app` de olur). Başka bir ad verirseniz açıkça belirtirsiniz: `mcp run server.py:bookshop`.

Bu, bu sayfadaki son Python satırı. Buradan aşağısı tamamen host yapılandırması.

## Başlatma komutu {#the-launch-command}

Aşağıdaki her host aynı komutu alır:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Hepsi için tek komut, çünkü `uv run --with` SDK'yı anında yeni bir ortama çözümler: herhangi bir dizinden çalışır, ne bir projeye ne de etkinleştirilecek bir sanal ortama ihtiyaç duyar. Bu, burada başka her yerden daha önemlidir; çünkü host sunucunuzu sizin kabuğunuzdan değil, *kendi* çalışma dizininden ve neredeyse boş bir ortamla başlatır.

Bu aynı zamanda `mcp install`'un sizin için Claude Desktop'ın yapılandırmasına yazdığı komuttur (aşağıda). Böylece elle yazdığınız ile aracın ürettiği, aracın eklediği tam sürüm sabitlemesi dışında örtüşür.

!!! tip "Host `uv`'yi bulamazsa"
    Host sunucunuzu asgari bir `PATH` ile başlatır ve `uv` bunun üzerinde olmayabilir. Yalın
    `uv`'yi `which uv` (macOS/Linux) veya `where uv` (Windows) çıktısındaki mutlak yolla değiştirin.
    `mcp install`'un yazdığı da tam olarak budur.

!!! note "Bu sayfa yerel senaryoyu anlatır"
    Buradaki her şey sunucunuzu host'un bulunduğu makinede çalıştırır: host dosyanızı stdio
    üzerinden başlatır. Kişisel ya da tek makinelik bir araç için bu tam olarak doğru olandır.
    Dosyanıza sahip *olmayan* insanlara bir sunucu vermek için komut değil **URL** dağıtırsınız:
    aynı `mcp` nesnesi, Streamable HTTP üzerinden sunulur. **[Sunucunuzu çalıştırma](../run/index.md)**
    bu kararı tek bir tabloda verir, **[Dağıtım ve ölçekleme](../run/deploy.md)** ise oradan
    gerçek bir ana bilgisayar adına giden yoldur.

    Ve host, içinde bir MCP istemcisi olan bir uygulamadan başka bir şey değildir; bu yüzden kendi
    Python kodunuz host rolünü oynayabilir: **[İstemci aktarımları](../client/transports.md)**
    bu aynı dosyayı `stdio_client(...)` ile bir alt süreç olarak başlatır, **[Test etme](testing.md)**
    ise ona hiç süreç olmadan bellek içinde bağlanır.

## Claude Desktop {#claude-desktop}

SDK'nın sizin için yapılandırabildiği tek host:

```bash
uv run mcp install server.py
```

Hepsi bu. `mcp install` sunucunun adını okumak için dosyayı import eder, Claude Desktop'ın yapılandırma dosyasını bulur ve başlatma komutunu içine yazar. Bu arada yolunuzu mutlak bir yola çevirir, sizin yapmanıza gerek kalmaz.

Kafa karıştıracak bir şey yok. Yazdığı kayıt şu:

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

Bu, yukarıdaki bölümdeki başlatma komutunun üç eklemeli hâli: `uv`'nin mutlak yolu, `uv` yakınında bulunduğu bir kilit dosyasını asla yeniden yazmasın diye `--frozen` ve kurulu `mcp` sürümüne tam bir sabitleme. Şurada bulunan `claude_desktop_config.json` dosyasına yazılır:

* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Bu dosyayı elle yazabilirsiniz. `mcp install`, bunu yaparken klasik hatayı (göreli yol) yapmayın diye vardır.

Claude Desktop'tan tamamen çıkın (yalnızca penceresini kapatmayın) ve yeniden açın.

!!! warning
    Claude Desktop'ın yapılandırma *dizini* henüz yoksa `mcp install`, `Claude app not found`
    hatasıyla başarısız olur. Claude Desktop'ı kurun ve bir kez çalıştırın: dizini oluşturan budur.

!!! tip
    Claude Desktop sunucunuzu kendi sürecinde başlatır; bu yüzden kabuğunuzun ortam değişkenleri
    orada yoktur. `uv run mcp install server.py -v API_KEY=abc123` (veya `-f .env`) bunları kaydın
    `env` alanına işler. `--name` kayıt adını geçersiz kılar; varsayılan olarak sunucunun `name`
    değeridir.

## Claude Code {#claude-code}

Düzenlenecek dosya yok. Sunucuyu `claude` CLI ile kaydedin; `--` sonrasındaki her şey başlatma komutudur.

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

`bookshop`'un bağlı olduğunu ve araçlarının listelendiğini doğrulamak için bir Claude Code oturumunda `/mcp` çalıştırın.

## Cursor {#cursor}

Proje kök dizininizde `.cursor/mcp.json` dosyasını oluşturun.

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

Aynı `command` artı `args`, Claude Desktop'ın kullandığı aynı `mcpServers` anahtarı altında. Sunucu, Cursor'ın MCP ayarlarında iki araç da listelenmiş olarak görünür.

## VS Code {#vs-code}

Proje kök dizininizde `.vscode/mcp.json` dosyasını oluşturun.

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

Cursor'ın dosyasından iki fark var ve yalnızca bu ikisi: sarmalayıcı anahtar `mcpServers` değil `servers`'tır ve her kayıt `type`'ını bildirir. Güven iletişim kutusunu onaylayın; ardından Command Palette'teki **MCP: List Servers**, `bookshop`'u çalışır durumda gösterir.

!!! note
    **GitHub Copilot** eklentisiyle oturum açılmış VS Code 1.99 veya üzeri gerekir (Copilot Free
    yeterli) ve Copilot Chat **Agent** modunda olmalıdır; çünkü başka hiçbir mod araç çağırmaz.

## Görünmüyor {#it-doesnt-show-up}

Herhangi bir host yapılandırmasına dokunmadan önce başlatma komutunu kendiniz çalıştırın:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Hiçbir şey yazdırmaz ve geri dönmez. Bu sessizlik doğrudur: stdio sunucusu, bir host'un stdin'de ilk konuşan taraf olmasını bekler (durdurmak için `Ctrl-C`). Asıl hata bir traceback ya da anında çıkıştır; artık onu bir host üzerinden tahmin etmeye çalışmak yerine okuyabilirsiniz.

Bu komut oturup beklediğinde, geriye kalan neredeyse her zaman üç şeyden biridir:

* **Göreli yol.** Host sunucunuzu kaydı yaptığınız dizinden değil, *kendi* çalışma dizininden başlatır. `/absolute/path/to/server.py` gereken yerde `server.py` yazmak, açık ara en yaygın hatadır. Host `uv`'yi de bulamıyorsa o yol da mutlak olmalıdır.
* **Host hâlâ eski yapılandırmasını çalıştırıyor.** Host'lar yapılandırmalarını başlarken okur. Özellikle Claude Desktop'tan, `claude_desktop_config.json` üzerindeki bir düzenleme etkili olmadan önce *tamamen çıkılması* (yalnızca penceresinin kapatılması değil) ve yeniden açılması gerekir.
* **Yönlendirilen pencerenin dışında stdout'a bir şey ulaştı.** stdio'da stdout protokolün *ta kendisidir*. SDK, hizmet verirken flush edilmiş başıboş çıktıyı stderr'e yönlendirir; ancak o andan önce stdout'a flush edilen çıktı (bir sarmalayıcı betiğin echo'su, tamponsuz bir süreçte import anında bir `print()`) ya da yorumlayıcı çıkışında boşaltılan tamponlanmış bir `print()`, host'a bozuk bir mesaj verir ve host bağlantıyı keser. stderr işleyicisi her kaydı flush eden varsayılan `logging` yapılandırmasıyla log tutun; özel işleyiciler de stdout'tan uzak durmalıdır. Ayrıntıların tamamı **[Logging](../handlers/logging.md)** sayfasında.

Claude Desktop her sunucu için bir log tutar: `mcp-server-<NAME>.log` sunucunuzun stderr'idir, bağlantılar için `mcp.log`'un yanında; macOS'te `~/Library/Logs/Claude`, Windows'ta `%APPDATA%\Claude\logs` altında.

Bu üçünün ötesindeki her şey için doğru sayfa **[Sorun giderme](../troubleshooting.md)**.

## Özet {#recap}

* **Host** (Claude Desktop, bir IDE), sunucunuzu stdio üzerinden bir alt süreç olarak başlatan bir MCP istemcisi çalıştırır. Bağlanmak, ona tek bir başlatma komutu vermek demektir.
* O komut `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`: etkinleştirilecek venv yok, her dizinden çalışır.
* **Claude Desktop**, `mcp install`'un sizin için yapılandırdığı tek host'tur. Aynı komutu (artı `uv`'nin mutlak yolu, `--frozen` ve kurulu sürüme tam bir sabitleme) `claude_desktop_config.json` dosyasına yazar; böylece sizin yapmanıza hiç gerek kalmaz.
* **Claude Code** için `claude mcp add bookshop -- <launch command>`. **Cursor** için `mcpServers` altında `.cursor/mcp.json`. **VS Code** için `servers` altında `.vscode/mcp.json`, her kayıtta bir `type` ile.
* Her yerde mutlak yollar, yapılandırmasını düzenledikten sonra host'u yeniden başlatın ve SDK dışında hiçbir şeyin stdout'a yazmasına izin vermeyin.

Bu sayfadaki her host aynı dosyaya, aynı komutla bağlandı. O dosyanın neler *sunabileceği* ise bu belgelerin geri kalanı: **[Araçlar](../servers/tools.md)**, **[Kaynaklar](../servers/resources.md)** ve stdio dışındaki tüm aktarımlar için **[Sunucunuzu çalıştırma](../run/index.md)**.
