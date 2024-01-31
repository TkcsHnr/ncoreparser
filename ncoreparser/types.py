from dataclasses import dataclass
from ncoreparser.torrent import Torrent


@dataclass
class SearchResults:
    torrents: list[Torrent]
    page_count: int