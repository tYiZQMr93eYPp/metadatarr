# metadatarr

Watches configured Telegram channels for new indexer announcements, parses the messages, looks up the torrents' metadata in the indexers' UNIT3D API, and publishes it through [Apprise](https://github.com/caronc/apprise-api).

## How it works

1. Listens for new messages on configured Telegram channels, group topics, and chats via Telethon
2. Looks up which indexer class handles that channel
3. Parses the message into structured `AnnounceData`
4. Searches the torrent through the indexer's `/api/torrents/filter` endpoint by title, and picks the match by `id` (or by uploader if the announce has no `id`)
5. Sends the metadata to `APPRISE_URL`, tagged with the indexer's class name (E.G. `TORRENTEROS`)

If the announce can't be parsed or no torrent matches, the error is logged and an alert is sent to `APPRISE_URL`, tagged with `APPRISE_ERROR_TAG`.

Every processed announce (raw message, parsed data, reply markup, outcome and the resolved torrent) is stored in a SQLite database for debugging, and purged after `DB_RETENTION_DAYS` (checked at startup and then once a day). After each successful match, a background check looks for earlier matches of the same torrent on the same indexer, and sends a `Duplicate match` alert (tagged with `APPRISE_ERROR_TAG`) if there are any.

## Requirements

- Python 3.14+
- A [Telegram API app](https://my.telegram.org/apps) (API ID + hash)
- An [Apprise API](https://github.com/caronc/apprise-api) instance

## Configuration

### Environment variables

| Variable | Description | Mandatory | Default value | Example |
|---|---|---|---|---|
| `TG_APP_API_ID` | Telegram app API ID | true | `None` | `13371337` |
| `TG_APP_API_HASH` | Telegram app API hash | true | `None` | `oyr2i1ngqk3oc0lhac5cpn0anvuta9qk` |
| `TG_SESSION_PATH` | Path to the Telethon session file | false | `/app/config/telethon.session` | `/app/config/telethon.session` |
| `INDEXER_CONFIG_PATH` | Path to the indexer config YAML | false | `/app/config/config.yaml` | `/app/config/config.yaml` |
| `LOG_LEVEL` | The logging level | false | `INFO` | `INFO` |
| `LOG_PATH` | The log file path | false | `None` | `/app/logs/metadatarr.log` |
| `APPRISE_URL` | [Apprise API](https://appriseit.com/services/apprise_api/) URL (including the config id). The `tags` parameter is added automatically, so don't include it. Notification timestamps use `TZ` (UTC if unset) | true | `None` | `apprise://apprise:8000/your-config-id` |
| `APPRISE_ERROR_TAG` | Tag of the error and duplicate-match alerts | false | `error` | `error` |
| `DB_PATH` | Path to the SQLite history database | false | `/app/config/metadatarr.db` | `/app/config/metadatarr.db` |
| `DB_RETENTION_DAYS` | Days the history records are kept before being purged | false | `30` | `30` |

### Indexer config (`config.yaml`)

Three sections map different Telegram source types to indexer class names:

```yaml
channel_indexers:
  # TG-CHANNEL-ID_MYINDEXER: MyIndexer
  "1234567890": MyIndexer

group_topic_indexers:
  # TG-GROUP-TOPIC-ID_MYINDEXER: MyIndexer
  "1234567890_1234": MyIndexer

chat_indexers:
  # TG-CHAT-ID_MYINDEXER: MyIndexer
  "1234567890": MyIndexer

```

The Apprise tag is derived from the class name: `MyIndexer` → `MyIndexer`.

#### `indexer_api`

Every mapped indexer needs an entry keyed by its class name. The app refuses to start otherwise.

```yaml
indexer_api:
  MyIndexer:
    url: https://tracker.example.org  # scheme + host, no path
    api_key: MY_API_KEY
    rate_limit: 15  # optional, max lookups per minute (default: 15)
```

Lookups beyond `rate_limit` are delayed, not dropped.

#### `logging.level`

Optional. `LOG_LEVEL` is the default level; this section overrides it per module or package, like Spring Boot's `logging.level.*`. Names are the Python module names shown in the logs (E.G. `indexers.emuwarez`, `clients.unit3d`, `telethon`, `__main__`), and the most specific match wins. Each indexer lives in its own module, so this is effectively per class.

```yaml
logging:
  level:
    indexers.emuwarez: DEBUG
    clients.unit3d: DEBUG
    telethon: WARNING
```

### Metadata message

One `key: [value]` line per field, sent as plain text. Fields the API doesn't report are left out, and `size` is formatted with binary units:

```
id: [1234]
name: [Some Movie 1988 1080p BluRay AAC 2.0 x264]
release_year: [1988]
category: [Movies]
type: [Encode]
resolution: [1080p]
size: [4.08 GiB]
freeleech: [25%]
double_upload: [false]
uploader: [AnonymousUploader]
tmdb_id: [2280]
details_link: [https://tracker.internal/torrents/13897]
```

## Running with Docker

> [!IMPORTANT]
> Place `config.yaml` and `telethon.session` in the named volume before starting, or authenticate locally first.

> [!IMPORTANT]
> On first run, Telethon will prompt for your phone number to authenticate.  
> The session is saved to `TG_SESSION_PATH`.

### Docker Compose (recommended)

```yaml
---
services:
  metadatarr:
    image: tYiZQMr93eYPp/metadatarr:latest
    container_name: metadatarr
    environment:
      TZ: #optional
      TG_APP_API_ID: 
      TG_APP_API_HASH: 
      APPRISE_URL: 
      APPRISE_ERROR_TAG: #optional
      DB_PATH: #optional
      DB_RETENTION_DAYS: #optional
      TG_SESSION_PATH: #optional
      INDEXER_CONFIG_PATH: #optional
      LOG_LEVEL: #optional
      LOG_PATH: #optional
    volumes:
      - /path/to/metadatarr_config:/app/config
      - /path/to/log_path:/app/logs/app.log # optional
    restart: unless-stopped
```

### Docker CLI

```bash
docker run -d \
  --name metadatarr \
  -e TZ= `#optional` \
  -e TG_APP_API_ID= \
  -e TG_APP_API_HASH= \
  -e APPRISE_URL= \
  -e APPRISE_ERROR_TAG= `#optional` \
  -e DB_PATH= `#optional` \
  -e DB_RETENTION_DAYS= `#optional` \
  -e TG_SESSION_PATH= `#optional` \
  -e INDEXER_CONFIG_PATH= `#optional` \
  -e LOG_LEVEL= `#optional` \
  -e LOG_PATH= `#optional` \
  -v /path/to/metadatarr_config:/app/config \
  -v /path/to/log_path:/app/logs/app.log `#optional` \
  tYiZQMr93eYPp/metadatarr:latest
```

## Included indexers

| Indexer List |
|---|
| `HDZERO` |
| `EMUWAREZ` |
| `NOBS` |
| `ParabellumHD` |
| `Milnueve` |
| `TORRENTEROS` |

## Project structure

```
src/
  main.py              # Entry point
  indexers/            # One file per indexer, filename = class name lowercase
    myindexer.py
  clients/
    unit3d.py          # UNIT3D API client (torrent lookup)
  models/
    announce_data.py   # Parsed announce data
    torrent.py         # Torrent metadata returned by the UNIT3D API
  notifications/
    apprise_notifier.py  # Metadata, error and duplicate-match notifications
  storage/
    history_store.py   # SQLite history of processed announces
  mappers/
    indexer_mapper.py  # Loads channel → indexer mapping and API settings from config.yaml
config.yaml            # Indexer mappings
```
