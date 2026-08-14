---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# URI şablonları ve yol güvenliği {#uri-templates-and-path-safety}

Bu sayfa, [`@mcp.resource`](resources.md) dekoratörünün kabul ettiği URI
şablonu sözdiziminin ve SDK'nın çıkarılan değerlere uyguladığı yol
güvenliği politikasının başvuru kaynağıdır. Kaynakların ne olduğuna ve
ne zaman kullanılacağına dair bir giriş için **[Kaynaklar](resources.md)**
sayfasıyla başlayın; bu sayfa, kaynak bildirmeye zaten alışkın olduğunuzu
ve operatör setinin tamamını, güvenlik ayarlarını ya da düşük seviyeli
bağlantıları aradığınızı varsayar.

Şablon sözdizimi [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570)
standardıdır. SDK, gelen `resources/read` URI'lerini eşleştirmek için
seçilmiş bir alt kümeyi destekler; buna ek olarak, sunmayı amaçladığınız
dizinin dışına çözümlenecek değerleri reddeden bir güvenlik katmanı vardır.
Protokol düzeyindeki ayrıntılar (mesaj biçimleri, yaşam döngüsü, sayfalama)
için [MCP kaynaklar belirtimine](https://modelcontextprotocol.io/specification/latest/server/resources)
bakın.

## Operatör setinin tamamı {#the-full-operator-set}

Düz yer tutucu `{user_id}`, **[Kaynaklar](resources.md)** sayfasının tanıttığı
biçimdir. Dört operatör biçimi daha var; yan yana görebilmeniz için hepsi tek
bir sunucuda:

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

Vurgulanan her dekoratör, URI'yi parçalamanın farklı bir yoludur.
Aşağıdaki bölümler bunları yukarıdan aşağıya ele alır.

### Basit genişletme: `{name}` {#simple-expansion-name}

`books://{isbn}` düz, gündelik biçimdir. Yer tutucu `isbn` parametresine
eşlenir; yani `books://978-0441172719` okuyan bir istemci
`get_book("978-0441172719")` çağrısına yol açar.

Düz bir `{name}` ilk `/` karakterinde durur. `books://978/extra` eşleşmez
çünkü `978`'den sonraki eğik çizgi yakalamayı bitirir ve `/extra` artar.

### Tür dönüşümü {#type-conversion}

Çıkarılan değerler dize olarak gelir, ancak daha belirli bir tür
bildirebilirsiniz; SDK dönüştürür. `orders://{order_id}`, parametresi
`order_id: int` olan bir fonksiyona düşer; dolayısıyla `orders://12345`
okumak `get_order("12345")` değil `get_order(12345)` çağrısını yapar.
İşleyici, tür dönüştürme yapmadan üzerinde aritmetik işlem yapar
(`order_id + 1`).

### Çok segmentli yollar: `{+name}` {#multi-segment-paths-name}

Eğik çizgi içeren bir değeri yakalamak için `{+name}` kullanın.
`manuals://{+path}` ile:

* `manuals://returns.md`, `path = "returns.md"` verir
* `manuals://printing/setup.md`, `path = "printing/setup.md"` verir

Değer hiyerarşik olduğunda `{+name}` biçimine başvurun: dosya sistemi
yolları, iç içe nesne anahtarları, vekillik ettiğiniz URL yolları.

### Sorgu parametreleri: `{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}`, `limit` ve `sort` parametrelerini `?`
işaretinin ardına koyar. Yol *hangi* kitap olduğunu belirler; sorgu onu
*nasıl* okuduğunuzu ayarlar.

Sorgu parametreleri esnek eşleştirilir: sıra önemli değildir, fazlalıklar
yok sayılır ve verilmeyen parametreler fonksiyonunuzun varsayılanlarına
düşer. Yani `reviews://978-0441172719`, `limit=10, sort="newest"` kullanır;
`reviews://978-0441172719?sort=top` ise yalnızca `sort` değerini geçersiz
kılar.

### Liste olarak yol segmentleri: `{/name*}` {#path-segments-as-a-list-name}

Her yol segmentini eğik çizgili tek bir dize yerine ayrı birer liste öğesi
olarak istiyorsanız `{/name*}` kullanın. `shelves://browse{/path*}` ile,
`shelves://browse/fiction/sci-fi` okuyan bir istemci
`browse_shelf(["fiction", "sci-fi"])` çağrısına yol açar.

### Şablon başvurusu {#template-reference}

En yaygın kalıplar:

| Kalıp        | Örnek girdi           | Elde ettiğiniz          |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | *eşleşme yok* (`/` karakterinde durur) |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### Ayrıştırıcının reddettikleri {#what-the-parser-rejects}

Birkaç şablon biçimi, ilk istekte başarısız olmak yerine en baştan
yakalanır. `@mcp.resource`, şablonu dekoratör çalıştığında ayrıştırır;
bu yüzden bunların hiçbiri çalışan bir sunucuya ulaşmaz.

`UriTemplate.parse()`, şu durumlarda `InvalidUriTemplate` fırlatır:

* **Aralarında hiçbir şey olmayan iki değişken.** `manuals://{+path}{ext}`
  reddedilir: eşleştirme, `path` değişkeninin nerede bitip `ext`
  değişkeninin nerede başladığını ayırt edemez. Aralarına bir sabit
  koyun (`manuals://{+path}/{ext}`) ya da kendi ayırıcısını sağlayan bir
  operatör kullanın. `manuals://{+path}{.ext}` kabul edilir, çünkü `{.ext}`
  `.` karakterini kendisi getirir.
* **Birden fazla çok segmentli değişken.** Şablon başına en fazla bir
  `{+var}`, `{#var}` ya da patlatılmış (exploded) değişken (`{/var*}`,
  `{.var*}`, `{;var*}`). İki tanesi doğası gereği belirsizdir: fazladan
  bir segmenti hangisinin yutacağına karar vermenin ilkeli bir yolu yoktur.
* **Olağan sözdizimi hataları**: kapatılmamış bir süslü parantez, iki kez
  kullanılan bir değişken adı ya da SDK'nın desteklemediği bir RFC 6570
  özelliği, örneğin `{var:3}` önek değiştiricisi veya `{?vars*}` sorgu
  patlatması.

Bunun üstüne, bir işleyici parametresi şablonun sondaki `{?...}`/`{&...}`
dizisindeki bir sorgu değişkenine bağlı olup Python varsayılanı yoksa
`@mcp.resource` `ValueError` fırlatır. Bu değişkenler esnek eşleştirilir
(istemci herhangi birini atlayabilir); bu yüzden varsayılanı olmayan bir
parametre, onu atlayan ilk istekte yalnızca anlaşılmaz bir iç hata olarak
ortaya çıkardı. Yukarıdaki sunucudaki `reviews://{isbn}{?limit,sort}` düzgün
biçimli sürümdür: `limit` ve `sort` varsayılan taşır.

## Güvenlik {#security}

Şablon parametreleri istemciden gelir. Denetlenmeden dosya sistemi veya
veritabanı işlemlerine akarlarsa, `../../etc/passwd` gibi değerler sunmayı
amaçladığınız dizinin dışına çözümlenebilir.

### SDK'nın varsayılan olarak denetledikleri {#what-the-sdk-checks-by-default}

İşleyiciniz çalışmadan önce SDK, şu özelliklere sahip her parametreyi
reddeder:

* `..` bileşenleriyle başlangıç dizininden kaçacak olanlar
* mutlak yol (`/etc/passwd`, `C:\Windows`) ya da Windows sürücüye göreli
  yol (`C:foo`) gibi görünenler. Sürücüye göreli bir değer ile `x:y` gibi
  ad alanlı bir tanımlayıcı dize olarak ayırt edilemez; bu yüzden tek
  harf artı iki nokta üst üste biçimindeki her değer varsayılan olarak
  reddedilir. Parametre meşru olarak böyle değerler alıyorsa onu muaf tutun
* null bayt (`\x00`) içerenler

`..` denetimi alt dize taraması değil, bileşen tabanlıdır. `v1.0..v2.0` ya
da `HEAD~3..HEAD` gibi değerler geçer, çünkü orada `..` tek başına bir yol
segmenti değildir.

Bu denetimler kodu çözülmüş değere uygulanır; dolayısıyla URI içinde nasıl
kodlanmış olursa olsun dizin geçişini yakalarlar (`../etc`, `..%2Fetc`,
`%2E%2E/etc`, `..%5Cetc`, `%00` hepsi yakalanır).

!!! check
    Yukarıdaki sunucudan `manuals://../etc/passwd` okuyun; istek doğrudan
    reddedilir: şablon eşleştirme ilk başarısızlıkta durur, bu yüzden
    sonraki (muhtemelen daha gevşek) hiçbir şablon yedek olarak denenmez.
    İstemci, hiçbir şablonla eşleşmeyen bir URI için göreceği `-32602`
    "Unknown resource" hatasının aynısını görür ve `read_manual` hiç
    çalışmaz.

### Dosya sistemi işleyicileri: safe_join kullanın {#filesystem-handlers-use-safe_join}

Yerleşik denetimler yaygın durumları durdurur ama sizin sandbox sınırınızı
bilemez. Dosya sistemi erişimi için yolu çözümlemek ve temel dizininizin
içinde kaldığını doğrulamak üzere `safe_join` kullanın:

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join`, basit bir dize denetiminin kaçıracağı sembolik bağlantı
kaçışlarını, `..` dizilerini ve mutlak yol hilelerini yakalar. Çözümlenen
yol `DOCS_ROOT` dışına çıkarsa `PathEscapeError` fırlatır; bu, istemciye
`ResourceError` olarak yansır.

### Varsayılanlar engel olduğunda {#when-the-defaults-get-in-the-way}

Bazen denetimler meşru değerleri engeller. Bir katalog içe aktarma aracı
bilerek mutlak bir yol alabilir ya da bir parametre, işleyicinizin dosya
sistemine dokunmadan güvenle yorumladığı `../sibling` gibi göreli bir
başvuru olabilir. O parametreyi muaf tutun ya da politikayı tüm sunucu için
gevşetin:

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* Dekoratördeki `security=ResourceSecurity(exempt_params={"source"})`,
  denetimleri yalnızca o kaynaktaki o tek parametre için atlar. Sunucunun
  geri kalanı varsayılan politikayı korur.
* `MCPServer` kurucusundaki `resource_security=`, her kaynak için
  varsayılanı belirler. Burada `relaxed`, `..` denetimini tamamen kapatır.

Yapılandırılabilir denetimler:

| Ayar                    | Varsayılan | Ne yapar                            |
|-------------------------|------------|-------------------------------------|
| `reject_path_traversal` | `True`     | Başlangıç dizininden kaçan `..` dizilerini reddeder |
| `reject_absolute_paths` | `True`     | `/foo`, `C:\foo`, UNC yollarını ve sürücüye göreli `C:foo` değerini reddeder (`x:y` de yakalanır) |
| `reject_null_bytes`     | `True`     | `\x00` içeren değerleri reddeder    |
| `exempt_params`         | boş        | Denetimlerin atlanacağı parametre adları |

Bu denetimler sezgisel bir ön süzgeçtir; dosya sistemi erişimi için
kapsama sınırı `safe_join` olmaya devam eder.

!!! tip
    İşleyiciniz isteği karşılayamıyorsa (dosya yok, kimlik bilinmiyor) bir
    istisna fırlatın. SDK bunu bir hata yanıtına dönüştürür. Protokol hatası
    ile araç hatası arasındaki fark için **[Hataları ele alma](handling-errors.md)**
    sayfasına bakın.

## Düşük seviyeli Server üzerinde kaynaklar {#resources-on-the-low-level-server}

Düşük seviyeli `Server` üzerine inşa ediyorsanız (bkz. **[Düşük seviyeli
Server](../advanced/low-level-server.md)**), `resources/list` ve
`resources/read` protokol metotları için işleyicileri doğrudan kaydedersiniz.
Dekoratör yoktur; protokol türlerini kendiniz döndürürsünüz.

### Statik kaynaklar {#static-resources}

Sabit URI'ler için bir kayıt defteri tutun ve tam eşleşmeye göre yönlendirin:

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

list işleyicisi istemcilere nelerin mevcut olduğunu bildirir; read işleyicisi
içeriği sunar. Önce kayıt defterinizi denetleyin, varsa şablonlara
(aşağıda) geçin, geri kalan her şey için istisna fırlatın.

### Şablonlar {#templates}

`MCPServer`'ın kullandığı şablon motoru `mcp.shared.uri_template` içinde
yaşar ve tek başına çalışır. Aynı ayrıştırma ve eşleştirmeyi alırsınız;
yönlendirmeyi ve güvenlik politikasını kendiniz kurarsınız.

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

Vurgulanan satırlarda üç şey oluyor:

* **Bir kez ayrıştırın, istek başına eşleştirin.** `UriTemplate.parse()`
  şablonu oluşturur; `template.match(uri)` çıkarılan değişkenleri `dict`
  olarak, URI uymuyorsa `None` döndürür. URL kod çözme `match()` içinde
  olur; kodu çözülmüş değerler yol güvenliği doğrulaması yapılmadan olduğu
  gibi döndürülür. Değerler dize olarak çıkar: kendiniz dönüştürün
  (`int(matched["id"])`, `Path(matched["path"])`).
* **Güvenlik denetimlerini kendiniz uygulayın.** `MCPServer`'ın varsayılan
  olarak çalıştırdığı `..` ve mutlak yol denetimleri
  `mcp.shared.path_security` içinde yaşar. `read_manual_safely`,
  `MANUALS`'a dokunmadan önce bunları çağırır. Bir parametre dosya sistemi
  yolu değilse (ISBN, arama sorgusu), o değer için denetimleri atlayın:
  politikayı bir yapılandırma nesnesi üzerinden değil, işleyici başına siz
  denetlersiniz.
* **Şablonları aynı kaynaktan listeleyin.** İstemciler şablonları
  `resources/templates/list` üzerinden keşfeder. `str(template)` özgün
  şablon dizesini geri verir; böylece listeleme ile eşleştirici tek bir
  doğruluk kaynağını paylaşır.

## Özet {#recap}

* `{name}` tek bir segmentle eşleşir; `{+name}` eğik çizgileri korur;
  `{?a,b}` sorgu dizesinden çeker; `{/name*}` segmentleri bir listeye böler.
* Aralarında hiçbir şey olmayan iki değişken ya da ikinci bir çok segmentli
  değişken ayrıştırma anında reddedilir. Sondaki bir `{?...}`/`{&...}`
  sorgu değişkenine bağlı parametre bir Python varsayılanı bildirmelidir.
* Parametreye tür ipucu verin (`order_id: int`); SDK dönüştürür.
* Varsayılan güvenlik politikası `..`, mutlak yolları ve null baytları
  işleyiciniz çalışmadan önce reddeder; kaynak başına
  `security=ResourceSecurity(...)` ile, sunucu genelinde
  `resource_security=` ile geçersiz kılın.
* Dosya sistemi erişimi için kapsama sınırı `safe_join`'dur.
* Düşük seviyeli `Server` üzerinde `UriTemplate.parse()` ile ayrıştırın,
  `.match()` ile eşleştirin ve `mcp.shared.path_security`'yi kendiniz
  uygulayın.
