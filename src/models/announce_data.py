from dataclasses import dataclass

# Without a title, the torrent can't be looked up through the indexer's API
_REQUIRED_FIELDS = ("title",)


@dataclass
class AnnounceData:
    """What an indexer's announce message says about a torrent."""

    title: str | None = None
    category: str | None = None
    size: str | None = None
    uploader: str | None = None
    freeleech: str | None = None
    featured: str | None = None
    base_url: str | None = None
    id: str | None = None
    normalized_message: str | None = None

    def missing_fields(self) -> list[str]:
        return [name for name in _REQUIRED_FIELDS if not getattr(self, name)]
