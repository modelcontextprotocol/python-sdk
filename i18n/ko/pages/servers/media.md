---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# 미디어 {#media}

도구가 반환할 수 있는 것은 텍스트만이 아닙니다.

SDK는 바이너리 결과를 위한 두 가지 헬퍼(**`Image`**와 **`Audio`**)와, 클라이언트 UI에서 서버, 도구, 리소스, 프롬프트에 얼굴을 부여하는 **`Icon`** 타입을 제공합니다.

## 이미지 반환하기 {#returning-an-image}

반환 타입을 `Image`로 표기하고, 파일을 지정한 뒤 반환하세요.

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image`는 `path`(읽을 파일) 또는 `data`(원시 바이트) 중 정확히 하나만 받습니다.
* 클라이언트가 보는 MIME 타입은 확장자로 추측합니다. `logo.png`는 `image/png`로 알려집니다.
* 로고라서 특별한 것은 아닙니다. `server.py` 옆에 있는 PNG라면 무엇이든 됩니다. 코드가 렌더링한 차트, 다이어그램, 사진 모두 가능합니다.

`Image`는 SDK의 편의 기능이지 프로토콜 타입이 아닙니다. 전송 시 반환값은 **`ImageContent`** 블록(파일의 바이트를 base64로 인코딩한 값과 MIME 타입)이 됩니다.

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

눈여겨볼 점이 두 가지 있습니다.

* `data`는 base64입니다. 바이트를 직접 다룬 적이 없습니다. SDK가 파일을 읽고 인코딩까지 처리했습니다.
* `structured_content`는 `None`입니다. `Image`는 모델이 보기 위한 콘텐츠이지 애플리케이션이 파싱할 데이터가 아니므로 출력 스키마가 없습니다. (반환 타입 표기가 **곧** 스키마가 되는 **[구조화된 출력](structured-output.md)**과 대조해 보세요.)

!!! info
    `ImageContent`와 `AudioContent`는 `mcp.types`에 있으며, 평범한 `str` 결과가 변환되는 `TextContent`
    바로 옆에 있습니다(**[도구](tools.md)**). 도구 결과는 콘텐츠 블록의 리스트이고, `Image`와 `Audio`는
    두 가지 바이너리 종류를 만드는 가장 짧은 방법입니다.

### 직접 해 보기 {#try-it}

아무 PNG나 `server.py` 옆에 두고 이름을 `logo.png`로 바꾼 뒤 다음을 실행하세요.

```console
uv run mcp dev server.py
```

**Tools** 탭을 열고 `logo`를 호출하세요. 결과는 문자열이 아니라 `image` 콘텐츠 블록이며, Inspector가 그림을 렌더링합니다. 디스크의 파일에서 화면의 픽셀까지, 그 사이의 모든 일은 SDK가 했습니다.

## 오디오 반환하기 {#returning-audio}

`Audio`도 같은 형태입니다. `logo.png`는 그대로 두고, 아무 WAV나 그 옆에 `chime.wav`로 두세요.

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

결과는 **`AudioContent`** 블록입니다.

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

마찬가지입니다. 디스크의 파일이 들어가고, base64와 MIME 타입이 나오며, 출력 스키마는 없습니다.

## 바이트 또는 파일 {#bytes-or-a-file}

두 헬퍼 모두 `path=` 대신 `data=`(원시 바이트)도 받습니다. 애초에 자기 파일에서 온 적이 없는 바이트, 즉 데이터베이스 컬럼, HTTP 응답, Pillow가 방금 그린 결과물 같은 경우에 쓰는 방식입니다.

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

`path=`를 쓰면 선언할 것이 없습니다. 결과를 만들 때 파일을 읽고, MIME 타입은 확장자로 추측합니다.

* `Image`: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
* `Audio`: `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, `.m4a`.

인식하지 못하는 확장자는 `application/octet-stream`으로 대체됩니다.

!!! check
    `data=`를 쓰면 파일 이름이 없으므로 추측할 근거가 없습니다. `format=`을 빠뜨리면
    SDK는 기본값으로 대체합니다. 이미지는 `image/png`, 오디오는 `audio/wav`입니다. MP3 바이트로
    `Audio`를 그렇게 만들면 클라이언트는 `mime_type="audio/wav"`라고 전달받고, 그대로 믿고
    디코딩에 실패합니다. `data=`를 전달할 때는 `format=`도 전달하세요.

## 아이콘 {#icons}

`Icon`은 콘텐츠가 아니라 메타데이터입니다. 이미지를 담지 않고 URI로 이미지를 가리키며, 클라이언트는 이를 가져와 서버 이름, 도구, 리소스, 프롬프트 옆에 표시할 수 있습니다.

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src`는 클라이언트가 해석할 수 있는 URI입니다. `https:`이거나, 추가로 가져오지 않고 아이콘을 내장하고 싶다면 `data:` URI를 씁니다.
* `mime_type`과 `sizes`(`"48x48"`, 또는 크기 조절이 가능한 형식이면 `"any"`)는 여러 개를 제공할 때 클라이언트가 알맞은 것을 고르게 해 줍니다.
* `theme="light"` 또는 `theme="dark"`는 아이콘을 한 가지 색 구성표용으로 표시합니다.

같은 `icons=[...]` 키워드를 `MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`가 모두 받습니다.

### 클라이언트가 보는 위치 {#where-a-client-sees-them}

아이콘은 자신이 꾸미는 대상과 함께 전달됩니다. 서버의 아이콘은 클라이언트가 연결할 때 `client.server_info`로 도착합니다(2026년대 연결에서는 선택 사항이므로 먼저 타입을 좁히세요).

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

도구의 아이콘은 `tools/list`의 `Tool` 객체에, 리소스의 아이콘은 `resources/list`의 `Resource`에, 프롬프트의 아이콘은 `prompts/list`의 `Prompt`에 있습니다. 필드 이름은 언제나 `icons`입니다.

## 요약 {#recap}

* 도구에서 `Image`나 `Audio`를 반환하면 클라이언트는 `ImageContent` / `AudioContent` 블록을 받습니다. 바이트는 base64로 인코딩되고 MIME 타입이 함께 갑니다.
* `path=`로 만들어 확장자가 MIME 타입을 정하게 하거나, 메모리의 `data=`와 명시적인 `format=`으로 만드세요.
* 미디어 결과에는 `structured_content`도 출력 스키마도 없습니다.
* `Icon`은 포인터입니다. `src` URI에 선택적인 `mime_type`, `sizes`, `theme`이 더해집니다.
* `icons=[...]`는 서버, 도구, 리소스, 프롬프트에서 동작하며, 클라이언트는 대응하는 객체에서 아이콘을 찾습니다.

이것이 도구가 결과에 **넣을** 수 있는 전부입니다. 도구가 **실패**할 때 무슨 일이 일어나는지(그리고 누가 알아야 하는지)는 **[오류 처리](handling-errors.md)**에서 다룹니다.
