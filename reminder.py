import json
import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


JST = ZoneInfo("Asia/Tokyo")
SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
MEMBER_HEADERS = ("担当1", "担当2", "担当3")
IGNORED_SHEET_NAMES = {"マヌエル", "マヌエル・澤地"}


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
    if isinstance(value, (int, float)):
        # Google Sheets may return a date as its serial number.
        return date(1899, 12, 30) + timedelta(days=int(value))
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
        .get(spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'!A:Z")
        .execute()
    )
    values = result.get("values", [])
    if not values:
        raise RuntimeError(f"Sheet '{sheet_name}' is empty")

    rows = []
    for raw in values:
        date_index = None
        duty_date = None
        for index, cell in enumerate(raw):
            try:
                duty_date = parse_date(cell)
                date_index = index
                break
            except (RuntimeError, ValueError, TypeError):
                continue
        if date_index is None:
            continue
        # Read weekday, 担当1〜3, 鍵預かり当番 relative to the detected date cell.
        rows.append(
            {
                "日程": str(raw[date_index]).strip(),
                "担当1": str(raw[date_index + 2]).strip() if len(raw) > date_index + 2 else "",
                "担当2": str(raw[date_index + 3]).strip() if len(raw) > date_index + 3 else "",
                "担当3": str(raw[date_index + 4]).strip() if len(raw) > date_index + 4 else "",
                "鍵預かり当番": str(raw[date_index + 5]).strip() if len(raw) > date_index + 5 else "",
                "_date": duty_date,
            }
        )
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
    name_entries = []
    exact = {}
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
        normalized_names = {normalize_name(name) for name in names if name}
        if not normalized_names:
            continue
        entry = (user["id"], names)
        name_entries.append((user["id"], names, normalized_names))
        for normalized in normalized_names:
            exact.setdefault(normalized, set()).add(user["id"])

    mentions = []
    unresolved = []
    ambiguous = []
    for header in MEMBER_HEADERS:
        sheet_name = row.get(header, "").strip()
        if not sheet_name or normalize_name(sheet_name) in {
            normalize_name(value) for value in IGNORED_SHEET_NAMES
        }:
            continue
        normalized_sheet_name = normalize_name(sheet_name)
        exact_matches = exact.get(normalized_sheet_name, set())
        if len(exact_matches) == 1:
            user_id = next(iter(exact_matches))
        else:
            fuzzy_matches = []
            for user_id, names, normalized_names in name_entries:
                if any(
                    normalized_sheet_name in candidate
                    or candidate in normalized_sheet_name
                    for candidate in normalized_names
                ):
                    fuzzy_matches.append((user_id, names))
            unique_ids = {user_id for user_id, _ in fuzzy_matches}
            if len(unique_ids) == 1:
                user_id = next(iter(unique_ids))
            elif len(unique_ids) > 1:
                user_id = None
                ambiguous.append(sheet_name)
            else:
                user_id = None
        if user_id:
            mentions.append(f"<@{user_id}>")
        elif sheet_name not in ambiguous:
            unresolved.append(sheet_name)

    if ambiguous:
        raise RuntimeError(
            f"Slack user mapping is ambiguous for sheet name(s): {', '.join(ambiguous)}"
        )
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
