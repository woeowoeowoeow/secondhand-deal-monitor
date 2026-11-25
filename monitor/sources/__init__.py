"""Source registry. Add a new marketplace by writing a Source subclass and listing it here."""
from .ebay import EbaySource
from .email_intake import EmailIntakeSource
from .facebook import FacebookSource
from .reddit import RedditSource

ALL = [EbaySource, EmailIntakeSource, RedditSource, FacebookSource]
