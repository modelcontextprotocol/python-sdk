---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# Autorización {#authorization}

Sobre Streamable HTTP, tu servidor MCP es un servicio web común y corriente, y lo proteges igual que proteges cualquier servicio web: con tokens bearer de OAuth 2.1.

En términos de OAuth, el servidor es un **servidor de recursos**. Nunca inicia la sesión de nadie y nunca emite un token. Hace una sola cosa: mirar el header `Authorization` de cada solicitud y decidir si el token que trae es válido.

Esta página es el lado del servidor. Un cliente que descubre tu servidor de autorización y obtiene el token está en **[Clientes OAuth](../client/oauth-clients.md)**.

## Las tres partes {#the-three-parties}

* El **servidor de autorización** inicia la sesión de las personas y emite tokens de acceso. Esto no lo escribes tú. Es tu proveedor de identidad (Auth0, Keycloak, Entra, el tuyo propio).
* El **servidor de recursos** es tu servidor MCP. Verifica el token en cada solicitud.
* El **cliente** descubre en qué servidor de autorización confías, obtiene de él un token y te lo envía de vuelta como `Authorization: Bearer <token>`.

Ese es todo el triángulo. Todo lo que hay en esta página es el punto del medio.

## Un verificador de tokens {#a-token-verifier}

El SDK no opina sobre cómo debe ser un token válido. Se lo dices tú, implementando **`TokenVerifier`**:

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` es un protocolo con un solo método asíncrono. `verify_token` recibe el token en bruto del header `Authorization` y devuelve un **`AccessToken`** si es válido, `None` si no lo es. No hay nada más que implementar.
* Este busca el token en una tabla. Uno real verifica la firma de un JWT o llama al endpoint de introspección de tokens del servidor de autorización. Ese código es tuyo; el SDK solo lo llama.
* `token_verifier=` y `auth=` siempre van juntos. Pasa uno sin el otro y `MCPServer(...)` lanza un `ValueError` antes de atender ninguna solicitud.

`AuthSettings` es la cara pública de tu servidor de recursos:

* `issuer_url`: el servidor de autorización que emite tus tokens.
* `resource_server_url`: la URL pública de este endpoint MCP. Indica *para qué* recurso es un token y es donde vive el documento de descubrimiento.
* `required_scopes`: todo token debe traerlos todos.

!!! tip
    `examples/servers/simple-auth/` en el repositorio del SDK tiene un `IntrospectionTokenVerifier` que llama
    al endpoint [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) de un servidor de autorización real. Es la forma que toman la mayoría de los verificadores en producción.

## Lo que obtienes sobre HTTP {#what-you-get-over-http}

La autorización vive en los headers HTTP, así que solo existe en los transportes HTTP. Ejecútala en el que despliegues: `mcp.run(transport="streamable-http")` la pone en `http://127.0.0.1:8000/mcp`, y **[Ejecutar el servidor](index.md)** tiene el resto. La app ahora tiene dos rutas:

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

Registraste una herramienta. La segunda ruta es del SDK.

### Descubrimiento {#discovery}

Haz un `GET` a esa ruta well-known y obtienes los **Protected Resource Metadata de [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728)**, construidos directamente a partir de tu `AuthSettings`:

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

Este documento es la forma en que un cliente que nunca ha oído hablar de tu servidor encuentra la entrada: lee `authorization_servers` y va ahí a buscar un token. No escribiste nada de él.

!!! check
    Llama a `/mcp` sin token (o con uno para el que tu verificador devolvió `None`) y la solicitud
    se detiene en la puerta:

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    No se analizó nada ni se ejecutó ninguna herramienta. Y ese puntero `resource_metadata` en `WWW-Authenticate` es
    lo que hace automático el descubrimiento: 401 -> documento de metadatos -> servidor de autorización -> token -> reintento.

!!! warning
    Nada de esto protege a `stdio`. Una tubería no tiene header `Authorization`, así que ahí nunca se
    consulta `token_verifier`. La frontera de seguridad de un servidor `stdio` es el proceso que lo lanzó. Lo mismo
    vale para el `Client(mcp)` en memoria que usas en las pruebas: se conecta directamente al objeto servidor
    y se salta la capa HTTP, autorización incluida.

## La identidad de quien llama {#the-callers-identity}

Dentro de cualquier handler, **`get_access_token()`** es el `AccessToken` que tu verificador devolvió para la solicitud actual:

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* Funciona en herramientas, recursos y prompts, y no hay nada que pasar de un lado a otro: el middleware de autenticación lo guarda en una variable de contexto por solicitud.
* Recibes el **mismo objeto que construyó tu verificador**: `client_id`, `scopes`, `subject`, `expires_at` y cualquier `claims` extra que hayas añadido. Ese es el punto de enganche para reglas por herramienta: lee los scopes y rechaza.
* Fuera de una solicitud HTTP autenticada devuelve `None`. En memoria y sobre `stdio` siempre es `None`.

Llama a `whoami` con `Authorization: Bearer alice-token` y el modelo lee:

```text
alice (scopes: notes:read)
```

## La mitad que el SDK no hace {#the-half-the-sdk-doesnt-do}

El SDK te da la mitad del servidor de recursos: verificar, anunciar, rechazar. No te da una página de inicio de sesión, una pantalla de consentimiento ni un token.

Para ver a las tres partes en movimiento, ejecuta `examples/servers/simple-auth/` del repositorio del SDK (un pequeño servidor de autorización y un servidor de recursos configurado exactamente como en esta página) y luego apunta `examples/clients/simple-auth-client/` hacia él para ver el recorrido completo de descubrimiento y token.

!!! info
    Hay un segundo argumento del constructor, `auth_server_provider=`, que incrusta un servidor de autorización
    completo dentro de tu servidor MCP. Es anterior a la separación AS/RS sobre la que se construye la especificación
    de autorización de MCP. Los servidores nuevos no deberían recurrir a él.

Un servidor de autorización también puede aceptar la aserción firmada de un proveedor de identidad empresarial en lugar de que un usuario haga clic en una pantalla de consentimiento, y el SDK admite los dos lados de ese intercambio. El grant, y el cliente que lo presenta, están en **[Aserción de identidad](../client/identity-assertion.md)**.

## Resumen {#recap}

* Sobre Streamable HTTP tu servidor es un **servidor de recursos** de OAuth 2.1: verifica tokens, nunca los emite.
* `TokenVerifier` es toda la superficie de integración: un método asíncrono, entra un token, sale `AccessToken | None`.
* `token_verifier=` y `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` siempre van juntos.
* El SDK publica los Protected Resource Metadata de [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) en `/.well-known/oauth-protected-resource/...` y responde a las solicitudes no autenticadas con un 401 cuyo header `WWW-Authenticate` apunta a ellos. Ese es todo el mecanismo de descubrimiento.
* `get_access_token()` en cualquier handler te dice quién llama.
* La autorización es un asunto de HTTP. `stdio` y el cliente en memoria nunca la ven.

La mitad del cliente (descubrir tu servidor de autorización y obtener el token por ti) está en **[Clientes OAuth](../client/oauth-clients.md)**. Y un cliente que *afirma* una identidad en lugar de pedírsela a un usuario está en **[Aserción de identidad](../client/identity-assertion.md)**.
