import json
import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


JST = ZoneInfo("Asia/Tokyo")
SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
DATE_HEADERS = ("日程", "日付")
MEMBER_HEADERS = ("担当1", "担当2", "担当3")


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def run_date() -> date:
    value = os.environ.get("RUN_DATE", "").strip()
    if value:
        return parse_date(value)
    return datetime.now(JST).date()


def parse_date(value: str) -> date:
    match = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", value.strip())
    if not match:
        raise RuntimeError(f"Could not parse date: {value}")
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def display_date(value: date) -> str:
    weekday = "月火水木金土日"[value.weekday()]
    return f"{value.year}/{value.month}/{value.day}（{weekday}）"


def sheets_service():
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(required_env("GOOGLE_SERVICE_ACCOUNT_JSON")), scopes=SHEETS_SCOPE
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def load_rows(service, spreadsheet_id: str, sheet_name: str):
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'!A:F")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        raise RuntimeError(f"Sheet '{sheet_name}' is empty")

    headers = [cell.strip() for cell in values[0]]
    date_index = next((headers.index(header) for header in DATE_HEADERS if header in headers), None)
    missing = [header for header in MEMBER_HEADERS if header not in headers]
    if date_index is None or missing:
        raise RuntimeError(
            f"Sheet '{sheet_name}' must have 日程 and 担当1, 担当2, 担当3 columns"
        )

    rows = []
    for raw in values[1:]:
        row = {headers[index]: raw[index].strip() if index < len(raw) else "" for index in range(len(headers))}
        if row.get(headers[date_index], ""):
            row["_date"] = parse_date(row[headers[date_index]])
            rows.append(row)
    return rows


def find_next_duty(rows, today: date):
    candidates = [row for row in rows if row["_date"] > today]
    if not candidates:
        raise RuntimeError(f"No future duty date found after {today.isoformat()}")
    return min(candidates, key=lambda row: row["_date"])


def normalize_name(value: str) -> str:
    return re.sub(r"[\s　]+", "", value).casefold()


def slack_users(client: WebClient):
    users = []
    cursor = None
    while True:
        response = client.users_list(cursor=cursor) if cursor else client.users_list()
        users.extend(response.get("members", []))
        cursor = response.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    return users


def resolve_mentions(client: WebClient, row: dict) -> str:
    users = slack_users(client)
    by_name = {}
    for user in users:
        if user.get("deleted") or user.get("is_bot"):
            continue
        profile = user.get("profile", {})
        names = {
            user.get("name", ""),
            user.get("real_name", ""),
            profile.get("display_name", ""),
            profile.get("real_name", ""),
        }
        for name in names:
            if name:
                by_name[normalize_name(name)] = user["id"]

    mentions = []
    unresolved = []
    for header in MEMBER_HEADERS:
        name = row.get(header, "").strip()
        if not name:
            continue
        user_id = by_name.get(normalize_name(name))
        if user_id:
            mentions.append(f"<@{user_id}>")
        else:
            unresolved.append(name)
    if unresolved:
        raise RuntimeError(f"Slack user not found for sheet name(s): {', '.join(unresolved)}")
    if not mentions:
        raise RuntimeError("No names found in 担当1, 担当2, 担当3")
    return " ".join(mentions)


def build_message(row: dict, mentions: str) -> str:
    event_date = display_date(row["_date"])
    sheet_url = "https://docs.google.com/spreadsheets/d/1CH-JOlTq-PYzeRdsKL47XeftKD16Tt7UQyz4_JiGtEs/edit?usp=sharing"
    return f"""{mentions}
お疲れ様です！
今週のMUの鍵預かりの入力を<{sheet_url}|こちら>にお願いします。
（出勤がなく受け取り・返却が厳しい場合は本日中にall-askで代わりを探すメッセージを送ってください。）
当番の方、このメッセージの確認・シートの入力が終わりましたら「🔥」のリアクションをお願いいたします！
また、当番でなくてもMU参加できるよって方はこのメッセージに「:fire:」のリアクションをお願いいたします！

また、鍵当番の方は木番のslack「#all-cypher-2026」の方にMUの宣伝をお願いします！
例）
お疲れ様です！
今週のMUは{event_date}に開催します🎉

個人的に〇〇にハマっているのでこれについていっぱいお話しできたらなと思っています☺️
（何か一言）

みなさんでお菓子食べながらいっぱいお話ししましょー🍪
参加できる方はこのメッセージに「:+1:」のリアクションお願いします！"""


def main():
    spreadsheet_id = required_env("GOOGLE_SPREADSHEET_ID")
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "MU当番")
    today = run_date()
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    sheet_service = sheets_service()
    row = find_next_duty(load_rows(sheet_service, spreadsheet_id, sheet_name), today)
    client = WebClient(token=required_env("SLACK_BOT_TOKEN"))
    message = build_message(row, resolve_mentions(client, row))

    if dry_run:
        print(f"DRY RUN - next duty date: {row['_date'].isoformat()}\n")
        print(message)
        return

    try:
        response = client.chat_postMessage(
            channel=required_env("SLACK_CHANNEL_ID"), text=message, unfurl_links=False
        )
    except SlackApiError as error:
        raise RuntimeError(f"Slack API error: {error.response.get('error')}") from error
    print(f"Posted reminder for {row['_date'].isoformat()}: {response['ts']}")


if __name__ == "__main__":
    main()
