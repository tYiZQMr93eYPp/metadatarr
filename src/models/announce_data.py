from dataclasses import dataclass


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
        # Without a title or an id, the torrent can't be looked up through the indexer's API
        return [] if self.title or self.id else ["title or id"]
