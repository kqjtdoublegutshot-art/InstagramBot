import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_IDS = {int(uid) for uid in os.environ["TELEGRAM_USER_IDS"].split(",")}
RULES_FILE = Path(__file__).parent / "rules.json"

NAME, MEDIA_ID, KEYWORDS, MIN_KEYWORDS, COMMENT_REPLY, DM_MESSAGE = range(6)
EDIT_RULE, EDIT_FIELD, EDIT_VALUE = range(6, 9)

FIELD_LABELS = {
    "name": "이름",
    "media_id": "media_id",
    "keywords": "키워드",
    "min_keywords": "min_keywords",
    "comment_reply": "댓글 답글",
    "dm_message": "DM 내용",
}


def load_rules() -> list[dict]:
    try:
        return json.loads(RULES_FILE.read_text(encoding="utf-8")).get("rules", [])
    except Exception:
        return []


def save_rules(rules: list[dict]):
    RULES_FILE.write_text(
        json.dumps({"rules": rules}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def auth(update: Update) -> bool:
    return update.effective_user.id in ALLOWED_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    await update.message.reply_text(
        "인스타 자동응답 봇 관리자예요 😊\n\n"
        "/rules — 현재 룰 목록\n"
        "/addrule — 새 룰 추가\n"
        "/editrule — 룰 수정\n"
        "/delrule — 룰 삭제\n"
        "/cancel — 진행 중인 작업 취소"
    )


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    rules = load_rules()
    if not rules:
        await update.message.reply_text("등록된 룰이 없어요.")
        return
    lines = []
    for i, rule in enumerate(rules, 1):
        keywords = ", ".join(rule.get("keywords", []))
        min_kw = rule.get("min_keywords", 1)
        media_id = rule.get("media_id") or "전체 게시물"
        replies = rule.get("comment_reply", [])
        reply_count = len(replies) if isinstance(replies, list) else 1
        lines.append(
            f"{i}. *{rule.get('name')}*\n"
            f"   📌 media\\_id: `{media_id}`\n"
            f"   🔑 키워드: {keywords} (최소 {min_kw}개)\n"
            f"   💬 댓글 답글: {reply_count}개\n"
            f"   📩 DM: {'있음' if rule.get('dm_message') else '없음'}"
        )
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# ── /addrule 대화 흐름 ──────────────────────────────────────

async def addrule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("룰 이름을 입력해주세요:")
    return NAME


async def addrule_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        "media_id를 입력해주세요.\n특정 게시물에만 적용하려면 ID를 입력하고,\n모든 게시물에 적용하려면 '-' 입력:"
    )
    return MEDIA_ID


async def addrule_media_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["media_id"] = "" if text == "-" else text
    await update.message.reply_text("키워드를 쉼표로 구분해서 입력해주세요:\n예: 에어컨청소, 에어컨 청소")
    return KEYWORDS


async def addrule_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keywords = [k.strip() for k in update.message.text.split(",") if k.strip()]
    context.user_data["keywords"] = keywords
    await update.message.reply_text(
        f"키워드 {len(keywords)}개 중 최소 몇 개가 포함되어야 반응할까요?\n"
        f"(1 = 하나만 있어도 반응, {len(keywords)} = 모두 있어야 반응)"
    )
    return MIN_KEYWORDS


async def addrule_min_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        min_kw = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("숫자로 입력해주세요.")
        return MIN_KEYWORDS
    context.user_data["min_keywords"] = min_kw
    await update.message.reply_text(
        "댓글 답글을 입력해주세요.\n여러 개면 줄바꿈으로 구분 (랜덤 선택됩니다):"
    )
    return COMMENT_REPLY


async def addrule_comment_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    replies = [r.strip() for r in update.message.text.split("\n") if r.strip()]
    context.user_data["comment_reply"] = replies if len(replies) > 1 else replies[0]
    await update.message.reply_text("DM 내용을 입력해주세요:\n(DM 없이 댓글만 달려면 '-' 입력)")
    return DM_MESSAGE


async def addrule_dm_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    dm = "" if text == "-" else text

    rule: dict = {"name": context.user_data["name"]}
    if context.user_data.get("media_id"):
        rule["media_id"] = context.user_data["media_id"]
    rule["keywords"] = context.user_data["keywords"]
    if context.user_data.get("min_keywords", 1) > 1:
        rule["min_keywords"] = context.user_data["min_keywords"]
    rule["comment_reply"] = context.user_data["comment_reply"]
    if dm:
        rule["dm_message"] = dm

    rules = load_rules()
    rules.append(rule)
    save_rules(rules)

    await update.message.reply_text(f"✅ '{rule['name']}' 룰이 추가됐어요!")
    return ConversationHandler.END


async def addrule_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("취소됐어요.")
    return ConversationHandler.END


# ── /editrule 대화 흐름 ─────────────────────────────────────

async def editrule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return ConversationHandler.END
    rules = load_rules()
    if not rules:
        await update.message.reply_text("수정할 룰이 없어요.")
        return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton(rule["name"], callback_data=f"erule_{i}")]
        for i, rule in enumerate(rules)
    ]
    keyboard.append([InlineKeyboardButton("취소", callback_data="erule_cancel")])
    await update.message.reply_text("수정할 룰을 선택해주세요:", reply_markup=InlineKeyboardMarkup(keyboard))
    return EDIT_RULE


async def editrule_select_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "erule_cancel":
        await query.edit_message_text("취소됐어요.")
        return ConversationHandler.END
    idx = int(query.data.split("_")[1])
    context.user_data["edit_idx"] = idx
    rules = load_rules()
    rule = rules[idx]
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"efield_{field}")]
        for field, label in FIELD_LABELS.items()
    ]
    keyboard.append([InlineKeyboardButton("취소", callback_data="efield_cancel")])
    await query.edit_message_text(
        f"*{rule['name']}* 의 어떤 항목을 수정할까요?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return EDIT_FIELD


async def editrule_select_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "efield_cancel":
        await query.edit_message_text("취소됐어요.")
        return ConversationHandler.END
    field = query.data.split("_", 1)[1]
    context.user_data["edit_field"] = field
    rules = load_rules()
    rule = rules[context.user_data["edit_idx"]]
    current = rule.get(field, "없음")
    hints = {
        "keywords": "쉼표로 구분해서 입력 (예: 에어컨청소, 에어컨 청소)",
        "min_keywords": "숫자로 입력",
        "comment_reply": "줄바꿈으로 구분하면 랜덤 선택",
        "media_id": "없애려면 '-' 입력",
        "dm_message": "없애려면 '-' 입력",
    }
    hint = f"\n💡 {hints[field]}" if field in hints else ""
    await query.edit_message_text(
        f"현재 *{FIELD_LABELS[field]}*: `{current}`\n\n새 값을 입력해주세요:{hint}",
        parse_mode="Markdown",
    )
    return EDIT_VALUE


async def editrule_save_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    field = context.user_data["edit_field"]
    idx = context.user_data["edit_idx"]
    rules = load_rules()

    if field == "keywords":
        value = [k.strip() for k in text.split(",") if k.strip()]
    elif field == "min_keywords":
        try:
            value = int(text)
        except ValueError:
            await update.message.reply_text("숫자로 입력해주세요.")
            return EDIT_VALUE
    elif field == "comment_reply":
        parts = [r.strip() for r in text.split("\n") if r.strip()]
        value = parts if len(parts) > 1 else parts[0]
    elif field in ("media_id", "dm_message"):
        value = "" if text == "-" else text
    else:
        value = text

    if value == "" and field in ("media_id", "dm_message"):
        rules[idx].pop(field, None)
    else:
        rules[idx][field] = value

    save_rules(rules)
    await update.message.reply_text(f"✅ *{FIELD_LABELS[field]}* 수정됐어요!", parse_mode="Markdown")
    return ConversationHandler.END


async def editrule_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):  # noqa: ARG001
    await update.message.reply_text("취소됐어요.")
    return ConversationHandler.END


# ── /delrule ────────────────────────────────────────────────

async def cmd_delrule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    rules = load_rules()
    if not rules:
        await update.message.reply_text("삭제할 룰이 없어요.")
        return
    keyboard = [
        [InlineKeyboardButton(rule["name"], callback_data=f"del_{i}")]
        for i, rule in enumerate(rules)
    ]
    keyboard.append([InlineKeyboardButton("취소", callback_data="del_cancel")])
    await update.message.reply_text("삭제할 룰을 선택해주세요:", reply_markup=InlineKeyboardMarkup(keyboard))


async def delrule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "del_cancel":
        await query.edit_message_text("취소됐어요.")
        return
    idx = int(query.data.split("_")[1])
    rules = load_rules()
    if idx >= len(rules):
        await query.edit_message_text("룰을 찾을 수 없어요.")
        return
    deleted = rules.pop(idx)
    save_rules(rules)
    await query.edit_message_text(f"✅ '{deleted['name']}' 룰이 삭제됐어요.")


# ── 진입점 ──────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("delrule", cmd_delrule))
    app.add_handler(CallbackQueryHandler(delrule_callback, pattern="^del_"))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("editrule", editrule_start)],
        states={
            EDIT_RULE: [CallbackQueryHandler(editrule_select_rule, pattern="^erule_")],
            EDIT_FIELD: [CallbackQueryHandler(editrule_select_field, pattern="^efield_")],
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, editrule_save_value)],
        },
        fallbacks=[CommandHandler("cancel", editrule_cancel)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("addrule", addrule_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addrule_name)],
            MEDIA_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, addrule_media_id)],
            KEYWORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, addrule_keywords)],
            MIN_KEYWORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, addrule_min_keywords)],
            COMMENT_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, addrule_comment_reply)],
            DM_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addrule_dm_message)],
        },
        fallbacks=[CommandHandler("cancel", addrule_cancel)],
    ))

    log.info("텔레그램 봇 시작")
    app.run_polling()


if __name__ == "__main__":
    main()
