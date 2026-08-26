---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

**MCP App**은 얼굴을 가진 도구입니다. 도구가 데이터와 함께 HTML 문서를 가리키면, 호스트는 이 문서를 상호작용 가능한 화면으로 렌더링합니다.

두 부분으로 이루어지며, 언제나 두 부분입니다.

1. 다른 도구와 마찬가지로 작업을 수행하고 데이터를 반환하는 **도구**.
2. 호스트가 도구를 위해 보여 줄 HTML을 담은 **`ui://` 리소스**.

도구는 리소스를 가리키는 `_meta.ui.resourceUri` 참조를 지닙니다. 호스트는 `resources/read`로 리소스를 가져와 **샌드박스 처리된 iframe**에 렌더링하고, 도구의 결과를 `postMessage`로 그 iframe에 전달합니다. 서버는 어떤 `ui/*` 메시지도 주고받지 않습니다. 그 트래픽은 호스트와 iframe 사이의 일입니다. 서버는 도구와 HTML 문서를 제공할 뿐이고, 나머지 연출은 호스트가 맡습니다.

SDK는 이를 내장 `Apps` 확장(`io.modelcontextprotocol/ui`)으로 제공합니다. [확장](extensions.md)이 처음이라면 먼저 그 페이지를 훑어보세요. 1분이면 충분하니 읽고 돌아오면 됩니다.

## 얼굴을 가진 시계 {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

네 가지 단계입니다.

* `Apps()`: 인스턴스 하나가 UI에 연결된 도구와 그 리소스를 모두 담습니다.
* `@apps.tool(resource_uri="ui://clock/app.html")`: 일반 도구에 `_meta.ui.resourceUri` 표시가 더해집니다. `@mcp.tool()`이 받는 모든 것(name, title, description, ...)이 그대로 전달됩니다.
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`: 짝이 되는 리소스이며 `text/html;profile=mcp-app`으로 제공됩니다. 바로 이 MIME 타입이 호스트에게 "이것은 앱이니 렌더링하라"고 알려 줍니다.
* `MCPServer("clock", extensions=[apps])`: 옵트인입니다. 이제 서버는 `capabilities.extensions` 아래에 `io.modelcontextprotocol/ui`를 알립니다.

HTML 자체는 호스트의 `postMessage`를 수신하고 결과를 표시합니다. 실제 앱에서는 HTML 안에서 공식 [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps) 브라우저 SDK를 사용하세요. 원시 메시지 이벤트 대신 `ontoolresult`, `callServerTool`, `getHostContext`, `onhostcontextchanged`를 제공합니다.

## 우아한 성능 저하 {#graceful-degradation}

모든 클라이언트가 앱을 렌더링하지는 않습니다. 이것이 서버에 어떤 의미인지 사양은 분명하게 말합니다.

> 도구는 UI를 사용할 수 있는 경우에도 의미 있는 `content` 배열을 반환해야 **합니다(MUST)**.

모델은 `content`를 읽고, iframe은 사람을 위한 것입니다. UI를 지원하는 호스트도 여전히 텍스트 결과를 모델에 전달하며, 텍스트 전용 클라이언트는 **오직** 그 텍스트만 받습니다. 따라서 표준 패턴은 도구 하나에 답 둘입니다. `get_time`을 다시 살펴보세요.

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

`client_supports_apps(ctx)`는 클라이언트가 `io.modelcontextprotocol/ui` 확장을 선언했고 **동시에** `mimeTypes` 설정에 `text/html;profile=mcp-app`을 나열했을 때만 `True`입니다. 이 필드는 필수이므로 생략한 클라이언트는 해당하지 않습니다. 같은 파일의 `main()`이 선언하는 것이 바로 이것입니다. 협상의 클라이언트 쪽 절반을 선언하면 풍부한 답이 돌아옵니다.

!!! warning
    `"[Rendered UI]"` 같은 자리 표시자를 유일한 content로 반환하지 마세요. 대체 텍스트가 쓸모없다면, 그 도구는 모든 텍스트 전용 클라이언트와 모델 자체에 쓸모없는 도구가 됩니다. 제대로 된 문장을 작성하세요.

## iframe 잠그기 {#locking-the-iframe-down}

리소스 쪽이 보안 메타데이터를 지닙니다. iframe이 무엇을 로드할 수 있는지, 어떤 브라우저 권한을 원하는지, 어떻게 프레임에 담기기를 원하는지를 담습니다.

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp`와 `permissions`는 서버의 동작이 아니라 **호스트에 대한 요청**입니다. 호스트는 이를 바탕으로 iframe의 Content-Security-Policy와 Permissions-Policy를 구성하며, 거부할 수도 있습니다. 허가되었다고 가정하지 말고 JS에서 기능 탐지를 하세요.

`ResourceCsp`를 필드별로 살펴보면 다음과 같습니다(Python 이름, 와이어 키, 호스트가 이것으로 하는 일).

| Python | 와이어 (`_meta.ui.csp`) | 제어 대상 |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`: `fetch`/XHR이 갈 수 있는 곳 |
| `resource_domains` | `resourceDomains` | `img-src`, `style-src`, ...: 정적 자산 |
| `frame_domains` | `frameDomains` | `frame-src`: 중첩 iframe |
| `base_uri_domains` | `baseUriDomains` | `base-uri`: `<base>`가 가리킬 수 있는 곳 |

`ResourcePermissions`: 각 필드는 iframe을 위한 브라우저 권한 하나를 요청합니다.

| Python | 와이어 (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP와 권한은 **리소스**에 있으며, 도구에는 절대 두지 않습니다. 사양의 도구 메타데이터에는 이를 위한 자리가 없고, 호스트는 그곳에 있는 값을 무시합니다. SDK는 이 실수를 아예 표현할 수 없게 만듭니다. `@apps.tool()`에는 `csp` 매개변수가 없습니다.

### 가시성 {#visibility}

도구의 `visibility=["app"]`은 "이것은 모델이 아니라 iframe을 위해 존재한다"는 뜻입니다.

* `"model"`: 모델이 호출할 수 있습니다.
* `"app"`: iframe이 호출할 수 있습니다(`callServerTool`을 통해).
* 생략: 둘 다이며, 이것이 기본값입니다.

필터링은 **호스트**의 일입니다. 서버는 앱 전용 도구를 다른 도구와 마찬가지로 `tools/list`에 나열하고, 호스트가 이를 모델에게서 숨깁니다. 서버 쪽에서 필터링하지 마세요.

## SDK가 강제하는 규칙 {#the-rules-the-sdk-enforces}

모두 프로덕션이 아니라 시작 시점에 실패합니다.

* `ui://...`가 아닌 `resource_uri`나 리소스 URI는 데코레이션/등록 시점에 `ValueError`입니다.
* **짝이 되는 등록된 리소스가 없는** URI에 연결된 도구는 `MCPServer(extensions=[apps])`가 확장을 소비할 때 `ValueError`입니다. `resources/read`에서 404가 나는 HTML을 알리는 도구는 잘못된 설정이므로, 생성 자체를 거부합니다.
* `@apps.tool()`의 `meta={"ui": ...}`는 `ValueError`입니다. `_meta["ui"]`는 데코레이터의 소유이니 `resource_uri=`와 `visibility=`로 표현하세요. 다른 `meta=` 키는 문제없이 함께 병합됩니다.

TypeScript ext-apps SDK도 FastMCP도 현재는 이 중 어느 것도 잡아내지 못합니다. 호스트가 발견하기 전에 먼저 알게 되는 편이 낫다고 생각합니다.

## 인라인 HTML 너머 {#beyond-inline-html}

`add_html_resource`는 흔한 경우, 즉 HTML 문자열을 다룹니다. 그 밖의 경우, 디스크에 있는 HTML이나 생성된 콘텐츠라면 리소스를 직접 만들어 넘기세요.

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

`add_resource`는 리소스가 MIME 타입을 명시적으로 설정하지 않았을 때 `text/html;profile=mcp-app`을 채워 넣고, 명시적으로 불일치하는 값은 거부합니다. 다른 MIME 타입의 `ui://` 리소스는 어떤 호스트도 렌더링하지 않기 때문입니다.

!!! tip
    지원 중단 예정(deprecated)인 평면 키 `_meta["ui/resourceUri"]`를 여전히 읽는 GA 이전 호스트를 대상으로 하나요? 직접 병합하세요.
    `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`.
    중첩된 `ui` 객체가 사양의 형태이며, 평면 키는 사라지는 중입니다.

## 실행해 보기 {#see-it-run}

`examples/stories/`의 `apps` 스토리는 이 페이지를 실행 가능한 한 쌍으로 만든 것입니다. UI에 연결된 시계 도구를 갖춘 서버, 그리고 Apps를 협상하고 도구의 `_meta.ui.resourceUri`를 읽고 HTML을 가져와 도구를 호출하는 클라이언트입니다.

```bash
uv run python -m stories.apps.client
```
