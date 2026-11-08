import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger
from telethon import TelegramClient, events, custom
from log_config import LogConfig
from mappers.indexer_mapper import IndexerMapper
from notifications.apprise_notifier import ensure_configured, notify_duplicate, notify_error, notify_metadata
from storage.history_store import HistoryStore


load_dotenv()
LogConfig().configure()
ensure_configured()

telethon_session = Path(os.getenv("TG_SESSION_PATH", "/app/config/telethon.session"))
api_id = int(os.getenv("TG_APP_API_ID"))
api_hash = os.getenv("TG_APP_API_HASH")
client = TelegramClient(telethon_session, api_id, api_hash)

indexer_mapper = IndexerMapper(os.getenv("INDEXER_CONFIG_PATH", "/app/config/config.yaml"))
history = HistoryStore.from_env()
_background: set[asyncio.Task] = set()


def _record(indexer: type, message_ent: custom.Message, channel_id: int | None, chat_id: int | None, data, outcome: str, torrent=None) -> int | None:
    markup = message_ent.reply_markup
    return history.record(
        indexer.__name__, outcome,
        channel_id=channel_id, chat_id=chat_id, msg_id=message_ent.id,
        raw_message=message_ent.text, announce=vars(data),
        reply_markup=markup.to_dict() if markup else None,
        torrent_id=torrent.id if torrent else None,
        torrent=torrent.model_dump(mode="json") if torrent else None,
    )


async def _alert_if_repeated(indexer_name: str, torrent, record_id: int) -> None:
    try:
        previous = await asyncio.to_thread(history.previous_matches, indexer_name, torrent.id, record_id)
        if previous:
            logger.info("Torrent {} was already matched {} time(s) | indexer={}", torrent.id, len(previous), indexer_name)
            await asyncio.to_thread(notify_duplicate, indexer_name, torrent, previous)
    except Exception:
        logger.exception("Duplicate check failed | indexer={} | torrent_id={}", indexer_name, torrent.id)


@client.on(events.NewMessage)
async def read_messages(event: events.NewMessage.Event):
    message_ent: custom.Message = event.message

    channel_id: int | None = getattr(message_ent.peer_id, "channel_id", None)
    chat_id: int | None = getattr(message_ent, "chat_id", None)

    logger.debug("New message | peer_id={} | channel_id={} | chat_id={} | msg_id={}", message_ent.peer_id, channel_id, chat_id, message_ent.id)

    if channel_id is not None:
        reply_to = message_ent.reply_to
        is_topic = reply_to is not None and getattr(reply_to, "forum_topic", False)

        if is_topic:
            topic_id: int = reply_to.reply_to_top_id or reply_to.reply_to_msg_id
            indexer = indexer_mapper.get_topic(channel_id, topic_id)
            logger.debug("Topic lookup: group_id={}, topic_id={} -> {}", channel_id, topic_id, indexer)
        else:
            indexer = indexer_mapper.get(channel_id)
            logger.debug("Channel lookup: channel_id={} -> {}", channel_id, indexer)
    elif chat_id is not None:
        indexer = indexer_mapper.get_chat(chat_id)
        logger.debug("Chat lookup: chat_id={} -> {}", chat_id, indexer)
    else:
        logger.debug("No channel_id or chat_id, skipping")
        return

    if indexer is None:
        logger.debug("No indexer found for message, skipping")
        return

    logger.debug("Indexer matched: {}", indexer)
    logger.debug("reply_markup | indexer={} | msg_id={} | {}", indexer.__name__, message_ent.id,
                message_ent.reply_markup.to_dict() if message_ent.reply_markup else None)

    # The parser and the API lookup run off the event loop, as the latter does blocking HTTP calls
    data = await asyncio.to_thread(indexer().parse_event, event)

    missing = data.missing_fields()
    if missing:
        logger.error("Missing fields {} | indexer={} | msg_id={}", missing, indexer.__name__, message_ent.id)
        reason = "Missing fields: {}".format(", ".join("`{}`".format(m) for m in missing))
        await asyncio.to_thread(_record, indexer, message_ent, channel_id, chat_id, data, "missing_fields")
        await asyncio.to_thread(notify_error, indexer.__name__, data, reason, event)
        return

    torrent = await asyncio.to_thread(indexer_mapper.api(indexer).find_torrent, data)
    if torrent is None:
        logger.error("No matching torrent found | indexer={} | msg_id={} | title={!r} | id={}",
                     indexer.__name__, message_ent.id, data.title, data.id)
        await asyncio.to_thread(_record, indexer, message_ent, channel_id, chat_id, data, "no_match")
        await asyncio.to_thread(notify_error, indexer.__name__, data, "No matching torrent found", event)
        return

    logger.debug("Torrent resolved through the API: {}", torrent)
    await asyncio.to_thread(notify_metadata, indexer.__name__, torrent)

    record_id = await asyncio.to_thread(_record, indexer, message_ent, channel_id, chat_id, data, "matched", torrent)
    if record_id is not None:
        # Runs in the background so it never delays the next announce
        task = asyncio.create_task(_alert_if_repeated(indexer.__name__, torrent, record_id))
        _background.add(task)
        task.add_done_callback(_background.discard)


if __name__ == "__main__":
    client.start()
    purge_task = client.loop.create_task(history.purge_periodically())
    _background.add(purge_task)
    client.run_until_disconnected()
