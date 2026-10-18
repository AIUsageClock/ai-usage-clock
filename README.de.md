<p align="center">
  <img src="src/aiusageclock/assets/aiusageclockicon.png" alt="App-Symbol von AI Usage Clock" width="160" />
</p>

<h1 align="center">AI Usage Clock</h1>

<p align="center"><strong>Alle KI-Limits im Blick. Alle Resets auf dem Schirm.</strong></p>

<p align="center">
  Wer mehrere KI-Dienste parallel nutzt, klappert ständig deren Seiten ab, um zu sehen, wie viel noch übrig ist und ob gerade zurückgesetzt wurde.<br />
  AI Usage Clock bündelt diese Nutzungslimits in einem kleinen Desktop-Widget.<br />
  Außerdem greift es Reset-Ankündigungen von Codex und Claude auf: Wird ein Reset vorab angekündigt, weißt du früher Bescheid,<br />
  und steht dein Verbrauch plötzlich auf null, kannst du nachsehen, ob gerade einer stattgefunden hat.
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <strong>Deutsch</strong>
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml"><img src="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml/badge.svg" alt="Teststatus" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078d4" alt="Windows, macOS und Linux" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT-Lizenz" />
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/releases/latest"><img src="https://img.shields.io/badge/Download-latest%20release-2ea44f?style=for-the-badge" alt="Neuestes Release herunterladen" /></a>
  <a href="https://aiusageclock.com/de/"><img src="https://img.shields.io/badge/Website-aiusageclock.com-c2410c?style=for-the-badge" alt="Website besuchen" /></a>
</p>

<p align="center">
  <img src="docs/screenshots/windows-1.0.0.png" alt="AI Usage Clock unter Windows mit der Nutzung von Claude und Codex, den Kontingenten von Antigravity sowie den Reset-Ankündigungen von Codex und Claude" width="520" />
</p>

<p align="center"><sub>Das Widget unter Windows, aufgenommen von einem laufenden Release. Die Verbrauchswerte entsprechen dem Zeitpunkt der Aufnahme.</sub></p>

<p align="center">
  <img src="docs/screenshots/win-panel-compact.png" alt="Kompaktmodus: eine Kapsel pro Dienst" width="440" />
</p>

<p align="center"><sub>Im Kompaktmodus schrumpft das Widget auf eine Kapsel pro Dienst (Beispieldaten).</sub></p>

## Was das Tool kann

- **Deine KI-Limits an einem Ort.** Claude, Codex, Antigravity, OpenCode Go, GitHub Copilot und OpenRouter nebeneinander, jeder Dienst mit eigenem Verbrauchsbalken. Bei laufenden Limits steht neben dem Balken außerdem die verbleibende Zeit.
- **Angekündigte Resets vorher sehen, überraschende hinterher nachprüfen.** Schalte die Reset-Ankündigungen ein, dann greift AI Usage Clock die Ankündigungen von Codex und Claude auf. Manche Resets werden vorab angekündigt (die Ankündigungen von Codex, dazu eine KI-Prognose in der Zeile **Watch**), sodass du dich darauf einstellen kannst. Andere kommen aus heiterem Himmel: Die Kachel zeigt immer die neueste Ankündigung. Steht dein Verbrauch plötzlich auf null, siehst du dort, ob gerade ein Reset stattgefunden hat, und kommst mit einem Klick zum Originalbeitrag.
- **Benachrichtigung bei neuen Ankündigungen.** Auf Wunsch bekommst du eine Benachrichtigung, sobald eine neue Ankündigung auftaucht (unter Windows über die systemeigenen Benachrichtigungen); für jeden Typ gibt es einen eigenen Schalter. Die Ankündigungen stammen von unabhängigen Trackern Dritter und können verspätet oder falsch sein; maßgeblich ist deshalb der Originalbeitrag. Die Funktion ist standardmäßig deaktiviert.
- **Läuft auf deinem Rechner.** Es gibt weder ein Konto noch einen Server von AI Usage Clock, und auch keine Telemetrie. API-Schlüssel liegen im sicheren Speicher deines Betriebssystems. Dort liegen auch die Anmeldesitzungen für Claude und ChatGPT, außerdem im eigenen Browserprofil-Ordner der App.

## In drei Schritten loslegen

1. **Herunterladen:** Hol dir aus dem [neuesten Release](https://github.com/AIUsageClock/ai-usage-clock/releases/latest) das Archiv für dein System: `ai-usage-clock-<version>-windows.zip`, `ai-usage-clock-<version>-macos.tar.gz` oder `ai-usage-clock-<version>-linux.tar.gz`.
2. **Entpacken und starten:**
   - Windows: `ai-usage-clock.exe` ausführen
   - macOS: `ai-usage-clock.app` in den Ordner „Programme“ ziehen und öffnen
   - Linux: `./ai-usage-clock/ai-usage-clock` ausführen
3. **Dienste verbinden:** Bei Claude und Codex meldest du dich direkt in der App an. Für Dienste mit API-Schlüssel fügst du den Schlüssel unter **Settings** (den Einstellungen der App) ein. Die Details stehen in der [Einrichtungsanleitung](docs/setup.md) (englisch).

Die Builds sind nicht signiert, deshalb kann Windows oder macOS beim ersten Start warnen. [So gehst du vor](#warnung-von-smartscreen-oder-gatekeeper-beim-ersten-start).

## Unterstützte Dienste

| Dienst | Was du siehst | Wie die Verbindung läuft |
| --- | --- | --- |
| **Claude** | Limits für Session und Weekly (Sitzung und Woche), dazu das wöchentliche Fable-Limit in Tarifen, die eines haben | Anmeldung über deinen Browser (Google-Konto und Passkeys funktionieren) oder per eingefügtem Session-Cookie |
| **Codex** (ChatGPT) | Limits für Session und Weekly | Wie bei Claude |
| **Antigravity** | Nutzung von Gemini und von Claude+GPT, jeweils mit 5-Stunden- und Wochenlimit | Liest dein lokales Kommandozeilentool `agy` aus; in der App brauchst du weder Konto noch Schlüssel |
| **OpenCode Go** | Verbrauch für Rolling, Weekly und Monthly (gleitend, wöchentlich, monatlich) | API-Schlüssel von OpenCode |
| **GitHub Copilot** | Verbrauchte KI-Credits im Monat, gemessen am Kontingent deines Tarifs; Reset am Monatsersten | Fine-grained personal access token von GitHub |
| **OpenRouter** | Ausgaben heute und im laufenden Monat, optional ein Tagesbudget; mit einem Management-Schlüssel auch Guthaben und Aktivität pro Modell | API-Schlüssel von OpenRouter |

Claude, Codex und GitHub Copilot sind von Anfang an aktiv. Die übrigen Dienste und die Reset-Ankündigungen schaltest du unter **Settings** ein. Von Claude, Codex und OpenCode Go kannst du jeweils auch mehrere Konten im Blick behalten.

## Für KI-Agenten (MCP)

AI Usage Clock bringt einen optionalen lokalen MCP-Server mit, der standardmäßig deaktiviert ist. Damit können Coding-Agenten deinen Verbrauch prüfen, bevor sie eine teure Aufgabe starten, und pausieren, sobald ein von dir gesetztes Limit erreicht ist. Der Server liest nur einen bereinigten lokalen Nutzungs-Cache, nie deine Zugangsdaten. Die Einrichtung steht in [docs/mcp.md](docs/mcp.md) (englisch).

## Häufige Fragen

### Wie funktionieren die Reset-Ankündigungen?

Standardmäßig sind sie deaktiviert. Einschalten kannst du sie unter **Settings → General** (Allgemein) mit **Codex Resets** oder **Claude Resets**, den Schaltern für die beiden Dienste. AI Usage Clock liest dann zwei unabhängige Tracker von Dritten:

- codex-resets.com ordnet die Beiträge von @thsottiaux per KI ein.
- claude-resets.com sammelt die Beiträge von @ClaudeDevs und von Mitgliedern des Claude-Code-Teams.

Solange die App läuft, fragt sie jeden Tracker höchstens alle 15 Minuten ab; nach einem Neustart fragt sie erneut.

Die Kachel zeigt das jüngste Ereignis und wie lange es her ist, gekennzeichnet nach Typ:

- **Announced** (angekündigt): Ein Reset wurde vorab angekündigt. Diesen Typ gibt es nur bei Codex.
- **Reset** (zurückgesetzt): Die Limits wurden wieder aufgefüllt.
- **Banked** (Reset-Gutschein): Du hast einen Reset-Gutschein bekommen, den du selbst einlösen kannst.

Bei Codex gibt es zusätzlich die Zeile **Watch** (Prognose): eine KI-Schätzung, wie wahrscheinlich ein Reset ist. Eine offizielle Ankündigung ist das nicht, und eine Benachrichtigung löst sie nie aus. Ein Klick auf ↗ öffnet den Originalbeitrag, ✕ blendet die Kachel aus, bis der nächste Eintrag kommt.

Unter **Settings → Reset alerts** (Reset-Benachrichtigungen) legst du fest, bei welchen Typen du benachrichtigt wirst (Codex: Announced, Reset, Banked; Claude: Reset, Banked). Das allererste Ereignis, das die App bei einem Tracker findet, wird nur gespeichert, nicht gemeldet. Unter Windows erscheinen systemeigene Benachrichtigungen, die per Klick den Originalbeitrag öffnen. Andere Systeme zeigen eine Sprechblase im System-Tray, sofern vorhanden. Im Menüleisten-Modus von macOS und unter Linux ohne Tray gibt es keine Benachrichtigungen, die Kacheln werden aber weiter aktualisiert.

Die Daten stammen von Dritten und können verspätet oder falsch sein (neue Claude-Einträge bleiben unter Umständen bis zu 24 Stunden vorläufig). Maßgeblich ist immer der Originalbeitrag.

### Ist das eine offizielle App?

Nein. AI Usage Clock ist ein unabhängiges Open-Source-Projekt und ein inoffizielles lokales Desktop-Tool, weder von einem der angezeigten Dienste entwickelt noch von einem befürwortet. Seiten und APIs der Anbieter können sich ohne Vorankündigung ändern.

### Wohin gehen meine Daten?

Einstellungen, Nutzungsverlauf und Anmeldesitzungen bleiben auf deinem Rechner. Sitzungen und API-Schlüssel werden mit den Bordmitteln deines Betriebssystems für Zugangsdaten gespeichert: unter Windows in der Anmeldeinformationsverwaltung und mit DPAPI, unter macOS im Schlüsselbund, unter Linux im Secret Service. Die Sitzungen für Claude und ChatGPT liegen außerdem im eigenen Browserprofil-Ordner der App.

Es gibt keine Telemetrie und keinen Server von AI Usage Clock. Die App verbindet sich direkt mit den Diensten, die du einschaltest: mit den Nutzungsseiten von Claude und ChatGPT (geladen in einem eingebauten Browser) sowie mit den APIs von GitHub, OpenCode und OpenRouter. Die Werte für Antigravity kommen vom Tool `agy` auf deinem Rechner, das die App für dich aufruft; um seine eigenen Verbindungen kümmert sich `agy` selbst.

Wenn du die Reset-Ankündigungen einschaltest, kontaktiert die App außerdem codex-resets.com und claude-resets.com; diese Seiten sehen deine IP-Adresse sowie Namen und Version der App. Die optionale lokale Kostenerfassung liest die Logs von Claude Code und Codex auf deinem Rechner aus und lädt nichts hoch. Mehr dazu in [SECURITY.md](SECURITY.md) (englisch).

### Warnung von SmartScreen oder Gatekeeper beim ersten Start

Die Release-Builds sind nicht codesigniert. Neben jedem Archiv werden SHA256-Prüfsummen veröffentlicht.

- **Windows:** Wenn SmartScreen warnt, klicke auf **Weitere Informationen** und dann auf **Trotzdem ausführen**.
- **macOS:** Gatekeeper blockiert die App beim ersten Mal. Versuche einmal, sie zu öffnen, und gehe dann zu **Systemeinstellungen → Datenschutz & Sicherheit**. Klicke im Abschnitt **Sicherheit** bei der App auf **Öffnen** und dann auf **Dennoch öffnen**, gib dein Anmeldepasswort ein und klicke auf **OK**. Die Schaltfläche **Dennoch öffnen** steht nach dem Öffnungsversuch etwa eine Stunde lang zur Verfügung. Alternativ führst du einmal `xattr -dr com.apple.quarantine ai-usage-clock.app` aus.
- **Linux:** Hier gibt es keine Signaturprüfung. Setze bei `ai-usage-clock` das Ausführungsrecht, falls es noch fehlt.

Weitere Details, auch zum MCP-Hilfsprogramm unter macOS, stehen in [docs/build.md](docs/build.md#first-launch-warnings-on-unsigned-builds) (englisch).

### Brauche ich Python?

Für die Downloads nicht: Python und die Browser-Engine sind bereits enthalten. Python 3.11 oder neuer brauchst du nur, wenn du aus dem Quellcode startest oder mitentwickeln willst; siehe [docs/build.md](docs/build.md) (englisch).

### Läuft es auch unter macOS und Linux?

Ja, aber mit einer Einschränkung. Entwickelt wird unter Windows, und dort wird auch mit echten Konten getestet. Die Builds für macOS (dort ein Eintrag in der Menüleiste statt eines schwebenden Widgets) und Linux werden veröffentlicht, und die automatisierten Tests laufen auf allen drei Systemen. Das Aktualisieren echter Konten ist bisher aber nur unter Windows 11 geprüft. Betrachte macOS und Linux deshalb als Beta. Wie sich die Reset-Benachrichtigungen je nach System unterscheiden, steht in der ersten Frage. Wenn etwas nicht stimmt, [eröffne gern ein Issue](https://github.com/AIUsageClock/ai-usage-clock/issues).

### Ist es kostenlos?

Ja. Es ist kostenlos und Open Source unter der MIT-Lizenz. Für die angezeigten Dienste brauchst du jeweils eigene Konten oder Abos.

## Mehr

[Einrichtungsanleitung](docs/setup.md) (englisch) · [Tägliche Nutzung](docs/usage.md) (englisch) · [MCP-Nutzungswächter](docs/mcp.md) (englisch) · [Aus dem Quellcode bauen](docs/build.md) (englisch) · [Mitmachen](CONTRIBUTING.md) (englisch) · [Sicherheit](SECURITY.md) (englisch) · [Lizenz (MIT)](LICENSE)

Aktuelle Version: **1.0.0** · [Änderungsprotokoll](CHANGELOG.md) (englisch)

AI Usage Clock steht in keiner Verbindung zu Anthropic, OpenAI, Google, GitHub, Microsoft, OpenCode, OpenRouter oder anderen Anbietern. Produktnamen gehören ihren jeweiligen Inhabern.
