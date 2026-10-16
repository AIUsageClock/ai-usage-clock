<p align="center">
  <img src="src/aiusageclock/assets/aiusageclockicon.png" alt="AI Usage Clock のアイコン" width="160" />
</p>

<h1 align="center">AI Usage Clock</h1>

<p align="center"><strong>すべての AI の上限が見える。すべてのリセットがわかる。</strong></p>

<p align="center">
  複数の AI を使い分けていると、あとどれだけ使えるのか、さっきリセットがあったのかを、<br />
  サービスごとに見に行くことになりがちです。<br />
  AI Usage Clock は、各サービスの利用上限をデスクトップの小さなウィジェットにまとめて表示します。<br />
  Codex と Claude のリセット告知も拾うので、予告されたリセットは前もって把握でき、<br />
  使用量が急にゼロに戻ったときも、リセットがあったのかをここで確かめられます。
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.zh-CN.md">简体中文</a> · <strong>日本語</strong> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a>
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml"><img src="https://github.com/AIUsageClock/ai-usage-clock/actions/workflows/test.yml/badge.svg" alt="テストの状態" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0078d4" alt="Windows、macOS、Linux に対応" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT ライセンス" />
</p>

<p align="center">
  <a href="https://github.com/AIUsageClock/ai-usage-clock/releases/latest"><img src="https://img.shields.io/badge/Download-latest%20release-2ea44f?style=for-the-badge" alt="最新リリースをダウンロード" /></a>
</p>

<p align="center">
  <img src="docs/screenshots/windows-1.0.0.png" alt="Windows で動作する AI Usage Clock。Claude と Codex の使用量、Antigravity のクォータ、Codex と Claude のリセット告知が表示されている" width="520" />
</p>

<p align="center"><sub>Windows 版のウィジェット。実際に動いているリリース版から撮影したもので、使用量は撮影時点の値です。</sub></p>

<p align="center">
  <img src="docs/screenshots/win-panel-compact.png" alt="コンパクトモード：サービスごとにカプセル型の表示が 1 つずつ並ぶ" width="440" />
</p>

<p align="center"><sub>コンパクトモードでは、サービスごとに小さなカプセル 1 つまで縮めて表示できます（サンプルデータ）。</sub></p>

## できること

- **AI の上限を一か所に**：Claude、Codex、Antigravity、OpenCode Go、GitHub Copilot、OpenRouter を並べて表示し、サービスごとに使用量バーが付きます。期間が始まっている上限には、バーの横に残り時間も表示されます。
- **予告があれば事前に、なくてもあとから確認**：リセット告知をオンにすると、AI Usage Clock が Codex と Claude のリセット告知を拾います。前もって予告されるリセット（Codex の告知と、AI が予測する Watch 行）なら、準備をしておけます。一方で、何の前触れもなく来るリセットもあります。タイルには最新の告知が表示され続けるので、使用量が急にゼロに戻ったとき、リセットがあったのかどうかを確かめられます。元の投稿もワンクリックで開けます。
- **新しい告知が出たら通知**：希望すれば、新しい告知が出たときに通知を受け取れます（Windows ではシステム標準の通知）。通知は種類ごとに個別にオン・オフできます。告知の出どころは独立したサードパーティのトラッカーなので、遅れたり間違っていたりすることがあります。必ず元の投稿で確認してください。この機能は初期設定ではオフです。
- **手元のコンピューターで動作**：AI Usage Clock のアカウントも、サーバーも、テレメトリもありません。API キーは OS の安全な保管場所に保存します。Claude と ChatGPT のログインセッションも同じ場所に保存し、加えてアプリ専用のブラウザープロファイルフォルダーにも保存します。

## 3 ステップで導入

1. **ダウンロード**：[最新リリース](https://github.com/AIUsageClock/ai-usage-clock/releases/latest)から、お使いの OS 用のアーカイブを入手します。ファイル名は `ai-usage-clock-<version>-windows.zip`、`ai-usage-clock-<version>-macos.tar.gz`、`ai-usage-clock-<version>-linux.tar.gz` のいずれかです。
2. **展開（解凍）して起動**：
   - Windows：`ai-usage-clock.exe` を実行します
   - macOS：`ai-usage-clock.app` を「アプリケーション」フォルダーにドラッグしてから開きます
   - Linux：`./ai-usage-clock/ai-usage-clock` を実行します
3. **サービスを接続**：Claude と Codex はアプリ内でログインします。API キーを使うサービスは、**Settings**（設定画面）にキーを貼り付けます。詳しくは[セットアップガイド](docs/setup.md)（英語）をご覧ください。

ビルドにはコード署名をしていないため、初回起動時に Windows や macOS が警告を出すことがあります。[対処方法はこちら](#初回起動時に-smartscreen-や-gatekeeper-の警告が出る)。

## 対応サービス

| サービス | 表示される内容 | 接続方法 |
| --- | --- | --- |
| **Claude** | Session と Weekly（週）の上限。Fable の週上限があるプランでは、それも表示 | ブラウザーでログイン（Google アカウントやパスキーも可）、またはセッション Cookie を貼り付け |
| **Codex**（ChatGPT） | Session と Weekly の上限 | Claude と同じ |
| **Antigravity** | Gemini と Claude+GPT の使用量（それぞれ 5 時間と週の上限） | 手元の `agy` コマンドラインツールを読み取るので、アプリにアカウントやキーを登録する必要はありません |
| **OpenCode Go** | Rolling、Weekly、Monthly（ローリング・週・月）の使用量 | OpenCode の API キー |
| **GitHub Copilot** | 当月に使った AI クレジットを、プランの利用枠と比べて表示。毎月 1 日にリセット | GitHub の fine-grained personal access token |
| **OpenRouter** | 今日と今月の利用額、任意で 1 日の予算。管理キーがあれば残高とモデル別のアクティビティも | OpenRouter の API キー |

初期状態で有効なのは Claude、Codex、GitHub Copilot です。ほかのサービスとリセット告知は、**Settings** でオンにします。Claude、Codex、OpenCode Go は、複数のアカウントを登録して追跡できます。

## AI エージェントから使う（MCP）

AI Usage Clock には、ローカルで動く MCP サーバーが付属しています。使うかどうかは任意で、初期設定ではオフです。オンにすると、コーディングエージェントが使用量を大きく消費する作業を始める前に残りを確認し、設定しておいた上限に達したら一時停止できるようになります。読み取るのはサニタイズ済みのローカル使用量キャッシュだけで、認証情報には一切触れません。設定方法は [docs/mcp.md](docs/mcp.md)（英語）を参照してください。

## よくある質問

### リセット告知はどうやって取得していますか？

初期設定ではオフです。**Settings → General**（一般）で **Codex Resets** または **Claude Resets**（それぞれ Codex と Claude のリセット告知のスイッチ）をオンにすると、AI Usage Clock は独立したサードパーティのトラッカー 2 つを読みに行きます。

- codex-resets.com：@thsottiaux の投稿を AI で分類しています。
- claude-resets.com：@ClaudeDevs と Claude Code チームのメンバーの投稿を集めています。

アプリの起動中、各トラッカーへの問い合わせは最大で 15 分に 1 回です。アプリを再起動すると、あらためて問い合わせます。

タイルには、最新のイベントとそこからの経過時間が、種類のラベル付きで表示されます。

- **Announced**（予告）：リセットが事前に告知されました。この種類があるのは Codex だけです。
- **Reset**（リセット済み）：上限が回復しました。
- **Banked**（リセット券）：自分の好きなタイミングで使えるリセット券が付与されました。

Codex のタイルには **Watch**（予測）行もあります。これは AI がリセットの起こりやすさを予測したもので、公式の告知ではなく、通知も一切送りません。↗ をクリックすると元の投稿が開き、✕ をクリックすると次の新しいエントリーが届くまでタイルを隠せます。

**Settings → Reset alerts**（リセット通知）では、どの種類を通知するかを選べます（Codex は予告・リセット済み・リセット券、Claude はリセット済み・リセット券）。各トラッカーからアプリが初めて取得したイベントは、記録するだけで通知はしません。Windows ではシステム標準の通知を使い、クリックすると元の投稿が開きます。ほかの OS では、システムトレイがあればトレイのバルーン通知を使います。macOS のメニューバーモードと、トレイのない Linux では通知は出ませんが、タイルの表示は更新されます。

データはサードパーティがまとめたもので、遅れたり間違っていたりすることがあります（Claude の新しいエントリーは、最長 24 時間は暫定扱いのままのことがあります）。正しい情報は元の投稿で確認してください。

### 公式のアプリですか？

いいえ。AI Usage Clock は独立したオープンソースプロジェクトで、非公式のローカルデスクトップユーティリティです。表示しているどのサービスが作ったものでもなく、どのサービスの公認も受けていません。各サービスのページや API は、予告なく変わることがあります。

### データはどこに送られますか？

設定、使用量の履歴、ログインセッションは、お使いのコンピューターの中に保存されます。セッションと API キーの保存には、OS の資格情報の仕組みを使います。Windows では資格情報マネージャーと DPAPI、macOS ではキーチェーン、Linux では Secret Service です。Claude と ChatGPT のセッションは、アプリ専用のブラウザープロファイルフォルダーにも保存されます。

テレメトリはなく、AI Usage Clock のサーバーもありません。アプリは、オンにしたサービスに直接接続します。具体的には、Claude と ChatGPT の使用量ページ（内蔵ブラウザーで読み込みます）と、GitHub、OpenCode、OpenRouter の API です。Antigravity の使用量は、手元の `agy` ツールをアプリが代わりに実行して取得します。`agy` 自体の通信は `agy` が独自に行います。

リセット告知をオンにした場合は、codex-resets.com と claude-resets.com にも接続します。これらのサイトからは、IP アドレスと、アプリの名前・バージョンが見えます。任意で使えるローカルのコスト集計は、手元の Claude Code と Codex のログを読むだけで、何もアップロードしません。詳しくは [SECURITY.md](SECURITY.md)（英語）をご覧ください。

### 初回起動時に SmartScreen や Gatekeeper の警告が出る

リリース版のビルドにはコード署名をしていません。各アーカイブの横には SHA256 チェックサムを公開しています。

- **Windows：** SmartScreen の警告が出たら、「詳細情報」をクリックしてから「実行」をクリックします。
- **macOS：** 初回は Gatekeeper がアプリをブロックします。一度アプリを開こうとしてから、「システム設定」→「プライバシーとセキュリティ」に進み、「セキュリティ」の項目でこのアプリを見つけて「開く」をクリックし、続けて「このまま開く」をクリックします。ログインパスワードを入力し、「OK」をクリックしてください（「このまま開く」ボタンは、開こうとしてから約 1 時間使えます）。または、`xattr -dr com.apple.quarantine ai-usage-clock.app` を一度実行してもかまいません。
- **Linux：** 署名の仕組みはありません。`ai-usage-clock` に実行権限が付いていなければ、付けてください。

macOS の MCP ヘルパーを含む詳しい説明は、[docs/build.md](docs/build.md#first-launch-warnings-on-unsigned-builds)（英語）にあります。

### Python は必要ですか？

ダウンロード版なら不要です。Python とブラウザーエンジンは同梱されています。Python 3.11 以降が必要なのは、ソースから実行する場合や開発に参加する場合だけです。[docs/build.md](docs/build.md)（英語）を参照してください。

### macOS や Linux でも使えますか？

使えますが、注意点があります。開発は Windows で行っていて、実際のアカウントを使ったテストも Windows でしています。macOS 版（フローティングウィジェットではなく、メニューバーの項目として動きます）と Linux 版も公開していて、自動テストは 3 つの OS すべてで実行しています。ただ、実際のアカウントで使用量を更新できることを確認できているのは Windows 11 だけなので、macOS と Linux はベータ版と考えてください。リセット通知の動き方は OS によって違います（最初の質問を参照）。おかしな点があれば、[Issue](https://github.com/AIUsageClock/ai-usage-clock/issues) で知らせてください。

### 無料ですか？

はい。MIT ライセンスで公開している、無料のオープンソースソフトウェアです。ただし、表示する各サービスを使うには、それぞれのアカウントやサブスクリプションが必要です。

## ドキュメント

[セットアップガイド](docs/setup.md)（英語） · [日々の使い方](docs/usage.md)（英語） · [MCP による使用量ガード](docs/mcp.md)（英語） · [ソースからビルド](docs/build.md)（英語） · [コントリビューション](CONTRIBUTING.md)（英語） · [セキュリティ](SECURITY.md)（英語） · [ライセンス（MIT）](LICENSE)

現在のバージョン：**1.0.0** · [変更履歴](CHANGELOG.md)（英語）

AI Usage Clock は、Anthropic、OpenAI、Google、GitHub、Microsoft、OpenCode、OpenRouter をはじめ、どのサービス提供元とも提携関係にありません。各製品名は、それぞれの権利者に帰属します。
