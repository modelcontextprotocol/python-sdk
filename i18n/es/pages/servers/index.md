---
translation:
  sections: [09defc170a0da89d]
  tool: 1
---
# Servidores {#servers}

Un `MCPServer` expone tres primitivas a un cliente conectado. Se diferencian en quién
decide usarlas:

* Una **[herramienta](tools.md)** es una acción que el *modelo* elige y llama. Esta es
  la página que la mayoría quiere leer primero, y
  **[Salida estructurada](structured-output.md)** es su referencia complementaria:
  todo sobre la forma de lo que devuelve una herramienta.
* Un **[recurso](resources.md)** son datos de solo lectura que la *aplicación*
  decide leer. **[Plantillas de URI](uri-templates.md)** es su referencia
  complementaria: la sintaxis de direccionamiento completa y las reglas de seguridad de rutas.
* Un **[prompt](prompts.md)** es una plantilla de mensaje que una *persona* invoca por
  nombre, desde un menú o un comando de barra.

En torno a las tres primitivas, el resto de lo que declara un servidor:

* **[Autocompletado](completions.md)** es el autocompletado del lado del servidor para los
  argumentos de prompts y de plantillas de recursos.
* **[Imágenes, audio e iconos](media.md)** cubre todo lo que una herramienta puede
  devolver además de texto, y los iconos que un cliente muestra junto al servidor.
* **[Manejo de errores](handling-errors.md)** explica la diferencia entre un
  error del que el modelo puede recuperarse y uno que nunca debe ver.

Cada página de esta sección se sostiene por sí sola; ve directamente a la que necesites. Si aún no
has creado un servidor, empieza por **[Primeros pasos](../get-started/first-steps.md)**.

Lo que ocurre *dentro* de las funciones que registras (el `Context`, la inyección de dependencias,
pedirle al usuario más información a mitad de la llamada) es la siguiente sección,
**[Dentro de tu handler](../handlers/index.md)**.
