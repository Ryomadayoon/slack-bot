import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


JST = ZoneInfo("Asia/Tokyo")
SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
HEADERS = ["date", "member1_slack_id", "member2_slack_id", "mu_date", "posted_at"]


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def target_date() -> str:
    return os.environ.get("RUN_DATE", "").strip() or datetime.now(JST).date().isoformat()


def sheets_service():
    credentials_json = required_env("GOOGLE_SERVICE_ACCOUNT_JSON")
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(credentials_json), scopes=SHEETS_SCOPE
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def load_rows(service, spreadsheet_id: str, sheet_name: str):
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'!A:E")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        raise RuntimeError(f"Sheet '{sheet_name}' is empty")

    headers = values[0]
    missing = [header for header in HEADERS if header not in headers]
    if missing:
        raise RuntimeError(f"Missing columns in '{sheet_name}': {', '.join(missing)}")

    rows = []
    for row_number, raw in enumerate(values[1:], start=2):
        row = {header: raw[index].strip() if index < len(raw) else "" for index, header in enumerate(headers)}
        row["_row_number"] = row_number
        if row.get("date"):
            rows.append(row)
    return rows


def update_posted_at(service, spreadsheet_id: str, sheet_name: str, row_number: int):
    timestamp = datetime.now(JST).isoformat(timespec="seconds")
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!E{row_number}",
        valueInputOption="RAW",
        body={"values": [[timestamp]]},
    ).execute()


def build_message(row: dict) -> str:
    member_ids = [row.get("member1_slack_id", ""), row.get("member2_slack_id", "")]
    member_ids = [member_id for member_id in member_ids if member_id]
    if not member_ids:
        raise RuntimeError(f"No Slack member IDs in row {row['_row_number']}")

    mentions = " ".join(f"<@{member_id}>" for member_id in member_ids)
    mu_date = row.get("mu_date") or row["date"]
    return f"""{mentions}
お疲れ様です！
今週のMUの鍵預かりの入力を<https://docs.google.com/spreadsheets/d/1CH-JOlTq-PYzeRdsKL47XeftKD16Tt7UQyz4_JiGtEs/edit?usp=sharing|こちら>にお願いします。
（出勤がなく受け取り・返却が厳しい場合は本日中にall-askで代わりを探すメッセージを送ってください。）
当番の方、このメッセージの確認・シートの入力が終わりましたら「🔥」のリアクションをお願いいたします！
また、当番でなくてもMU参加できるよって方はこのメッセージに「:fire:」のリアクションをお願いいたします！

また、鍵当番の方は木番のslack「#all-cypher-2026」の方にMUの宣伝をお願いします！
例）
お疲れ様です！
今週のMUは{mu_date}に開催します🎉

個人的に〇〇にハマっているのでこれについていっぱいお話しできたらなと思っています☺️
（何か一言）

みなさんでお菓子食べながらいっぱいお話ししましょー🍪
参加できる方はこのメッセージに「:+1:」のリアクションお願いします！"""


def main():
    spreadsheet_id = required_env("GOOGLE_SPREADSHEET_ID")
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "MU当番")
    run_date = target_date()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    service = sheets_service()
    rows = [row for row in load_rows(service, spreadsheet_id, sheet_name) if row["date"] == run_date]
    if not rows:
        raise RuntimeError(f"No duty row found for {run_date}")
    if len(rows) > 1:
        raise RuntimeError(f"Multiple duty rows found for {run_date}")

    row = rows[0]
    if row.get("posted_at"):
        print(f"Already posted for {run_date}: {row['posted_at']}")
        return

    message = build_message(row)
    if dry_run:
        print("DRY RUN - message was not posted:\n")
        print(message)
        return

    client = WebClient(token=required_env("SLACK_BOT_TOKEN"))
    try:
        response = client.chat_postMessage(
            channel=required_env("SLACK_CHANNEL_ID"),
            text=message,
            unfurl_links=False,
        )
    except SlackApiError as error:
        raise RuntimeError(f"Slack API error: {error.response.get('error')}") from error

    update_posted_at(service, spreadsheet_id, sheet_name, row["_row_number"])
    print(f"Posted reminder for {run_date}: {response['ts']}")


if __name__ == "__main__":
    main()
