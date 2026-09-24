from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any

from .config import (
    HTTP_TIMEOUT_SECONDS,
    MAX_HTTP_BYTES,
    MAX_RESEARCH_FEEDS,
    MAX_SEARCH_RESULTS,
    RESEARCH_TOTAL_TIMEOUT_SECONDS,
)

USER_AGENT = "ScalperLab/0.1 (desktop strategy research; contact: local application)"


class ResearchError(Exception):
    pass


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = False
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.meta_description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.lower() == "title":
            self.title = True
        if tag.lower() == "meta" and values.get("name", "").lower() in {"description", "og:description"}:
            self.meta_description = values.get("content") or self.meta_description

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.title = False

    def handle_data(self, data: str) -> None:
        clean = " ".join(data.split())
        if clean:
            if self.title:
                self.title_parts.append(clean)
            if len(" ".join(self.parts)) < 8000:
                self.parts.append(clean)


def _validate_public_https_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ResearchError("Use uma URL HTTPS pública, sem credenciais embutidas.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".localhost")):
        raise ResearchError("Endereços locais não podem ser importados.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ResearchError("Não foi possível resolver o domínio da fonte.") from exc
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ResearchError("A fonte resolve para um endereço não público.") from None
    else:
        if not ip.is_global:
            raise ResearchError("Endereços IP privados ou reservados não podem ser importados.")
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        _validate_public_https_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    """Reject a DNS-rebound/private target after the TLS connection is established."""

    def connect(self) -> None:
        super().connect()
        if self.sock is None:
            raise ResearchError("A conexão segura com a fonte não foi estabelecida.")
        peer = ipaddress.ip_address(self.sock.getpeername()[0])
        if not peer.is_global:
            self.sock.close()
            self.sock = None
            raise ResearchError("A conexão da fonte terminou em um endereço não público.")


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_PublicHTTPSConnection, request, context=self._context)


def _get(url: str, headers: dict[str, str] | None = None,
         timeout: float = HTTP_TIMEOUT_SECONDS) -> tuple[bytes, str]:
    safe_url = _validate_public_https_url(url)
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json, application/atom+xml, application/rss+xml, text/html;q=0.9, */*;q=0.5"}
    request_headers.update(headers or {})
    # Avoid ambient HTTP(S)_PROXY settings bypassing the connected-peer check.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SafeRedirect, _SafeHTTPSHandler())
    request = urllib.request.Request(safe_url, headers=request_headers)
    try:
        with opener.open(request, timeout=max(0.1, timeout)) as response:
            content_type = response.headers.get_content_type()
            data = response.read(MAX_HTTP_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ResearchError(f"A fonte respondeu HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ResearchError("A fonte não respondeu ou está indisponível.") from exc
    if len(data) > MAX_HTTP_BYTES:
        raise ResearchError("A resposta excedeu o limite local de tamanho.")
    return data, content_type


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _normal_result(title: str, url: str, source: str, excerpt: str = "", published_at: str | None = None) -> dict[str, Any]:
    safe_url = _validate_public_https_url(url)
    parsed = urllib.parse.urlsplit(safe_url)
    safe_url = urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))
    return {"title": title.strip() or safe_url, "url": safe_url, "source": source,
            "excerpt": " ".join(excerpt.split())[:1000], "published_at": published_at}


def _matches(query: str, text: str) -> bool:
    words = [word.lower() for word in re.findall(r"[\w+#.-]+", query) if len(word) > 2]
    haystack = text.lower()
    return not words or any(word in haystack for word in words)


class ResearchService:
    def __init__(self, database) -> None:
        self.database = database
        self._feed_lock = threading.RLock()

    def provider_status(self) -> list[dict[str, Any]]:
        return [
            {"name": "GitHub", "available": True, "detail": "Busca de repositórios públicos via API oficial."},
            {"name": "Busca web", "available": bool(os.getenv("SCALPERLAB_BRAVE_API_KEY")),
             "detail": "Configure SCALPERLAB_BRAVE_API_KEY para busca ampla em sites, blogs e fóruns."},
            {"name": "YouTube", "available": bool(os.getenv("SCALPERLAB_YOUTUBE_API_KEY")),
             "detail": "A API oficial do YouTube requer uma chave configurada no ambiente."},
            {"name": "Feeds RSS/Atom", "available": True,
             "detail": f"{len(self.database.list_feeds())} feed(s) configurado(s)."},
        ]

    def search(self, query: str) -> dict[str, Any]:
        query = " ".join(query.split())[:240]
        if len(query) < 3:
            raise ResearchError("Digite ao menos três caracteres para pesquisar.")
        items: list[dict[str, Any]] = []
        providers: list[dict[str, Any]] = []
        deadline = time.monotonic() + RESEARCH_TOTAL_TIMEOUT_SECONDS
        operations = (
            ("GitHub", self._github),
            ("Busca web", self._brave),
            ("YouTube", self._youtube),
            ("Feeds RSS/Atom", self._feeds),
        )
        for name, operation in operations:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                providers.append({"name": name, "ok": False, "count": 0,
                                  "detail": "Orçamento total de tempo da pesquisa esgotado."})
                continue
            try:
                found = operation(query, timeout=min(HTTP_TIMEOUT_SECONDS, remaining))
                items.extend(found)
                providers.append({"name": name, "ok": True, "count": len(found)})
            except ResearchError as exc:
                providers.append({"name": name, "ok": False, "count": 0, "detail": str(exc)})
        unique: dict[str, dict[str, Any]] = {}
        for item in items:
            unique.setdefault(item["url"], item)
        results = list(unique.values())[:MAX_SEARCH_RESULTS * 3]
        saved = self.database.save_research_items(results)
        return {"items": results, "providers": providers, "saved": saved,
                "message": "Resultados e respectivas fontes foram registrados; revise cada fonte antes de usar um achado como estratégia."}

    def _github(self, query: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({"q": f"{query} MetaTrader OR MQL5", "sort": "updated", "per_page": MAX_SEARCH_RESULTS})
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            data, _ = _get(f"https://api.github.com/search/repositories?{params}", headers, timeout)
            payload = json.loads(data)
        except (ResearchError, json.JSONDecodeError) as exc:
            raise ResearchError(f"GitHub indisponível: {exc}") from exc
        return [_normal_result(item.get("full_name", "Repositório GitHub"), item["html_url"], "GitHub",
                               item.get("description") or "Repositório público relacionado à busca.", item.get("updated_at"))
                for item in payload.get("items", []) if item.get("html_url")]

    def _brave(self, query: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
        key = os.getenv("SCALPERLAB_BRAVE_API_KEY")
        if not key:
            raise ResearchError("Configure SCALPERLAB_BRAVE_API_KEY no ambiente para habilitar busca web.")
        params = urllib.parse.urlencode({"q": query, "count": MAX_SEARCH_RESULTS})
        try:
            data, _ = _get(f"https://api.search.brave.com/res/v1/web/search?{params}",
                           {"Accept": "application/json", "X-Subscription-Token": key}, timeout)
            payload = json.loads(data)
        except (ResearchError, json.JSONDecodeError) as exc:
            raise ResearchError(f"Busca web indisponível: {exc}") from exc
        return [_normal_result(item.get("title", "Resultado web"), item["url"],
                               urllib.parse.urlsplit(item["url"]).hostname or "Web", item.get("description", ""))
                for item in payload.get("web", {}).get("results", []) if item.get("url")]

    def _youtube(self, query: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
        key = os.getenv("SCALPERLAB_YOUTUBE_API_KEY")
        if not key:
            raise ResearchError("Configure SCALPERLAB_YOUTUBE_API_KEY no ambiente para habilitar busca no YouTube.")
        params = urllib.parse.urlencode({"part": "snippet", "q": query, "type": "video",
                                         "maxResults": MAX_SEARCH_RESULTS, "key": key})
        try:
            data, _ = _get(f"https://www.googleapis.com/youtube/v3/search?{params}", timeout=timeout)
            payload = json.loads(data)
        except (ResearchError, json.JSONDecodeError) as exc:
            raise ResearchError(f"YouTube indisponível: {exc}") from exc
        results = []
        for item in payload.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            if video_id:
                results.append(_normal_result(snippet.get("title", "Vídeo"),
                                              f"https://www.youtube.com/watch?v={video_id}", "YouTube",
                                              snippet.get("description", ""), snippet.get("publishedAt")))
        return results

    def _feeds(self, query: str, timeout: float = RESEARCH_TOTAL_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        errors = []
        feeds = self.database.list_feeds()[:MAX_RESEARCH_FEEDS]
        deadline = time.monotonic() + min(RESEARCH_TOTAL_TIMEOUT_SECONDS, timeout)
        for feed in feeds:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                errors.append("Tempo total de pesquisa de feeds esgotado.")
                break
            try:
                data, _ = _get(feed["url"], timeout=min(HTTP_TIMEOUT_SECONDS, remaining))
                items.extend(item for item in parse_feed(data, feed["label"], feed["url"])
                             if _matches(query, f"{item['title']} {item['excerpt']}"))
            except ResearchError as exc:
                errors.append(f"{feed['label']}: {exc}")
        if errors and not items:
            raise ResearchError("; ".join(errors[:2]))
        return items[:MAX_SEARCH_RESULTS]

    def import_url(self, url: str) -> dict[str, Any]:
        safe_url = _validate_public_https_url(url)
        data, content_type = _get(safe_url)
        if content_type in {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}:
            parsed = parse_feed(data, urllib.parse.urlsplit(safe_url).hostname or "Feed", safe_url)
            stored = self.database.save_research_items(parsed)
            return {"items": parsed, "saved": stored}
        parser = TextExtractor()
        parser.feed(_text(data))
        title = " ".join(parser.title_parts)[:300] or urllib.parse.urlsplit(safe_url).hostname or safe_url
        excerpt = parser.meta_description or " ".join(parser.parts)
        item = _normal_result(title, safe_url, urllib.parse.urlsplit(safe_url).hostname or "Web", excerpt)
        stored = self.database.save_research_items([item])
        return {"items": [item], "saved": stored}

    def register_feed(self, url: str, label: str) -> dict[str, Any]:
        with self._feed_lock:
            if len(self.database.list_feeds()) >= MAX_RESEARCH_FEEDS:
                raise ResearchError(f"O limite é de {MAX_RESEARCH_FEEDS} feeds cadastrados.")
            safe_url = _validate_public_https_url(url)
            data, _ = _get(safe_url)
            try:
                root = ET.fromstring(data)
            except ET.ParseError as exc:
                raise ResearchError("O endereço não contém um feed RSS/Atom válido.") from exc
            root_name = root.tag.rsplit("}", 1)[-1].lower()
            if root_name not in {"rss", "feed", "rdf"}:
                raise ResearchError("O endereço não contém um feed RSS/Atom.")
            items = parse_feed(data, label or "Feed", safe_url)
            saved = self.database.save_research_items(items)
            feed = self.database.add_feed(safe_url, label or "Feed")
            return {"feed": feed, "saved": saved, "count": len(items)}


def parse_feed(data: bytes, source: str, base_url: str = "") -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ResearchError("O feed não contém XML válido.") from exc
    entries = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] in {"item", "entry"}]
    results = []
    for entry in entries[:MAX_SEARCH_RESULTS]:
        fields = {child.tag.rsplit("}", 1)[-1]: child for child in entry}
        title = "".join(fields.get("title", ET.Element("title")).itertext()).strip()
        link_node = fields.get("link")
        url = ""
        if link_node is not None:
            url = (link_node.attrib.get("href") or link_node.text or "").strip()
        if not url:
            url = (fields.get("guid").text or "").strip() if fields.get("guid") is not None else ""
        excerpt_node = fields.get("description")
        if excerpt_node is None:
            excerpt_node = fields.get("summary")
        if excerpt_node is None:
            excerpt_node = fields.get("content")
        excerpt = "".join(excerpt_node.itertext()).strip() if excerpt_node is not None else ""
        date_node = next((fields[key] for key in ("pubDate", "published", "updated")
                          if fields.get(key) is not None), None)
        published = ("".join(date_node.itertext()).strip() if date_node is not None else None)
        if title and url:
            try:
                url = _validate_public_https_url(urllib.parse.urljoin(base_url, url))
            except ResearchError:
                continue
            results.append(_normal_result(title, url, source, excerpt, published))
    return results
