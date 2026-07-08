"""ReliefWeb disasters fetcher, RSS phase (FR-3).

The RSS feed needs no appname approval and carries the 20 most recent
disaster records: title, link, pubDate, and category elements holding the
affected countries and the GLIDE number. The API v2 client replaces this
module behind the same interface once the registered appname is approved;
nothing outside the fetcher changes.
"""

import urllib.request
import xml.etree.ElementTree as ET

from hadr.fetchers import FetchResult, TIMEOUT_SECONDS, USER_AGENT

RSS_URL = "https://reliefweb.int/disasters/rss.xml"


def fetch() -> FetchResult:
    try:
        request = urllib.request.Request(RSS_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            root = ET.fromstring(response.read())
        items = []
        for item in root.findall(".//item"):
            items.append({
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "pubdate": (item.findtext("pubDate") or "").strip(),
                "categories": [(c.text or "").strip() for c in item.findall("category")],
            })
        return FetchResult(ok=True, features=items)
    except Exception as exc:
        return FetchResult(ok=False, error="{}: {}".format(type(exc).__name__, exc))
