# MU Slack Reminder Bot

毎週日曜にGoogle Sheetsの当番表を読み込み、SlackのプライベートチャンネルへMU当番のリマインドを投稿します。

## 1. Google Sheetsの準備

対象スプレッドシートに、次の名前のシート（タブ）を作成します。

```text
MU当番
```

1行目をヘッダーにして、以下の列を用意してください。

| 日程 | 曜日 | 担当1 | 担当2 | 担当3 | 鍵預かり当番 |
|---|---|---|---|---|
| 2026/09/27 | 日 | 中島 | マヌエル | 迫田 | 迫田 |

- `日程`: `2026/09/27`のような日付。Botは実行日より後で最も近い日程を次週の当番として選びます。
- `担当1`, `担当2`, `担当3`: Slack表示名または実名。BotがSlackのユーザー一覧と照合してメンションします。
- `曜日`, `鍵預かり当番`など他の列はそのまま残して構いません。

Google Cloudでサービスアカウントを作成し、Google Sheets APIを有効化したうえで、そのサービスアカウントのメールアドレスを対象スプレッドシートに編集者として共有してください。

## 2. Slack Appの準備

Slack Appの **OAuth & Permissions → Bot Token Scopes** に以下だけを追加します。

```text
chat:write
users:read
```

Appをワークスペースにインストールし、Botを投稿先のプライベートチャンネルへ招待してください。

```text
/invite @MU Reminder Bot
```

SlackのユーザーIDは、Slackプロフィールの「メンバーIDをコピー」などから取得します。

## 3. GitHub Secrets

リポジトリの **Settings → Secrets and variables → Actions** に以下を登録します。

| Secret | 内容 |
|---|---|
| `SLACK_BOT_TOKEN` | `xoxb-...` のBot Token |
| `SLACK_CHANNEL_ID` | 投稿先プライベートチャンネルのID（`G...` または `C...`） |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | サービスアカウントJSONの内容を丸ごと貼り付け |
| `GOOGLE_SPREADSHEET_ID` | URL中の `/d/` と `/edit` の間のID |

このスプレッドシートのIDは次の部分です。

```text
https://docs.google.com/spreadsheets/d/ここがスプレッドシートID/edit
```

## 4. 手動テスト

GitHub Actionsの **MU Slack Reminder → Run workflow** から、`run_date` に当番表の日付を入れて実行できます。

初回は `dry_run` を有効にすると、Slackへ投稿せず内容だけログに表示します。

## 5. 投稿内容

BotはSlackのユーザーIDを使って次の形式でメンションします。

```text
<@U01234567> <@U07654321>
```

シートの名前をSlackの表示名・実名と照合し、投稿時にはSlackユーザーIDのメンションへ変換します。
