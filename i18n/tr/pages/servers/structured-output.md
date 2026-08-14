---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# Yapılandırılmış çıktı {#structured-output}

Düz bir `str` döndüren bir araç, sonucu iki kez üretir: `content` içinde metin olarak ve `structured_content` içinde `{"result": "..."}` olarak.

Bu sayfa o ikinci kanalla ilgili: nereden geldiği, alabileceği her biçim ve SDK'nın onu nasıl tutarlı tuttuğu.

Kısaca: **dönüş türü açıklaması (annotation) çıktı şemasıdır**. Onu zaten yazdınız.

## Çıktı şeması {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

Önemli olan satır imza: `-> int`.

Bu sayede SDK'nın `tools/list` sırasında gönderdiği araç, parametrelerinizden oluşturduğu girdi şemasının yanında (onu **[Araçlar](tools.md)** sayfası anlatır) bir de `output_schema` taşır:

```json
{
  "properties": {
    "result": {"title": "Result", "type": "integer"}
  },
  "required": ["result"],
  "title": "get_temperatureOutput",
  "type": "object"
}
```

Tek başına bir `int` JSON nesnesi değildir, bu yüzden SDK onu `{"result": ...}` içine **sarar**. Aracı çağırdığınızda iki kanal da dolar:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

Her skaler aynı sarmalayıcıyı alır: `str`, `int`, `float`, `bool`, `bytes`, `None`.

## İki kanal {#two-channels}

Neden aynı değer iki kez gönderiliyor?

* `content` **model** içindir. Bir dil modeli metin okur; sonucun gördüğü tek kısmı budur.
* `structured_content`, modelin içinde çalıştığı **uygulama** içindir: "17" geçen bir cümle değil, `17` isteyen kod.
* `output_schema` ikisi arasındaki sözleşmedir ve araç daha hiç çağrılmadan yayımlanır.

Siz tek bir Python değeri döndürürsünüz. Üçünü de SDK doldurur.

## Bir model döndürme {#return-a-model}

Biçimi bir Pydantic `BaseModel` olarak bildirin ve bir örneğini döndürün:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

Artık şema `WeatherData`'nın **kendisi**. Sarmalayıcı yok, `result` anahtarı yok:

```json
{
  "properties": {
    "temperature": {"description": "Degrees Celsius.", "title": "Temperature", "type": "number"},
    "humidity": {"description": "Relative humidity, 0 to 1.", "title": "Humidity", "type": "number"},
    "conditions": {"title": "Conditions", "type": "string"}
  },
  "required": ["temperature", "humidity", "conditions"],
  "title": "WeatherData",
  "type": "object"
}
```

`structured_content` alan alan o nesnedir:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

Model de dışarıda kalmaz. SDK aynı nesneyi `content` için JSON metnine serileştirir:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

`temperature` ve `humidity` üzerindeki `Field(description=...)` bilgisinin şemaya düştüğüne dikkat edin. **Girdilerinizi** tanımlayan aynı `Field`, çıktılarınızı da tanımlar.

!!! info
    FastAPI'nin `response_model`'ını kullandıysanız bunu zaten biliyorsunuz: bildirilen yanıt olarak
    bir Pydantic modeli, sizin yerinize serileştirilir ve belgelenir. Tek fark, burada bildirimin
    tamamının dönüş açıklaması olmasıdır.

## Bir `TypedDict` {#a-typeddict}

Her biçim bir sınıfı hak etmez. Bir `TypedDict` aynı şemayı üretir:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

`TypedDict` çalışma zamanında düz bir `dict`'tir; siz de onu oluşturup döndürürsünüz. Şema, doğrulama ve `structured_content`, `BaseModel` sürümüyle birebir aynıdır (`TypedDict`'te yeri olmayan açıklamalar hariç).

## Bir dataclass {#a-dataclass}

Dataclass'lar da çalışır; öznitelikleri tür ipucu taşıyan herhangi bir sıradan sınıf da öyle. SDK arka planda açıklamalardan bir Pydantic modeli oluşturur.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

Üç yazım, tek şema. Kod tabanınızda hangisi varsa onu kullanın.

## Listeler {#lists}

Bir `list[...]` de JSON nesnesi değildir, bu yüzden `{"result": ...}` sarmalayıcısını alır; öğe türünüz içinde bir `$defs` başvurusu olarak yer alır:

```python title="server.py" hl_lines="15"
--8<-- "docs_src/structured_output/tutorial005.py"
```

```json
{
  "$defs": {
    "WeatherData": {
      "properties": {
        "temperature": {"title": "Temperature", "type": "number"},
        "humidity": {"title": "Humidity", "type": "number"},
        "conditions": {"title": "Conditions", "type": "string"}
      },
      "required": ["temperature", "humidity", "conditions"],
      "title": "WeatherData",
      "type": "object"
    }
  },
  "properties": {
    "result": {"items": {"$ref": "#/$defs/WeatherData"}, "title": "Result", "type": "array"}
  },
  "required": ["result"],
  "title": "get_forecastOutput",
  "type": "object"
}
```

İki günlük bir tahmin istediğinizde `structured_content`, `{"result": [{...}, {...}]}` olur. `content` ise öğe başına bir tane olmak üzere **iki** `TextContent` bloğuna dönüşür: liste, model için tek bir dizge olarak dökülmek yerine düzleştirilir.

`tuple[...]`, union'lar ve `Optional[...]` aynı şekilde sarılır.

## Sözlükler {#dictionaries}

`dict[str, ...]` zaten bir JSON nesnesi *olan* tek generic türdür, bu yüzden sarılmaz:

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial006.py"
```

```json
{
  "additionalProperties": {"type": "number"},
  "title": "get_temperaturesDictOutput",
  "type": "object"
}
```

```python
result.structured_content  # {"London": 16.2, "Reykjavik": 4.4}
```

Anahtarlar `str` olmalıdır. Bir `dict[int, float]` JSON nesnesi olamaz, bu yüzden `{"result": ...}` sarmalayıcısına geri düşer.

## Doğrulama {#validation}

`output_schema` belgeleme değildir. Fonksiyonunuz ne döndürürse döndürsün, sunucudan çıkmadan önce **ona göre doğrulanır**.

Değeri elle oluşturduğunuz sürece bunu fark etmezsiniz: Pydantic, `WeatherData`'nızın bir `WeatherData` olduğundan zaten emin olmuştur. Bunu, verinin sizin denetlemediğiniz bir yerden geldiği gün fark edersiniz:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

Açıklama `WeatherData` vaat ediyor. Üst servisin yanıtı `humidity` göndermeyi bırakmış.

!!! check
    `get_weather`'ı çağırdığınızda istemciye sessizce yarı boş bir nesne vermez. Çağrı başarısız
    olur ve hatanın ilk satırları alanın adını verir:

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    Bu metin, `is_error=True` ile araç sonucu olarak geri döner; böylece model, var olmayan bir hava
    durumunu kendinden emin biçimde okumak yerine çağrının başarısız olduğunu bilir.

Bu arada, `-> WeatherData` bir araçtan düz bir `dict` döndürmek sorun değil. `json.loads`'un ürettiği tam olarak buydu. Doğrulama Python türüne değil, değere uygulanır.

## Devre dışı bırakma {#opting-out}

Bazen dönüş açıklaması protokol için değil, tür denetleyiciniz içindir. `structured_output=False` geçirin; araç yalnızca metin üretir:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

`output_schema` yok, sarmalama yok, doğrulama yok. `structured_content` `None`'dır ve `content` döndürdüğünüz dizgedir.

Tersi olan `structured_output=True`, otomatik algılamayı bir zorunluluğa çevirir: dönüş türü şema üretemeyen bir araç, metne geri düşmek yerine içe aktarma anında istisna fırlatır.

## Tür ipucu olmayan bir sınıf {#a-class-without-type-hints}

İstemeden yapılandırılmamış sonuca varmanın bir yolu vardır: **gövdesinde hiç açıklama olmayan** bir sınıf döndürmek.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station`, `name` ve `online` değerlerini `__init__` içinde atar, ama *sınıf* hiçbir şey bildirmez. SDK sınıf açıklamalarını okur, hiçbir şey bulamaz ve vazgeçer.

!!! warning
    **Sessizce** vazgeçer. `output_schema` `None`'dır, `structured_content` `None`'dır ve modelin
    okuduğu metin nesnenin `repr`'idir:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    Hata yok, uyarı yok, işe yaramaz bir araç. Açıklamaları sınıf gövdesine taşıyın ya da
    `structured_output=True` geçirin; bu, modül içe aktarıldığı anda durumu kesin bir hataya çevirir:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    Tam denetim mi gerekiyor (`CallToolResult`'ı kendiniz oluşturmak ya da uygulamanın görüp
    modelin göremediği bir `_meta` eklemek)? Bunun yeri **[Düşük seviyeli Server](../advanced/low-level-server.md)**.

## Özet {#recap}

* **Dönüş türü açıklaması** çıktı şemasıdır. `tools/list` içinde `output_schema` olarak yayımlanır.
* Skalerler, listeler, tuple'lar ve union'lar `{"result": ...}` içine sarılır. Modeller, `TypedDict`'ler, dataclass'lar, açıklamalı sınıflar ve `dict[str, ...]` zaten nesnedir ve oldukları gibi kalırlar.
* Her sonuç hem `content` (metin, model için) **hem de** `structured_content` (veri, uygulama için) taşır.
* Döndürdüğünüz şey şemaya göre doğrulanır. Uyuşmazlık bozuk bir sonuç değil, bir araç hatasıdır.
* `structured_output=False` bir aracı devre dışı bırakır. Tür ipucu olmayan bir sınıf sessizce devre dışı kalır; buna dikkat edin.

Artık bir aracın geri söyleyebileceği her şeye hâkimsiniz. Sırada ikinci ilkel yapı var: **[Kaynaklar](resources.md)**.
