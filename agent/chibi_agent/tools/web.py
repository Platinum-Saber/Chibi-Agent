"""Open pages and searches in the default browser."""
from __future__ import annotations

import urllib.parse
import webbrowser

from . import Result, tool


@tool("open_url", "Open a web page in the browser.", {"url": ("The full URL", True)},
      side_effect=True, summary=lambda a: f"Open {a.get('url')}")
def open_url(url: str) -> Result:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return Result(f"Opened {url}.")


@tool("web_search", "Search the web or YouTube in the browser.",
      {"query": ("What to search for", True), "site": ("'web' (default) or 'youtube'", False)},
      side_effect=True, summary=lambda a: f"Search {a.get('site') or 'the web'} for '{a.get('query')}'")
def web_search(query: str, site: str = "web") -> Result:
    q = urllib.parse.quote_plus(query)
    url = (f"https://www.youtube.com/results?search_query={q}" if site.lower().startswith("you")
           else f"https://www.google.com/search?q={q}")
    webbrowser.open(url)
    return Result(f"Opened the search for '{query}'.")
