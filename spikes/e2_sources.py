"""Fetch at most five real records per public source and save allowlisted metadata."""

import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from common import Result, save, standalone


AGENT = "ViralContentHunterSpike/0.1 (one-shot public-source feasibility check)"
MAX_BODY = 3 * 1024 * 1024
HN = "https://hacker-news.firebaseio.com/v0/"
WIKI = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/"
CHANNEL = "UCLA_DiR1FfKNvjuUpBHmylQ"  # NASA
TIKTOK_VIDEO = "https://www.tiktok.com/@scout2015/video/6718335390845095173"
DOUYIN_VIDEO = "https://www.douyin.com/video/7262247783225837603"
WEIBO = "https://s.weibo.com/top/summary?cate=realtimehot"
REDDIT = "https://www.reddit.com/r/popular/hot.json?limit=5"
CHALLENGE = re.compile(r"<title[^>]*>[^<]*(?:captcha|just a moment|access denied|"
                       r"verify|sign in|log in|visitor system|安全验证|访问受限|访问异常|请登录)|"
                       r"cf-chl-|/captcha/verify|访问频次过高", re.I)


class StopProbe(Exception):
    def __init__(self, message, verdict="BLOCKED"):
        super().__init__(message)
        self.verdict = verdict


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def public_url(value, query_keys=()):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if url.scheme in {"http", "https"} and url.hostname and not (url.username or url.password):
            query = urlencode([(key, val) for key, val in parse_qsl(url.query) if key in query_keys])
            return urlunsplit((url.scheme, url.netloc, url.path, query, ""))
    except ValueError:
        pass
    return None


def fetch(url, attempts, missing_ok=False):
    record = {"endpoint": url, "http_status": None}
    attempts.append(record)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        try:
            response = opener.open(Request(url, headers={"User-Agent": AGENT}), timeout=7)
        except HTTPError as exc:
            response = exc
        with response:
            status = record["http_status"] = response.code
            for key in ("Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
                value = response.headers.get(key, "")
                if value and re.fullmatch(r"[0-9A-Za-z., :+-]{1,70}", value):
                    record[key] = value
            if status in {401, 403, 407, 429, 451, 503} or "Retry-After" in record:
                raise StopProbe(f"HTTP {status} or server backoff. No retry attempted.")
            if status == 404 and missing_ok and record.get("X-RateLimit-Remaining") != "0":
                return None
            if 300 <= status < 400:
                target = response.headers.get("Location", "")
                path = urlsplit(target).path.casefold()
                record["redirect_kind"] = ("login/challenge" if any(word in path for word in
                                           ("login", "signin", "passport", "captcha", "verify"))
                                           else "other redirect")
                raise StopProbe(f"HTTP {status} {record['redirect_kind']}; redirect left unfollowed.")
            if status != 200:
                raise StopProbe(f"HTTP {status} returned no usable records.", "FAIL")
            content = response.read(MAX_BODY + 1)
            if len(content) > MAX_BODY:
                raise StopProbe("Response exceeded the 3 MiB evidence budget.", "FAIL")
            if "text/html" in response.headers.get("Content-Type", "").lower() and CHALLENGE.search(
                    content.decode("utf-8", errors="replace")[:200_000]):
                raise StopProbe("HTTP 200 page contained a login or challenge signal.")
            if record.get("X-RateLimit-Remaining") == "0":
                record["stop_after_response"] = True
            return content
    except URLError as exc:
        reason = exc.reason
        code = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
        record["transport_error"] = f"{type(reason).__name__}" + (f" ({code})" if code else "")
        raise StopProbe(f"No HTTP response: {record['transport_error']}.") from None
    except (OSError, TimeoutError) as exc:
        record["transport_error"] = type(exc).__name__
        raise StopProbe(f"HTTP exchange failed: {type(exc).__name__}.") from None


def metadata(title, url, **fields):
    if not isinstance(title, str) or not title.strip() or not url:
        return None
    return {"title": title.strip()[:350], "url": url,
            **{key: value for key, value in fields.items() if value is not None}}


def hacker_news(attempts):
    top = json.loads(fetch(HN + "topstories.json", attempts))
    for item_id in top[:3]:
        if attempts[-1].get("stop_after_response"):
            break
        item = json.loads(fetch(f"{HN}item/{int(item_id)}.json", attempts))
        if item and item.get("type") == "story" and not (item.get("deleted") or item.get("dead")):
            discussion = f"https://news.ycombinator.com/item?id={int(item['id'])}"
            timestamp = item.get("time")
            yield metadata(item.get("title"), discussion, article_url=public_url(item.get("url")),
                           score=item.get("score"), comments=item.get("descendants"),
                           published_at=datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp else None)


def check_robots(url, attempts, known_denied=False):
    parts = urlsplit(url)
    robots = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        body = fetch(robots, attempts, missing_ok=True)
    except StopProbe as exc:
        if known_denied:
            raise StopProbe(f"Published robots policy disallows this path. Local robots check: {exc}") from None
        raise
    if attempts[-1].get("stop_after_response"):
        raise StopProbe("Rate-limit remaining is zero on robots.txt response.")
    if known_denied:
        raise StopProbe("Published robots policy disallows this path. Content was skipped.")
    if body is None:
        return

    # These probes identify as ViralContentHunterSpike. Parse wildcard rules and any matching
    # exact agent group, with longest-rule precedence and Allow winning equal-length matches.
    groups = {"*": [], "viralcontenthunterspike": []}
    agents = []
    in_rules = False
    for line in body.decode("utf-8-sig", errors="replace").splitlines():
        key, _, value = line.split("#", 1)[0].partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                agents = []
                in_rules = False
            agents.append(value.lower())
        elif key in {"allow", "disallow"}:
            in_rules = True
            for agent in groups.keys() & set(agents):
                groups[agent].append((key, value))
    target = parts.path + ("?" + parts.query if parts.query else "")
    matches = [(len(rule), key == "allow") for key, rule in
               (groups["viralcontenthunterspike"] or groups["*"]) if rule and
               re.match(re.escape(rule.removesuffix("$")).replace(r"\*", ".*") +
                        ("$" if rule.endswith("$") else ""), target)]
    if matches and not max(matches)[1]:
        raise StopProbe("robots.txt disallows this path. Content was skipped.")


def reddit(attempts):
    check_robots(REDDIT, attempts, known_denied=True)
    return []


def youtube(attempts):
    feed = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={CHANNEL}"
    body = fetch(feed, attempts, missing_ok=True)
    if body is None:
        page = f"https://www.youtube.com/channel/{CHANNEL}/videos"
        check_robots(page, attempts)
        return youtube_page(fetch(page, attempts))
    ns = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/"}
    items = []
    for entry in ET.fromstring(body).findall("a:entry", ns)[:5]:
        link = entry.find("a:link[@rel='alternate']", ns)
        stats = entry.find("m:group/m:community/m:statistics", ns)
        rating = entry.find("m:group/m:community/m:starRating", ns)
        items.append(metadata(entry.findtext("a:title", namespaces=ns),
                              public_url(link.get("href"), ("v",)) if link is not None else None,
                              published_at=entry.findtext("a:published", namespaces=ns),
                              views=stats.get("views") if stats is not None else None,
                              rating_count=rating.get("count") if rating is not None else None))
    return items


def youtube_page(body):
    page = body.decode("utf-8", errors="replace")
    marker = re.search(r"\b(?:var\s+ytInitialData|window\[\"ytInitialData\"\])\s*=\s*", page)
    if not marker:
        return []
    root, _ = json.JSONDecoder().raw_decode(page[marker.end():])
    pending = [root]
    items = {}
    while pending and len(items) < 5:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(reversed(node))
        if not isinstance(node, dict):
            continue
        video = node.get("videoRenderer") or node.get("lockupViewModel")
        if isinstance(video, dict):
            video_id = video.get("videoId") or video.get("contentId", "")
            title = "".join(run.get("text", "") for run in video.get("title", {}).get("runs", []))
            lockup = video.get("metadata", {}).get("lockupMetadataViewModel", {})
            title = title or lockup.get("title", {}).get("content")
            if (re.fullmatch(r"[\w-]{11}", video_id) and
                    video.get("contentType", "LOCKUP_CONTENT_TYPE_VIDEO") == "LOCKUP_CONTENT_TYPE_VIDEO"):
                item = metadata(title, f"https://www.youtube.com/watch?v={video_id}",
                                published_relative=video.get("publishedTimeText", {}).get("simpleText"),
                                views_label=video.get("viewCountText", {}).get("simpleText"))
                if item:
                    items[video_id] = item
        pending.extend(reversed(list(node.values())))
    return list(items.values())


def trends(attempts):
    url = "https://trends.google.com/trending/rss?geo=VN"
    channel = ET.fromstring(fetch(url, attempts)).find("channel")
    if channel is None:
        return []
    items = []
    for item in channel.findall("item")[:5]:
        fields = {node.tag.split("}")[-1]: node for node in item}
        article = fields.get("news_item")
        article_url = next((node.text for node in article if node.tag.endswith("}news_item_url")), None) if article is not None else None
        title = item.findtext("title")
        traffic = fields.get("approx_traffic")
        link = public_url(article_url) or (
            "https://trends.google.com/trends/explore?" + urlencode({"geo": "VN", "q": title}) if title else None)
        items.append(metadata(title, link, published_at=item.findtext("pubDate"),
                              search_traffic_label=traffic.text if traffic is not None else None))
    return items


def wikipedia(attempts):
    day = datetime.now(UTC).date() - timedelta(days=2)
    body = fetch(WIKI + day.strftime("%Y/%m/%d"), attempts, missing_ok=True)
    if body is None:
        day -= timedelta(days=1)
        body = fetch(WIKI + day.strftime("%Y/%m/%d"), attempts)
    chart = json.loads(body)["items"][0]
    return [metadata(item["article"].replace("_", " "),
                     "https://en.wikipedia.org/wiki/" + quote(item["article"], safe=""),
                     views=item["views"], rank=item["rank"], pageviews_date=day.isoformat())
            for item in chart["articles"] if item["article"] != "Main_Page" and ":" not in item["article"]][:5]


class PublicHTML(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.meta = {}
        self.anchors = []
        self.anchor = None
        self.feed(body.decode("utf-8", errors="replace"))

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "meta":
            self.meta[fields.get("property") or fields.get("name")] = fields.get("content")
        elif tag == "a":
            self.anchor = (fields.get("href") or "", [])

    def handle_data(self, data):
        if self.anchor:
            self.anchor[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor:
            href, parts = self.anchor
            self.anchors.append((href, " ".join("".join(parts).split())))
            self.anchor = None


def weibo(attempts):
    check_robots(WEIBO, attempts)
    html = PublicHTML(fetch(WEIBO, attempts))
    items = {}
    for href, title in html.anchors:
        if href.startswith("/weibo?q=") and title:
            link = public_url("https://s.weibo.com" + href, ("q",))
            if link:
                items.setdefault(link, metadata(title, link))
        if len(items) == 5:
            break
    return list(items.values())


def tiktok(attempts):
    url = "https://www.tiktok.com/oembed?" + urlencode({"url": TIKTOK_VIDEO})
    data = json.loads(fetch(url, attempts))
    if data.get("type") == "video" and data.get("provider_name", "").lower() == "tiktok":
        title = data.get("title")
        if title:
            return [metadata(title, TIKTOK_VIDEO, creator=data.get("author_name"))]
        # The current documented oEmbed response may contain only a provider and video ID.
        match = data.get("embed_product_id")
        if str(match) == TIKTOK_VIDEO.rsplit("/", 1)[-1]:
            return [{"url": TIKTOK_VIDEO, "video_id": str(match), "provider": "TikTok", "title": None}]
    return []


def douyin(attempts):
    check_robots(DOUYIN_VIDEO, attempts)
    html = PublicHTML(fetch(DOUYIN_VIDEO, attempts))
    title = html.meta.get("og:title") or html.meta.get("twitter:title")
    if title and title.strip() not in {"抖音", "抖音 - 记录美好生活"} and (
            html.meta.get("og:type", "").startswith("video") or html.meta.get("og:url") == DOUYIN_VIDEO):
        return [metadata(title, DOUYIN_VIDEO, published_at=html.meta.get("article:published_time"))]
    return []


SOURCES = [
    ("Hacker News", hacker_news, HN + "topstories.json", "[Official Firebase API](https://github.com/HackerNews/API), which documents no current rate limit. Score is an HN score, and views are unavailable."),
    ("Reddit", reddit, REDDIT, "[Robots rules](https://www.reddit.com/robots.txt) disallow JSON paths. [Developer access terms](https://redditinc.com/policies/data-api-terms) apply."),
    ("YouTube", youtube, f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={CHANNEL}", "[Official push topic](https://developers.google.com/youtube/data/guides/push_notifications) and [robots rules](https://www.youtube.com/robots.txt). The older /feeds/videos.xml crawl path is disallowed. One channel gives targeted coverage."),
    ("Google Trends", trends, "https://trends.google.com/trending/rss?geo=VN", "[Trending Now](https://trends.google.com/trending?geo=VN) and [export guidance](https://support.google.com/trends/answer/4365538). Traffic labels refer to searches and can be approximate."),
    ("Wikimedia", wikipedia, WIKI + "YYYY/MM/DD", "[Analytics API access policy](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/access-policy.html), including identification, rate limits and CC0. Views represent the daily window."),
    ("Weibo", weibo, WEIBO, "Public hot-search page only, gated by [robots.txt](https://s.weibo.com/robots.txt). No documented anonymous hot-search API was assumed."),
    ("TikTok", tiktok, "https://www.tiktok.com/oembed?" + urlencode({"url": TIKTOK_VIDEO}), "[Documented oEmbed](https://developers.tiktok.com/docs/en/embed-videos) for one known video URL. The documentation announces deprecation. oEmbed has no discovery, publish time or engagement guarantee."),
    ("Douyin", douyin, DOUYIN_VIDEO, "One public video page gated by [robots.txt](https://www.douyin.com/robots.txt). The [developer hot-search API](https://open.douyin.com/platform/resource/docs/openapi/data-open-service/hot-video-data/get-ascending-words/) requires authorization and was left untouched."),
]


def probe(source):
    name, reader, target, policy = source
    attempts, items = [], []
    try:
        for item in reader(attempts):
            if item and item.get("url"):
                items.append(item)
            if len(items) == 5:
                break
        verdict = "PASS" if items else "FAIL"
        note = "Usable public metadata returned." if items else "No usable items parsed from the response."
    except StopProbe as exc:
        verdict = "PASS" if items else exc.verdict
        note = str(exc)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, ET.ParseError) as exc:
        verdict = "PASS" if items else "FAIL"
        note = f"Unexpected response format ({type(exc).__name__})."
    rate = [f"{key}={entry[key]}" for entry in attempts
            for key in ("Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")
            if key in entry]
    throttled = any(entry["http_status"] == 429 for entry in attempts)
    rate_note = ", ".join(rate) or ("HTTP 429 observed" if throttled else
                "No 429 or rate headers observed" if any(entry["http_status"] for entry in attempts)
                else "Rate behavior unverified")
    filename = "e2_" + name.lower().replace(" ", "_") + ".json"
    save(filename, {"source": name, "verdict": verdict, "target": target, "requests": attempts,
                    "note": note, "rate_limit": rate_note, "policy": policy, "items": items})
    status = ", ".join(str(entry["http_status"] or "unavailable") for entry in attempts) or "not requested"
    recommendation = "Build this connector first." if verdict == "PASS" and name in {
        "Hacker News", "Wikimedia", "Google Trends", "YouTube"} else (
        "Use for metadata enrichment of known URLs." if verdict == "PASS" else "Defer until verified.")
    return Result(f"E2 {name}", verdict,
                  f"HTTP {status}, {len(items)} saved item(s). {note} [Evidence and endpoints](out/{filename}).",
                  f"{rate_note}. {policy}", recommendation)


def run():
    # One exchange at a time per source, with no cookies, redirect-following, retries or proxies.
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(probe, SOURCES))


if __name__ == "__main__":
    standalone(run)
