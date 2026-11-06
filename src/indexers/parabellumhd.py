import re
import unicodedata
from loguru import logger
from models.announce_data import AnnounceData
from telethon import events


_FIELDS = {
    "title": r"🎬\s\*\*(.+?)\s?(?:\*\*)",
    "category": r"Categor.a:\*\*\s#?(.+?)(?:\n|$)",
    "size": r"Tama.o:\*\*\s(.+?)(?:\n|$)",
    "uploader": r"Subido\spor:\*\*\s#?(.+?)(?:\n|$)",
    "base_url": r"\[Ver\sDetalles\sdel\sTorrent\]\((https?://.+?)\)",
    "id": r"/torrents/(\d+?)\)",
    # ParabellumHD doesn't announce the `Double Upload`, `Freeleech`, `Featured`, and `Refundable` values
}


def _get(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None

class PARABELLUMHD:
    @staticmethod
    def parse_event(event: events.NewMessage.Event) -> AnnounceData:
        message: str = unicodedata.normalize('NFKC', event.message.text)
        logger.debug("Raw message: {!r}", event.message.text)
        logger.debug("Normalized message: {!r}", message)
        data = {key: _get(pat, message) for key, pat in _FIELDS.items()}
        logger.debug("Parsed fields: {}", data)

        obj = AnnounceData(**data, normalized_message=message)
        logger.debug("Parsed data: {}", vars(obj))

        return obj
