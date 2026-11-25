"""Source registry. Add a new marketplace by writing a Source subclass and listing it here."""
from .ebay import EbaySource
from .facebook import FacebookSource
from .reddit import RedditSource

ALL = [EbaySource, RedditSource, FacebookSource]
