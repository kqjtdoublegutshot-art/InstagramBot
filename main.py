import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from instagram_api import InstagramAPI
from rules import find_matching_rule, has_rule_for_media, load_rules, pick_message, save_rules

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Instagram Auto-Response Bot")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
_processed: set[str] = set()
_pending_follows: dict[str, list[dict]] = {}

_ACTIVITY_FILE = Path(__file__).parent / "activity.json"

def _load_activity() -> list[dict]:
    try:
        return json.loads(_ACTIVITY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

_activity: list[dict] = _load_activity()


def _log_activity(**kwargs):
    _activity.insert(0, {"time": datetime.now(KST).strftime("%m/%d %H:%M"), **kwargs})
    if len(_activity) > 100:
        _activity.pop()
    try:
        _ACTIVITY_FILE.write_text(json.dumps(_activity, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("activity.json 저장 실패: %s", e)
APP_SECRET = os.environ["APP_SECRET"]
api = InstagramAPI(
    os.environ["INSTAGRAM_ACCESS_TOKEN"],
    os.getenv("INSTAGRAM_USER_ID") or os.getenv("IG_USER_ID"),
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_USER_IDS = [uid.strip() for uid in os.getenv("TELEGRAM_USER_IDS", "").split(",") if uid.strip()]

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
_security = HTTPBasic()

_ADMIN_HTML_FILE = Path(__file__).parent / "admin.html"
_PUBLIC_HTML_FILE = Path(__file__).parent / "public.html"


def _check_admin(credentials: HTTPBasicCredentials = Depends(_security)):
    ok = secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    if credentials.username != "admin" or not ok:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})


async def _notify_telegram(message: str):
    if not TELEGRAM_TOKEN:
        return
    async with httpx.AsyncClient(timeout=5.0) as client:
        for uid in TELEGRAM_USER_IDS:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": uid, "text": message},
                )
            except Exception as e:
                log.error("텔레그램 알림 실패: %s", e)


def _valid_signature(payload: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@app.get("/", response_class=HTMLResponse)
async def public_home():
    return _PUBLIC_HTML_FILE.read_text(encoding="utf-8")


@app.get("/start", response_class=HTMLResponse)
async def root():
    return _PUBLIC_HTML_FILE.read_text(encoding="utf-8")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    return _PUBLIC_HTML_FILE.read_text(encoding="utf-8")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    return _PUBLIC_HTML_FILE.read_text(encoding="utf-8")


@app.get("/disabled-policy-page", response_class=HTMLResponse)
async def data_deletion_page():
    return _PUBLIC_HTML_FILE.read_text(encoding="utf-8")

    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Bot</title>
<style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
a{padding:12px 24px;background:#0066cc;color:#fff;text-decoration:none;border-radius:8px;font-size:16px}</style>
</head><body><a href="/console">관리자 대시보드</a></body></html>"""


@app.get("/miniapps/3min-stretch", response_class=HTMLResponse)
@app.get("/miniapps/3min-stretch/", response_class=HTMLResponse)
async def three_min_stretch_page():
    return _PUBLIC_HTML_FILE.read_text(encoding="utf-8")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/console", response_class=HTMLResponse)
async def admin_page(_: HTTPBasicCredentials = Depends(_check_admin)):
    return _ADMIN_HTML_FILE.read_text(encoding="utf-8")


@app.get("/console/status")
async def admin_status(_: HTTPBasicCredentials = Depends(_check_admin)):
    result = {}
    for service in ("instagram-bot", "telegram-bot"):
        r = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True)
        result[service] = r.stdout.strip()
    return result


@app.post("/console/restart/{service}")
async def admin_restart(service: str, _: HTTPBasicCredentials = Depends(_check_admin)):
    if service not in ("instagram-bot", "telegram-bot"):
        raise HTTPException(status_code=400, detail="Unknown service")
    subprocess.Popen(["sudo", "systemctl", "restart", service])
    return {"status": "restarting"}


@app.get("/console/rules")
async def get_rules(_: HTTPBasicCredentials = Depends(_check_admin)):
    return {"rules": load_rules()}


@app.post("/console/rules")
async def add_rule(request: Request, _: HTTPBasicCredentials = Depends(_check_admin)):
    rule = await request.json()
    rules = load_rules()
    rules.append(rule)
    save_rules(rules)
    return {"status": "ok"}


@app.put("/console/rules/{index}")
async def update_rule(index: int, request: Request, _: HTTPBasicCredentials = Depends(_check_admin)):
    rule = await request.json()
    rules = load_rules()
    if index >= len(rules):
        raise HTTPException(status_code=404)
    rules[index] = rule
    save_rules(rules)
    return {"status": "ok"}


@app.delete("/console/rules/{index}")
async def delete_rule(index: int, _: HTTPBasicCredentials = Depends(_check_admin)):
    rules = load_rules()
    if index >= len(rules):
        raise HTTPException(status_code=404)
    rules.pop(index)
    save_rules(rules)
    return {"status": "ok"}


@app.get("/console/activity")
async def get_activity(_: HTTPBasicCredentials = Depends(_check_admin)):
    return {"activity": _activity}


@app.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        log.info("Webhook verified")
        return hub_challenge
    raise HTTPException(status_code=403, detail="Verification failed")


SKIP_SIGNATURE = os.getenv("SKIP_SIGNATURE", "false").lower() == "true"


@app.post("/webhook")
async def handle_webhook(request: Request):
    body = await request.body()
    if SKIP_SIGNATURE:
        log.warning("서명 검증 건너뜀 (개발 모드)")
    else:
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _valid_signature(body, signature):
            expected = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
            log.error("서명 불일치 | received=%s | expected=%s", signature, expected)
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        log.warning("Invalid webhook JSON received")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    entries = data.get("entry", [])
    fields = [
        change.get("field")
        for entry in entries
        for change in entry.get("changes", [])
        if isinstance(change, dict)
    ]
    messaging_count = sum(len(entry.get("messaging", [])) for entry in entries)
    log.info(
        "Webhook received: entries=%s fields=%s messaging_events=%s",
        len(entries),
        fields,
        messaging_count,
    )
    log.debug("Webhook payload: %s", data)

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") == "comments":
                value = change["value"]
                verb = value.get("verb", "add")
                if verb == "remove":
                    log.warning("*** 댓글 삭제 *** id=%s", value.get("id"))
                    continue
                await _process_comment(value)

        for msg_event in entry.get("messaging", []):
            sender_id = msg_event.get("sender", {}).get("id")
            # postback (button template 버튼 클릭)
            if "postback" in msg_event:
                payload = msg_event["postback"].get("payload", "")
                if sender_id and payload == "CHECK_FOLLOW":
                    await _process_button_press(sender_id)
            # quick_reply (하위 호환)
            else:
                msg = msg_event.get("message", {})
                if "quick_reply" in msg:
                    payload = msg["quick_reply"].get("payload", "")
                    if sender_id and payload == "CHECK_FOLLOW":
                        await _process_button_press(sender_id)

    return {"status": "ok"}


async def _send_final_dm(user_id: str, rule: dict):
    dm_text = pick_message(rule["dm_message"])
    dm_url = rule.get("dm_url")
    dm_url_title = rule.get("dm_url_title", "자세히 보기")
    try:
        if dm_url:
            await api.send_dm_with_link(user_id, dm_text, dm_url, dm_url_title)
        else:
            await api.send_dm_to_user(user_id, dm_text)
        log.info("팔로워 확인 후 최종 DM 전송: %s", user_id)
    except Exception as e:
        log.error("최종 DM 전송 실패: %s", e)


async def _process_button_press(user_id: str):
    rules = _pending_follows.get(user_id)
    if not rules:
        log.info("버튼 클릭 — 대기 룰 없음: %s", user_id)
        return

    log.info("버튼 클릭 — DM 전송: %s", user_id)
    _pending_follows.pop(user_id, None)
    for rule in rules:
        await _send_final_dm(user_id, rule)


async def _process_comment(value: dict):
    comment_id = value.get("id")
    if comment_id in _processed:
        log.info("중복 이벤트 무시: %s", comment_id)
        return
    _processed.add(comment_id)

    # 대댓글(봇 답글 포함)은 무시 — 무한루프 방지
    if value.get("parent_id"):
        log.info("대댓글 무시: %s", comment_id)
        return

    comment_text = value.get("text", "")
    media_id = value.get("media", {}).get("id")
    username = value.get("from", {}).get("username", "unknown")
    user_id = value.get("from", {}).get("id")

    log.info("Comment from @%s on media %s: %s", username, media_id, comment_text)

    rules = load_rules()
    rule = find_matching_rule(comment_text, rules, media_id)
    if rule is None:
        log.info("No matching rule for comment")
        status = "no_rule" if not has_rule_for_media(media_id, rules) else "no_match"
        _log_activity(username=username, comment=comment_text, rule=None,
                      comment_reply=None, dm=None, status=status)
        if status == "no_rule":
            await _notify_telegram(
                f"📌 룰 없는 새 게시물 댓글\n"
                f"@{username}\n"
                f"media_id: {media_id}\n"
                f"댓글: {comment_text}"
            )
        return

    log.info("Matched rule: %s", rule.get("name"))
    reply_status = None
    dm_status = None

    if rule.get("comment_reply"):
        try:
            await api.reply_to_comment(comment_id, pick_message(rule["comment_reply"]))
            reply_status = "ok"
        except Exception as e:
            log.error("댓글 답글 실패: %s", e)
            reply_status = "fail"

    if comment_id:
        if rule.get("require_follow") and user_id:
            _pending_follows.setdefault(user_id, []).append(rule)
            try:
                await api.send_dm(
                    comment_id,
                    "정보 전송을 위해 팔로우 부탁드립니다! \n팔로우 하신 뒤 아래 버튼을 눌러주세요!😊",
                    quick_reply={"title": "정보 확인 🙌", "payload": "CHECK_FOLLOW"},
                )
                dm_status = "pending"
            except Exception as e:
                log.error("팔로우 확인 DM 전송 실패: %s", e)
                dm_status = "fail"
        elif rule.get("dm_message"):
            try:
                await api.send_dm(comment_id, pick_message(rule["dm_message"]))
                dm_status = "ok"
            except Exception as e:
                log.error("DM 전송 실패: %s", e)
                dm_status = "fail"

    _log_activity(username=username, comment=comment_text, rule=rule.get("name"),
                  comment_reply=reply_status, dm=dm_status, status="matched")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
