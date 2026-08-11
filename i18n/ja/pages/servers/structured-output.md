---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# 構造化出力 {#structured-output}

単なる `str` を返すツールは、結果を 2 回生み出します。`content` にはテキストとして、`structured_content` には `{"result": "..."}` として入ります。

このページで扱うのは、その 2 つ目のチャネルです。それがどこから来るのか、どんな形を取りうるのか、そして SDK がその正しさをどう担保しているのかを見ていきます。

ひとことで言えば、**戻り値の型アノテーションが出力スキーマです**。もう書いてあります。

## 出力スキーマ {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

重要なのはシグネチャの行、`-> int` です。

この行があるおかげで、SDK が `tools/list` で送るツールには、パラメーターから組み立てる入力スキーマ（こちらは **[ツール](tools.md)** で扱っています）の隣に `output_schema` が付きます。

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

`int` 単体は JSON オブジェクトではないため、SDK はそれを `{"result": ...}` で**ラップ**します。ツールを呼び出すと、両方のチャネルが埋まります。

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

スカラーはどれも同じラッパーに包まれます。`str`、`int`、`float`、`bool`、`bytes`、`None` のすべてが対象です。

## 2 つのチャネル {#two-channels}

なぜ同じ値を 2 回送るのでしょうか。

* `content` は**モデル**のためのものです。言語モデルが読むのはテキストであり、結果のうちモデルの目に入るのはこの部分だけです。
* `structured_content` は、モデルがその中で動いている**アプリケーション**のためのものです。つまり「17」を含んだ文章ではなく、`17` そのものが欲しいコードです。
* `output_schema` は両者をつなぐ契約で、ツールが一度でも呼ばれる前に公開されます。

返すのは Python の値 1 つです。3 つすべてを埋めるのは SDK です。

## モデルを返す {#return-a-model}

形を Pydantic の `BaseModel` として宣言し、そのインスタンスを返します。

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

今度は `WeatherData` **そのものが**スキーマです。ラッパーも `result` キーもありません。

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

`structured_content` は、そのオブジェクトをフィールドごとにそのまま写したものです。

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

モデルも置き去りにはしません。SDK は同じオブジェクトを JSON テキストにシリアライズして `content` に入れます。

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

`temperature` と `humidity` に付けた `Field(description=...)` がスキーマに入っている点に注目してください。**入力**を説明したのと同じ `Field` が、出力も説明します。

!!! info
    FastAPI の `response_model` を使ったことがあれば、これはすでにおなじみのはずです。宣言したレスポンスとして Pydantic モデルを置けば、シリアライズもドキュメント化も任せられる、というものです。唯一の違いは、ここでは戻り値のアノテーションだけで宣言が完結する点です。

## `TypedDict` {#a-typeddict}

どんな形にもクラスがふさわしいわけではありません。`TypedDict` でも同じスキーマになります。

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

`TypedDict` は実行時にはただの `dict` なので、組み立てて返すのもそれです。スキーマもバリデーションも `structured_content` も、`BaseModel` 版と同一です（説明だけは付きません。`TypedDict` には説明を書く場所がないからです）。

## データクラス {#a-dataclass}

データクラスも使えますし、属性に型ヒントの付いた普通のクラスならどれでも使えます。SDK が裏側で、アノテーションから Pydantic モデルを組み立てます。

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

書き方は 3 通り、スキーマは 1 つです。コードベースにすでにあるものを使ってください。

## リスト {#lists}

`list[...]` も JSON オブジェクトではないので、`{"result": ...}` ラッパーに包まれます。要素の型は、その中で `$defs` への参照になります。

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

2 日分の予報を要求すると、`structured_content` は `{"result": [{...}, {...}]}` になります。`content` のほうは、要素ごとに 1 つずつ、**2 つ**の `TextContent` ブロックになります。リストは 1 本の文字列として丸ごと出力されるのではなく、モデル向けに平坦化されます。

`tuple[...]`、ユニオン、`Optional[...]` も同じようにラップされます。

## 辞書 {#dictionaries}

`dict[str, ...]` は、それ自体がすでに JSON オブジェクトである唯一のジェネリック型なので、ラップされません。

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

キーは `str` でなければなりません。`dict[int, float]` は JSON オブジェクトになれないため、`{"result": ...}` ラッパーにフォールバックします。

## バリデーション {#validation}

`output_schema` は単なるドキュメントではありません。関数が返すものは何であれ、サーバーを出る前に**このスキーマに照らして検証されます**。

値を手で組み立てているうちは、このことに気づきません。`WeatherData` が本当に `WeatherData` であることは、Pydantic がすでに保証しているからです。気づくのは、自分では制御できない場所からデータが来るようになった日です。

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

アノテーションは `WeatherData` を約束しています。ところが、上流のレスポンスが `humidity` を送ってこなくなりました。

!!! check
    `get_weather` を呼び出しても、中身が半分欠けたオブジェクトがこっそりクライアントに渡ることはありません。呼び出しは失敗し、エラーの冒頭の数行にそのフィールド名が示されます。

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    このテキストは `is_error=True` の付いたツール結果として返ってくるので、モデルは、ありもしない天気を自信満々に読み上げる代わりに、呼び出しが失敗したと分かります。

ちなみに、`-> WeatherData` のツールから単なる `dict` を返してもかまいません。`json.loads` が返したのはまさにそれです。バリデーションの対象は Python の型ではなく、値です。

## オプトアウト {#opting-out}

戻り値のアノテーションが、プロトコルのためではなく型チェッカーのためにある場合もあります。`structured_output=False` を渡せば、ツールはテキストのみになります。

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

`output_schema` も、ラップも、バリデーションもありません。`structured_content` は `None` になり、`content` は返した文字列そのものです。

その逆の `structured_output=True` は、自動検出を必須要件に変えます。戻り値の型からスキーマを作れないツールは、テキストにフォールバックするのではなく、インポート時に例外を送出します。

## 型ヒントのないクラス {#a-class-without-type-hints}

頼んでもいないのに非構造化になってしまう道が 1 つだけあります。**本体にアノテーションが 1 つもない**クラスを返すことです。

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` は `__init__` の中で `name` と `online` を設定していますが、クラス自体は何も宣言していません。SDK はクラスのアノテーションを読みにいき、何も見つからず、諦めます。

!!! warning
    しかも**黙って**諦めます。`output_schema` は `None`、`structured_content` も `None` で、モデルが読むテキストはオブジェクトの `repr` です。

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    エラーも警告もなく、役に立たないツールができあがります。アノテーションをクラス本体へ移すか、`structured_output=True` を渡してください。後者なら、モジュールをインポートした瞬間に `Function get_station: return type <class 'server.Station'> is not serializable for structured output` というハードエラーに変わります。

!!! tip
    完全な制御が必要な場合（`CallToolResult` を自分で組み立てたい、あるいはアプリケーションからは見えてモデルからは見えない `_meta` を付けたいなど）は、**[低レベル Server](../advanced/low-level-server.md)** を参照してください。

## まとめ {#recap}

* **戻り値の型アノテーション**が出力スキーマです。`tools/list` で `output_schema` として公開されます。
* スカラー、リスト、タプル、ユニオンは `{"result": ...}` でラップされます。モデル、`TypedDict`、データクラス、アノテーション付きクラス、`dict[str, ...]` はもともとオブジェクトなので、そのままです。
* どの結果も `content`（モデル向けのテキスト）**と** `structured_content`（アプリケーション向けのデータ）の両方を持ちます。
* 返したものはスキーマに照らして検証されます。食い違いは壊れた結果ではなく、ツールエラーになります。
* `structured_output=False` を渡すと、そのツールはオプトアウトします。型ヒントのないクラスは黙ってオプトアウトするので、気をつけてください。

これで、ツールが返せるものはすべて押さえました。次は 2 つ目のプリミティブ、**[リソース](resources.md)** です。
