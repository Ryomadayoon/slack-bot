# MU Slack Reminder Bot

毎週日曜にGoogle Sheetsの当番表を読み込み、SlackのプライベートチャンネルへMU当番のリマインドを投稿します。

## 1. Google Sheetsの準備

対象スプレッドシートに、次の名前のシート（タブ）を作成します。

```text
MU当番
```

1行目をヘッダーにして、以下の列を用意してください。

| date | member1_slack_id | member2_slack_id | mu_date | posted_at |
|---|---|---|---|---|
| 2026-09-27 | U01234567 | U07654321 | 9/27（日） | |

- `date`: GitHub Actionsが実行する日。`YYYY-MM-DD`形式
- `member1_slack_id`, `member2_slack_id`: SlackのユーザーID。表示名ではなく`U`から始まるID
- `mu_date`: 投稿文に表示するMU開催日。例：`9/27（日）`
- `posted_at`: Botが投稿後に記録する列。最初は空欄

Google Cloudでサービスアカウントを作成し、Google Sheets APIを有効化したうえで、そのサービスアカウントのメールアドレスを対象スプレッドシートに編集者として共有してください。

## 2. Slack Appの準備

Slack Appの **OAuth & Permissions → Bot Token Scopes** に以下だけを追加します。

```text
chat:write
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

表示名ではなくIDを使うため、名前変更の影響を受けません。

