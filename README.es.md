<p align="center">
  <img src="src/aiusageclock/assets/aiusageclockicon.png" alt="Ícono de AI Usage Clock" width="160" />
</p>

<h1 align="center">AI Usage Clock</h1>

<p align="center"><strong>Mira cada límite de IA. Entérate de cada reinicio.</strong></p>

<p align="center">
  Si usas varios servicios de IA, saber cuánto te queda en cada uno, o si los límites se acaban de reiniciar,<br />
  te obliga a revisarlos uno por uno. AI Usage Clock reúne esos límites de uso en un pequeño widget de escritorio.<br />
  También recoge los anuncios de reinicio de Codex y Claude: te enteras con tiempo cuando un reinicio se anuncia por adelantado,<br />
  y tienes dónde revisar cuando tu uso cae a cero de repente.
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <strong>Español</strong> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a>
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml"><img src="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml/badge.svg" alt="Estado de las pruebas" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078d4" alt="Windows, macOS y Linux" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="Licencia MIT" />
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/releases/latest"><img src="https://img.shields.io/badge/Download-latest%20release-2ea44f?style=for-the-badge" alt="Descargar la versión más reciente" /></a>
  <a href="https://aiusageclock.com/es/"><img src="https://img.shields.io/badge/Website-aiusageclock.com-c2410c?style=for-the-badge" alt="Visitar el sitio web" /></a>
</p>

<p align="center">
  <img src="docs/screenshots/windows-1.0.0.png" alt="AI Usage Clock en Windows con el uso de Claude y Codex, las cuotas de Antigravity y los anuncios de reinicio de Codex y Claude" width="520" />
</p>

<p align="center"><sub>El widget en Windows, capturado de una versión publicada en ejecución. Los valores de uso corresponden al momento de la captura.</sub></p>

<p align="center">
  <img src="docs/screenshots/win-panel-compact.png" alt="Modo compacto: una cápsula por servicio" width="440" />
</p>

<p align="center"><sub>El modo compacto reduce el widget a una cápsula por servicio (datos de ejemplo).</sub></p>

## Qué hace por ti

- **Tus límites de IA en un solo lugar.** Claude, Codex, Antigravity, OpenCode Go, GitHub Copilot y OpenRouter, uno al lado del otro, cada uno con su propia barra de uso. En los límites que están en curso también verás, junto a la barra, cuánto tiempo queda.
- **Si hay aviso, te enteras antes; si no, sabes dónde revisar.** Activa los anuncios de reinicio y AI Usage Clock recogerá los anuncios de Codex y Claude. Algunos reinicios se anuncian por adelantado (los anuncios de Codex, más una fila **Watch** con un pronóstico hecho por IA), así que puedes prepararte. Otros llegan sin aviso: la tarjeta deja a la vista el último anuncio, así que cuando tu uso cae a cero de repente puedes comprobar si acaba de haber un reinicio, y abrir la publicación original con un clic.
- **Notificaciones cuando hay un anuncio nuevo.** Si quieres, puedes recibir una notificación cada vez que aparece un anuncio nuevo (en Windows, con las notificaciones nativas del sistema) y activarlas por separado para cada tipo. Los anuncios vienen de sitios independientes, de terceros, y pueden llegar tarde o estar equivocados, así que confirma siempre en la publicación original. Esta función viene desactivada de forma predeterminada.
- **Se ejecuta en tu computadora.** No hay cuenta de AI Usage Clock, ni servidor, ni telemetría. Las claves de API se guardan en el almacenamiento seguro de tu sistema operativo. Las sesiones iniciadas en Claude y ChatGPT también se guardan ahí y, además, en la carpeta de perfil del navegador propio de la app.

## Empieza en 3 pasos

1. **Descarga** el archivo comprimido para tu sistema desde la [versión más reciente](https://github.com/AIUsageClock/ai-usage-clock/releases/latest): `ai-usage-clock-<version>-windows.zip`, `ai-usage-clock-<version>-macos.tar.gz` o `ai-usage-clock-<version>-linux.tar.gz`.
2. **Descomprímelo y ábrelo.**
   - Windows: ejecuta `ai-usage-clock.exe`
   - macOS: arrastra `ai-usage-clock.app` a Aplicaciones y ábrelo
   - Linux: ejecuta `./ai-usage-clock/ai-usage-clock`
3. **Conecta tus servicios.** En Claude y Codex, inicia sesión desde la propia app; en los servicios que usan clave de API, pégala en **Settings** (la configuración de la app). Los detalles están en la [guía de configuración](docs/setup.md) (en inglés).

Las versiones publicadas no tienen firma de código, así que Windows o macOS pueden mostrar una advertencia la primera vez que abras la app. [Mira qué hacer](#aviso-de-smartscreen-o-gatekeeper-al-abrir-la-app-por-primera-vez).

## Servicios compatibles

| Servicio | Qué muestra | Cómo se conecta |
| --- | --- | --- |
| **Claude** | Límites Session (de sesión) y Weekly (semanal), más el límite semanal de Fable en los planes que lo tienen | Inicia sesión desde tu navegador (puedes entrar con Google o con una llave de acceso) o pega una cookie de sesión |
| **Codex** (ChatGPT) | Límites Session y Weekly | Igual que Claude |
| **Antigravity** | Uso de Gemini y de Claude+GPT, cada uno con su límite de 5 horas y su límite semanal | Lee la herramienta de línea de comandos `agy` instalada en tu computadora; no necesitas cuenta ni clave en la app |
| **OpenCode Go** | Uso Rolling, Weekly y Monthly (ventana móvil, semanal y mensual) | Clave de API de OpenCode |
| **GitHub Copilot** | Créditos de IA usados en el mes frente a lo que incluye tu plan; el conteo se reinicia el día 1 de cada mes | *Fine-grained personal access token* de GitHub (token de acceso personal) |
| **OpenRouter** | Gasto de hoy y del mes, con un presupuesto diario opcional; saldo y actividad por modelo si usas una clave de administración | Clave de API de OpenRouter |

Claude, Codex y GitHub Copilot vienen activados de forma predeterminada. Los demás servicios, y los anuncios de reinicio, se activan en **Settings**. Puedes monitorear más de una cuenta de Claude, Codex u OpenCode Go.

## Para agentes de IA (MCP)

AI Usage Clock incluye un servidor MCP local opcional, desactivado de forma predeterminada. Con él, los agentes de programación pueden revisar tu uso antes de empezar una tarea costosa y hacer una pausa al llegar a un límite que tú definas. Solo lee una caché local de uso, ya depurada de datos sensibles, y nunca tus credenciales. La configuración está en [docs/mcp.md](docs/mcp.md) (en inglés).

## Preguntas frecuentes

### ¿Cómo funcionan los anuncios de reinicio?

Vienen desactivados. Para usarlos, ve a **Settings → General** y activa **Codex Resets** o **Claude Resets** (los interruptores de los anuncios de Codex y de Claude). A partir de ahí, AI Usage Clock consulta dos sitios independientes, de terceros:

- codex-resets.com, que usa IA para clasificar las publicaciones de @thsottiaux.
- claude-resets.com, que reúne las publicaciones de @ClaudeDevs y de miembros del equipo de Claude Code.

Mientras la app está abierta, consulta cada sitio como máximo una vez cada 15 minutos; si vuelves a abrir la app, consulta de nuevo.

La tarjeta muestra el evento más reciente y hace cuánto ocurrió, con una etiqueta según el tipo:

- **Announced** (anunciado): se anunció un reinicio por adelantado. Solo Codex tiene este tipo.
- **Reset** (reiniciado): los límites se recargaron.
- **Banked** (cupón de reinicio): recibiste un cupón de reinicio que puedes canjear por tu cuenta.

La tarjeta de Codex tiene además una fila **Watch** (pronóstico): una estimación hecha por IA de qué tan probable es un reinicio. No es un anuncio oficial y nunca envía notificaciones. Haz clic en ↗ para abrir la publicación original, o en ✕ para ocultar la tarjeta hasta que llegue la siguiente entrada.

En **Settings → Reset alerts** (alertas de reinicio) eliges de qué tipos quieres recibir notificaciones (Codex: Announced, Reset y Banked; Claude: Reset y Banked). El primer evento que la app obtiene de cada sitio solo se registra, sin notificar. En Windows se usan las notificaciones nativas, que abren la publicación original al hacer clic; en otros sistemas se usa un globo de notificación en la bandeja del sistema, si hay bandeja. En el modo de barra de menús de macOS, o en Linux sin bandeja, no hay notificaciones, aunque las tarjetas se siguen actualizando.

Los datos los recopilan terceros y pueden llegar tarde o estar equivocados (las entradas nuevas de Claude pueden quedar como provisionales hasta 24 horas), así que toma la publicación original como la fuente confiable.

### ¿Es una app oficial?

No. AI Usage Clock es un proyecto independiente de código abierto y una utilidad de escritorio local no oficial: ninguno de los servicios que muestra la creó ni la respalda. Las páginas y las API de los proveedores pueden cambiar sin previo aviso.

### ¿A dónde van mis datos?

Tu configuración, tu historial de uso y tus sesiones iniciadas se quedan en tu computadora. Las sesiones y las claves de API se guardan con los mecanismos de credenciales de tu sistema operativo: el Administrador de credenciales y DPAPI en Windows, el llavero en macOS y Secret Service en Linux. Las sesiones de Claude y ChatGPT también se guardan en la carpeta de perfil del navegador propio de la app.

No hay telemetría ni servidor de AI Usage Clock. La app se conecta directamente a los servicios que actives: las páginas de uso de Claude y ChatGPT (que se cargan en un navegador integrado) y las API de GitHub, OpenCode y OpenRouter. El uso de Antigravity sale de la herramienta `agy` de tu computadora, que la app ejecuta por ti; `agy` se encarga de sus propias conexiones.

Si activas los anuncios de reinicio, la app también se conecta a codex-resets.com y claude-resets.com; esos sitios ven tu dirección IP y el nombre y la versión de la app. El seguimiento de costos local, que es opcional, lee los registros de Claude Code y Codex en tu computadora y no sube nada. Más detalles en [SECURITY.md](SECURITY.md) (en inglés).

### Aviso de SmartScreen o Gatekeeper al abrir la app por primera vez

Las versiones publicadas no tienen firma de código, y junto a cada archivo comprimido se publican sus sumas SHA256.

- **Windows:** si aparece el aviso de SmartScreen, haz clic en **Más información** y luego en **Ejecutar de todas formas**.
- **macOS:** Gatekeeper bloquea la app la primera vez. Intenta abrirla una vez y luego ve a **Configuración del Sistema → Privacidad y seguridad**, busca la app en la sección **Seguridad**, haz clic en **Abrir** y después en **Abrir de todos modos**; ingresa tu contraseña de inicio de sesión y haz clic en **OK** (el botón **Abrir de todos modos** queda disponible durante aproximadamente una hora después del intento). También puedes ejecutar una vez `xattr -dr com.apple.quarantine ai-usage-clock.app`.
- **Linux:** no hay ninguna capa de firma. Si `ai-usage-clock` todavía no tiene permiso de ejecución, dáselo.

Hay más detalles, incluido el programa auxiliar de MCP en macOS, en [docs/build.md](docs/build.md#first-launch-warnings-on-unsigned-builds) (en inglés).

### ¿Necesito Python?

Para las descargas, no: Python y el motor del navegador ya vienen incluidos. Python 3.11 o posterior solo hace falta para ejecutar desde el código fuente o para contribuir; consulta [docs/build.md](docs/build.md) (en inglés).

### ¿Funciona en macOS y Linux?

Sí, con una salvedad. Windows es la plataforma donde se desarrolla y donde se prueba con cuentas reales. Las versiones para macOS (un elemento de la barra de menús en lugar de un widget flotante) y Linux están publicadas, y las pruebas automatizadas corren en los tres sistemas, pero actualizar los datos de cuentas reales solo se ha verificado en Windows 11, así que considera macOS y Linux como versiones beta. Las notificaciones de reinicio varían según el sistema; mira la primera pregunta. Si algo no funciona bien, [abre un issue](https://github.com/AIUsageClock/ai-usage-clock/issues).

### ¿Es gratis?

Sí. Es gratuito y de código abierto, con licencia MIT. Los servicios que muestra requieren sus propias cuentas o suscripciones.

## Más recursos

[Guía de configuración](docs/setup.md) (en inglés) · [Uso diario](docs/usage.md) (en inglés) · [Control de uso con MCP](docs/mcp.md) (en inglés) · [Compilar desde el código fuente](docs/build.md) (en inglés) · [Cómo contribuir](CONTRIBUTING.md) (en inglés) · [Seguridad](SECURITY.md) (en inglés) · [Licencia (MIT)](LICENSE)

Versión actual: **1.0.0** · [Registro de cambios](CHANGELOG.md) (en inglés)

AI Usage Clock no está afiliado a Anthropic, OpenAI, Google, GitHub, Microsoft, OpenCode, OpenRouter ni a ningún otro proveedor. Los nombres de productos pertenecen a sus respectivos propietarios.
