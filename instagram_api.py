import logging

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://graph.instagram.com/v25.0"


class InstagramAPI:
    def __init__(self, access_token: str, instagram_user_id: str | None = None):
        self._token = access_token
        self._instagram_user_id = instagram_user_id
        self._client = httpx.AsyncClient(timeout=10.0)

    async def _get_instagram_user_id(self) -> str:
        if self._instagram_user_id:
            return self._instagram_user_id

        resp = await self._client.get(
            f"{BASE_URL}/me",
            params={"fields": "id", "access_token": self._token},
        )
        if not resp.is_success:
            log.error("Instagram user lookup failed: %s", resp.text)
        resp.raise_for_status()

        self._instagram_user_id = resp.json()["id"]
        log.info("Resolved Instagram user id for messages endpoint")
        return self._instagram_user_id

    async def _messages_url(self) -> str:
        ig_user_id = await self._get_instagram_user_id()
        return f"{BASE_URL}/{ig_user_id}/messages"

    async def reply_to_comment(self, comment_id: str, message: str) -> dict:
        url = f"{BASE_URL}/{comment_id}/replies"
        resp = await self._client.post(url, params={
            "message": message,
            "access_token": self._token,
        })
        resp.raise_for_status()
        log.info("Replied to comment %s", comment_id)
        return resp.json()

    async def send_dm(self, comment_id: str, message: str, quick_reply: dict = None) -> dict:
        url = await self._messages_url()
        if quick_reply:
            msg = {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": message,
                        "buttons": [{
                            "type": "postback",
                            "title": quick_reply["title"],
                            "payload": quick_reply["payload"],
                        }],
                    },
                }
            }
        else:
            msg = {"text": message}
        resp = await self._client.post(
            url,
            params={"access_token": self._token},
            json={
                "recipient": {"comment_id": comment_id},
                "message": msg,
            },
        )
        if not resp.is_success:
            log.error("DM API 오류 응답: %s", resp.text)
        resp.raise_for_status()
        log.info("DM sent via comment %s", comment_id)
        return resp.json()

    async def send_dm_to_user(self, user_id: str, message: str, quick_reply: dict = None) -> dict:
        url = await self._messages_url()
        if quick_reply:
            msg = {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": message,
                        "buttons": [{
                            "type": "postback",
                            "title": quick_reply["title"],
                            "payload": quick_reply["payload"],
                        }],
                    },
                }
            }
        else:
            msg = {"text": message}
        resp = await self._client.post(
            url,
            params={"access_token": self._token},
            json={
                "recipient": {"id": user_id},
                "message": msg,
            },
        )
        if not resp.is_success:
            log.error("DM to user API 오류 응답: %s", resp.text)
        resp.raise_for_status()
        log.info("DM sent to user %s", user_id)
        return resp.json()

    async def send_dm_with_link(self, user_id: str, text: str, url: str, url_title: str) -> dict:
        api_url = await self._messages_url()
        resp = await self._client.post(
            api_url,
            params={"access_token": self._token},
            json={
                "recipient": {"id": user_id},
                "message": {
                    "attachment": {
                        "type": "template",
                        "payload": {
                            "template_type": "button",
                            "text": text,
                            "buttons": [{
                                "type": "web_url",
                                "url": url,
                                "title": url_title,
                            }],
                        },
                    }
                },
            },
        )
        if not resp.is_success:
            log.error("DM with link API 오류 응답: %s", resp.text)
        resp.raise_for_status()
        log.info("DM with link sent to user %s", user_id)
        return resp.json()

    async def aclose(self):
        await self._client.aclose()
