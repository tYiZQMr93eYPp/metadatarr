from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# UNIT3D may report `0` for an id it doesn't have
_ZERO_IS_NULL = ("tmdb_id", "imdb_id", "tvdb_id", "mal_id", "igdb_id",
                 "category_id", "type_id", "resolution_id", "distributor_id", "region_id")
# Optional text labels normalised to "" when missing or null
_NONE_IS_EMPTY = ("resolution",)


class TorrentAttributes(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    release_year: int | None = None
    category: str | None = None
    type: str | None = None
    resolution: str = ""
    distributor: str | None = None
    region: str | None = None
    size: int | None = None  # bytes
    freeleech: str | None = None
    double_upload: bool | None = None
    refundable: bool | None = None
    internal: bool | None = None
    featured: bool | None = None
    personal_release: bool | None = None
    uploader: str | None = None
    tmdb_id: int | None = None
    imdb_id: int | None = None
    tvdb_id: int | None = None
    mal_id: int | None = None
    igdb_id: int | None = None
    isbn13: str | None = None
    asin: str | None = None
    category_id: int | None = None
    type_id: int | None = None
    resolution_id: int | None = None
    distributor_id: int | None = None
    region_id: int | None = None
    created_at: datetime | None = None
    details_link: str | None = None

    @field_validator(*_ZERO_IS_NULL, mode="before")
    @classmethod
    def _zero_to_none(cls, value: object) -> object:
        return None if value in (0, "0") else value

    @field_validator(*_NONE_IS_EMPTY, mode="before")
    @classmethod
    def _none_to_empty(cls, value: object) -> object:
        return "" if value is None else value


class Torrent(BaseModel):
    """A torrent resource returned by the UNIT3D `/api/torrents/filter` endpoint."""

    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    id: str
    attributes: TorrentAttributes = Field(default_factory=TorrentAttributes)

    @field_validator("id", mode="before")
    @classmethod
    def _stringify_id(cls, value: object) -> str:
        if value is None:
            raise ValueError("torrent id is required")
        return str(value)
