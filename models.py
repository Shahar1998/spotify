from dataclasses import asdict, dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Song:
    """Typed representation of a song used by SpotiWord."""

    track_name: str
    artist: str
    spotify_url: str
    lyrics: str
    has_real_lyrics: bool
    album_art_url: Optional[str] = None
    spotify_uri: Optional[str] = None
    genres: Tuple[str, ...] = ()
    release_year: Optional[int] = None

    def to_record(self):
        """Return the legacy record shape used by the current DataFrame layer."""
        return {
            'Track Name': self.track_name,
            'Artist': self.artist,
            'Spotify URL': self.spotify_url,
            'Lyrics': self.lyrics,
            'Has Real Lyrics': self.has_real_lyrics,
            'Album Art URL': self.album_art_url or '',
            'Spotify URI': self.spotify_uri or '',
            'Genres': ', '.join(self.genres),
            'Release Year': self.release_year or '',
        }

    def as_dict(self):
        """Return a Python-friendly representation for future GUI use."""
        return asdict(self)
