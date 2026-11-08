import json
import os
from datetime import datetime, timezone, tzinfo
from urllib.parse import quote
from zoneinfo import ZoneInfo

import apprise
from loguru import logger
from telethon import events

from models.announce_data import AnnounceData
from models.torrent import Torrent


def _resolve_tz() -> tzinfo:
    name = os.getenv("TZ")
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning("Invalid TZ {!r}, using UTC for notification timestamps", name)
        return timezone.utc


def _resolve_url() -> str | None:
    url = os.getenv("APPRISE_URL")
    if not url:
        return None
    if "overflow=" not in url:
        url += ("&" if "?" in url else "?") + "overflow=split"
    return url


_TZ = _resolve_tz()
_APPRISE_URL = _resolve_url()
_ERROR_TAG = os.getenv("APPRISE_ERROR_TAG") or "error"


def ensure_configured() -> None:
    if not _APPRISE_URL:
        raise RuntimeError("APPRISE_URL is required")


def _format_time(value: datetime | None) -> str | None:
    return value.astimezone(_TZ).isoformat(timespec="seconds") if value else None


def format_size(size: int) -> str:
    """Formats a size in bytes using binary units (B, KiB, MiB, GiB, TiB)."""
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            return f"{size} B" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TiB"


def _fence(content: str, lang: str = "") -> str:
    # Keep the payload from closing the fence early.
    return "```{}\n{}\n```".format(lang, content.replace("```", "'''"))


def _format_value(key: str, value: object) -> str:
    if key == "size":
        return format_size(value)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, datetime):
        return _format_time(value)
    return str(value)


def _send(tag: str, title: str, body: str, body_format: apprise.NotifyFormat, label: str) -> None:
    try:
        notifier = apprise.Apprise()
        # `tags` makes the Apprise API notify only the services with that tag
        url = "{}{}tags={}".format(_APPRISE_URL, "&" if "?" in _APPRISE_URL else "?", quote(tag))
        if not notifier.add(url):
            logger.error("Invalid APPRISE_URL, notification skipped")
            return
        if not notifier.notify(title=title, body=body, body_format=body_format):
            logger.error("Apprise notification failed for {}", label)
    except Exception:
        logger.exception("Apprise notification raised for {}", label)


def notify_metadata(indexer_name: str, torrent: Torrent) -> None:
    """Publishes the torrent's metadata as `key: [value]` lines, skipping the fields that are missing."""
    fields = {"id": torrent.id, **torrent.attributes.model_dump()}
    body = "\n".join(
        f"{key}: [{_format_value(key, value)}]"
        for key, value in fields.items()
        if value is not None and value != ""
    )
    _send(indexer_name, "[metadatarr] Metadata: {}\n".format(indexer_name), body,
          apprise.NotifyFormat.TEXT, indexer_name)


def notify_duplicate(indexer_name: str, torrent: Torrent, previous: list[dict]) -> None:
    """Alerts that `torrent` had already been matched on this indexer. `previous` holds its earlier records."""
    try:
        seen = "\n".join(
            "- `{}` (message {})".format(_format_time(datetime.fromisoformat(p["created_at"])), p["msg_id"])
            for p in previous[-10:]
        )
        sections = [
            "\u200b\n**Torrent:** {} (id `{}`)".format(torrent.attributes.name or "?", torrent.id),
            "**Matched before:** {} time(s)".format(len(previous)),
            "**Previous matches" + (" (last 10)" if len(previous) > 10 else "") + "**\n" + seen,
        ]
    except Exception:
        logger.exception("Building the duplicate notification raised for indexer {}", indexer_name)
        return

    _send(_ERROR_TAG, "[metadatarr] Duplicate match: {}\n".format(indexer_name), "\n\n".join(sections),
          apprise.NotifyFormat.MARKDOWN, indexer_name)


def notify_error(indexer_name: str, data: AnnounceData, reason: str, event: events.NewMessage.Event) -> None:
    try:
        fields = {k: v for k, v in vars(data).items() if k != "normalized_message"}
        # The first body line starts with a zero-width space (U+200B) to add spacing after the title in Telegram.
        sections = [
            "\u200b\n**Error:** {}".format(reason),
            "**Message date:** `{}`".format(_format_time(event.message.date)),
            "**Processed at:** `{}`".format(_format_time(datetime.now(timezone.utc))),
            "**AnnounceData**\n" + _fence(json.dumps(fields, ensure_ascii=False, indent=2, default=str), "json"),
            "**Normalized message**\n" + _fence(data.normalized_message or ""),
        ]
        markup = getattr(event.message, "reply_markup", None)
        if markup is not None and hasattr(markup, "to_dict"):
            sections.append("**Reply markup**\n" + _fence(json.dumps(markup.to_dict(), ensure_ascii=False, indent=2, default=str), "json"))
    except Exception:
        logger.exception("Building the error notification raised for indexer {}", indexer_name)
        return

    _send(_ERROR_TAG, "[metadatarr] Error: {}\n".format(indexer_name), "\n\n".join(sections),
          apprise.NotifyFormat.MARKDOWN, indexer_name)
