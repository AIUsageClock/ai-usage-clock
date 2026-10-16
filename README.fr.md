<p align="center">
  <img src="src/aiusageclock/assets/aiusageclockicon.png" alt="Icône de l’application AI Usage Clock" width="160" />
</p>

<h1 align="center">AI Usage Clock</h1>

<p align="center"><strong>Voyez tous vos quotas d’IA. Suivez chaque remise à zéro.</strong></p>

<p align="center">
  Vous jonglez entre plusieurs IA ? Pour savoir ce qu’il vous reste sur chacune, ou si un quota vient d’être réinitialisé, il faut souvent aller vérifier site par site.<br />
  AI Usage Clock rassemble ces limites d’utilisation dans un petit widget de bureau.<br />
  Il relève aussi les annonces de réinitialisation de Codex et de Claude : quand une réinitialisation est annoncée à l’avance, vous êtes au courant ;<br />
  quand votre consommation retombe brusquement à zéro, vous savez où vérifier.
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.es.md">Español</a> · <strong>Français</strong> · <a href="README.de.md">Deutsch</a>
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml"><img src="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml/badge.svg" alt="État des tests" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078d4" alt="Windows, macOS et Linux" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="Licence MIT" />
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/releases/latest"><img src="https://img.shields.io/badge/Download-latest%20release-2ea44f?style=for-the-badge" alt="Télécharger la dernière version" /></a>
</p>

<p align="center">
  <img src="docs/screenshots/windows-1.0.0.png" alt="AI Usage Clock sous Windows : consommation Claude et Codex, quotas Antigravity, annonces de réinitialisation Codex et Claude" width="520" />
</p>

<p align="center"><sub>Le widget sous Windows, capturé sur une version publiée en fonctionnement ; les chiffres de consommation sont ceux du moment de la capture.</sub></p>

<p align="center">
  <img src="docs/screenshots/win-panel-compact.png" alt="Mode compact : une pastille par service" width="440" />
</p>

<p align="center"><sub>Le mode compact réduit le widget à une pastille par service (données d’exemple).</sub></p>

## Ce que fait AI Usage Clock

- **Tous vos quotas d’IA au même endroit.** Claude, Codex, Antigravity, OpenCode Go, GitHub Copilot et OpenRouter, côte à côte, chacun avec sa propre jauge. Pour les limites en cours, le temps restant s’affiche à côté de la jauge.
- **Un préavis pour certaines réinitialisations, un repère pour les autres.** Activez les annonces de réinitialisation, et AI Usage Clock relève celles de Codex et de Claude. Certaines réinitialisations sont annoncées à l’avance (les annonces Codex, plus une ligne Watch prédite par une IA) : vous avez le temps de vous organiser. D’autres tombent sans prévenir : la vignette garde la dernière annonce sous les yeux, si bien que lorsque votre consommation retombe brusquement à zéro, vous pouvez vérifier si une réinitialisation vient d’avoir lieu, et ouvrir la publication d’origine en un clic.
- **Une notification quand une annonce tombe.** Si vous le souhaitez, recevez une notification à chaque nouvelle annonce (notifications natives sous Windows), avec un réglage distinct pour chaque type. Les annonces proviennent de sites de suivi tiers et indépendants : elles peuvent arriver en retard ou se tromper, alors vérifiez la publication d’origine. Cette fonction est désactivée par défaut.
- **Tout se passe sur votre ordinateur.** Pas de compte AI Usage Clock, pas de serveur, pas de télémétrie. Les clés d’API sont conservées dans le stockage sécurisé de votre système d’exploitation, tout comme les sessions de connexion Claude et ChatGPT, également enregistrées dans le dossier de profil de navigateur propre à l’application.

## Prise en main en 3 étapes

1. **Téléchargez** l’archive de votre système depuis la [dernière version](https://github.com/AIUsageClock/ai-usage-clock/releases/latest) : `ai-usage-clock-<version>-windows.zip`, `ai-usage-clock-<version>-macos.tar.gz` ou `ai-usage-clock-<version>-linux.tar.gz`.
2. **Décompressez-la et lancez l’application.**
   - Windows : lancez `ai-usage-clock.exe`
   - macOS : faites glisser `ai-usage-clock.app` dans le dossier Applications, puis ouvrez-la
   - Linux : lancez `./ai-usage-clock/ai-usage-clock`
3. **Connectez vos services.** Pour Claude et Codex, connectez-vous directement dans l’application ; pour les services à clé d’API, collez la clé dans **Settings** (les paramètres). Les étapes détaillées sont dans le [guide de configuration](docs/setup.md) (en anglais).

Les versions ne sont pas signées : Windows ou macOS peut donc afficher un avertissement au premier lancement. [Voici la marche à suivre](#avertissement-smartscreen-ou-gatekeeper-au-premier-lancement).

## Services pris en charge

| Service | Ce que vous voyez | Connexion |
| --- | --- | --- |
| **Claude** | Limites Session et Weekly (hebdomadaire), plus la limite hebdomadaire Fable sur les forfaits qui en comportent une | Connectez-vous via votre navigateur (compte Google et clés d’accès acceptés) ou collez un cookie de session |
| **Codex** (ChatGPT) | Limites Session et Weekly | Comme pour Claude |
| **Antigravity** | Consommation Gemini et Claude+GPT, chacune avec une limite sur 5 heures et une limite hebdomadaire | Lecture de votre outil en ligne de commande `agy` local ; aucun compte ni clé dans l’application |
| **OpenCode Go** | Consommation Rolling, Weekly et Monthly (fenêtre glissante, semaine, mois) | Clé d’API OpenCode |
| **GitHub Copilot** | Crédits IA consommés dans le mois, comparés à l’enveloppe de votre forfait ; compteur remis à zéro le premier du mois | Jeton d’accès personnel GitHub de type *fine-grained* |
| **OpenRouter** | Dépenses du jour et du mois, budget quotidien facultatif ; solde et activité par modèle avec une clé de gestion | Clé d’API OpenRouter |

Claude, Codex et GitHub Copilot sont activés par défaut. Les autres services, ainsi que les annonces de réinitialisation, s’activent dans **Settings**. Vous pouvez suivre plusieurs comptes Claude, Codex ou OpenCode Go.

## Laisser vos agents IA consulter vos quotas (MCP)

AI Usage Clock intègre un serveur MCP local, facultatif et désactivé par défaut. Il permet aux agents de code de vérifier votre consommation avant de lancer un travail coûteux, et de se mettre en pause une fois atteinte la limite que vous avez fixée. Il ne lit qu’un cache local des données d’utilisation, débarrassé des informations sensibles, et jamais vos identifiants. La configuration est décrite dans [docs/mcp.md](docs/mcp.md) (en anglais).

## Questions fréquentes

### Comment fonctionnent les annonces de réinitialisation ?

Elles sont désactivées par défaut. Activez-les dans **Settings → General** (réglages généraux) avec **Codex Resets** ou **Claude Resets** (les annonces de chaque service). AI Usage Clock consulte alors deux sites de suivi tiers et indépendants :

- codex-resets.com, qui classe à l’aide d’une IA les publications de @thsottiaux ;
- claude-resets.com, qui rassemble les publications de @ClaudeDevs et des membres de l’équipe Claude Code.

Tant que l’application tourne, elle interroge chaque site au plus une fois toutes les 15 minutes, et de nouveau à chaque redémarrage.

La vignette affiche le dernier événement, depuis combien de temps il a eu lieu, et son type :

- **Announced** (annoncée) : une réinitialisation a été annoncée à l’avance. Seul Codex a ce type.
- **Reset** (réinitialisée) : les quotas sont rechargés.
- **Banked** (bon de réinitialisation) : vous avez reçu un bon de réinitialisation, à utiliser vous-même au moment de votre choix.

La vignette Codex comporte aussi une ligne **Watch** (à surveiller) : une prévision, établie par une IA, de la probabilité d’une réinitialisation. Ce n’est pas une annonce officielle, et elle n’envoie jamais de notification. Cliquez sur ↗ pour ouvrir la publication d’origine, ou sur ✕ pour masquer la vignette jusqu’à la prochaine entrée.

Dans **Settings → Reset alerts** (alertes de réinitialisation), choisissez les types qui vous sont notifiés (Codex : Announced, Reset, Banked ; Claude : Reset, Banked). Le tout premier événement trouvé sur un site de suivi est simplement enregistré, sans notification. Sous Windows, ce sont des notifications natives, qui ouvrent la publication d’origine d’un clic ; sur les autres systèmes, une info-bulle apparaît dans la zone de notification, s’il y en a une. Aucune notification en mode barre des menus sur macOS, ni sous Linux sans zone de notification ; les vignettes, elles, continuent de se mettre à jour.

Les données sont compilées par des tiers et peuvent arriver en retard ou être erronées (une nouvelle entrée Claude peut rester provisoire jusqu’à 24 heures) : c’est la publication d’origine qui fait foi.

### Est-ce une application officielle ?

Non. AI Usage Clock est un projet open source indépendant, un utilitaire de bureau local et non officiel. Il n’est ni conçu ni approuvé par aucun des services qu’il affiche. Les pages et les API des fournisseurs peuvent changer sans préavis.

### Où vont mes données ?

Vos réglages, votre historique de consommation et vos sessions de connexion restent sur votre ordinateur. Sessions et clés d’API sont confiées aux mécanismes d’identification de votre système : le Gestionnaire d’identification (Credential Manager) et DPAPI sous Windows, le trousseau (Keychain) sous macOS, Secret Service sous Linux. Les sessions Claude et ChatGPT sont aussi conservées dans le dossier de profil de navigateur propre à l’application.

Aucune télémétrie, aucun serveur AI Usage Clock. L’application se connecte directement aux services que vous activez : les pages de consommation de Claude et de ChatGPT (chargées dans un navigateur intégré), et les API de GitHub, d’OpenCode et d’OpenRouter. Pour Antigravity, la consommation vient de l’outil `agy` installé sur votre ordinateur, que l’application lance pour vous ; `agy` gère lui-même ses connexions.

Si vous activez les annonces de réinitialisation, l’application contacte aussi codex-resets.com et claude-resets.com ; ces sites voient votre adresse IP ainsi que le nom et la version de l’application. Le suivi local des coûts, facultatif, lit les journaux de Claude Code et de Codex sur votre ordinateur et n’envoie rien. Plus de détails dans [SECURITY.md](SECURITY.md) (en anglais).

### Avertissement SmartScreen ou Gatekeeper au premier lancement

Les versions publiées ne sont pas signées (pas de signature de code) ; des sommes de contrôle SHA256 sont publiées à côté de chaque archive.

- **Windows :** si SmartScreen affiche un avertissement, cliquez sur **Informations complémentaires**, puis sur **Exécuter quand même**.
- **macOS :** Gatekeeper bloque l’application la première fois. Essayez de l’ouvrir une fois, puis allez dans **Réglages Système → Confidentialité et sécurité**, repérez l’application dans la section Sécurité, cliquez sur **Ouvrir**, puis sur **Ouvrir quand même**, saisissez votre mot de passe d’ouverture de session et cliquez sur **OK** (le bouton **Ouvrir quand même** reste disponible environ une heure après la tentative). Vous pouvez aussi lancer une fois `xattr -dr com.apple.quarantine ai-usage-clock.app`.
- **Linux :** il n’y a pas de couche de signature. Rendez `ai-usage-clock` exécutable s’il ne l’est pas déjà.

Plus de détails, notamment sur le programme d’assistance MCP sous macOS, dans [docs/build.md](docs/build.md#first-launch-warnings-on-unsigned-builds) (en anglais).

### Faut-il installer Python ?

Pas pour les versions téléchargées : Python et le moteur de navigateur sont inclus. Python 3.11 ou plus récent n’est nécessaire que pour lancer l’application depuis les sources ou pour contribuer ; voir [docs/build.md](docs/build.md) (en anglais).

### Fonctionne-t-il sous macOS et Linux ?

Oui, avec une réserve. Windows est la plateforme de développement, et celle où l’application est testée avec de vrais comptes. Les versions macOS (un élément dans la barre des menus plutôt qu’un widget flottant) et Linux sont publiées, et les tests automatisés tournent sur les trois systèmes, mais l’actualisation de vrais comptes n’a été vérifiée que sous Windows 11 : considérez donc macOS et Linux comme des versions bêta. Les notifications de réinitialisation varient selon le système ; voir la première question. En cas de souci, [ouvrez une issue](https://github.com/AIUsageClock/ai-usage-clock/issues).

### Est-ce gratuit ?

Oui. C’est un logiciel gratuit et open source, sous licence MIT. Les services qu’il affiche nécessitent leurs propres comptes ou abonnements.

## Pour aller plus loin

[Guide de configuration](docs/setup.md) (en anglais) · [Utilisation au quotidien](docs/usage.md) (en anglais) · [Garde-fou de consommation MCP](docs/mcp.md) (en anglais) · [Compiler depuis les sources](docs/build.md) (en anglais) · [Contribuer](CONTRIBUTING.md) (en anglais) · [Sécurité](SECURITY.md) (en anglais) · [Licence (MIT)](LICENSE)

Version actuelle : **1.0.0** · [Journal des modifications](CHANGELOG.md) (en anglais)

AI Usage Clock n’est affilié ni à Anthropic, ni à OpenAI, ni à Google, ni à GitHub, ni à Microsoft, ni à OpenCode, ni à OpenRouter, ni à aucun autre fournisseur. Les noms de produits appartiennent à leurs propriétaires respectifs.
