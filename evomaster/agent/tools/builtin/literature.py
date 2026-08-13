"""Restricted scholarly-metadata search for literature-grounded agent priors."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from html import unescape
from typing import Any, ClassVar, Literal

from pydantic import Field

from ..base import BaseTool, BaseToolParams


class LiteratureSearchToolParams(BaseToolParams):
    """Search scholarly metadata without granting general web or filesystem access."""

    name: ClassVar[str] = "literature_search"

    query: str = Field(
        min_length=3,
        max_length=300,
        description="Broad scientific topic query. Do not include benchmark answer terms.",
    )
    max_results: int = Field(default=5, ge=1, le=10)
    from_year: int | None = Field(default=None, ge=1900)
    sort: Literal["relevance", "latest"] = "relevance"


class LiteratureSearchTool(BaseTool):
    """Search Crossref for paper metadata and abstracts to ground broad physical priors."""

    name: ClassVar[str] = "literature_search"
    params_class: ClassVar[type[BaseToolParams]] = LiteratureSearchToolParams
    endpoint = "https://api.crossref.org/works"

    @staticmethod
    def _plain_text(value: Any, limit: int = 1600) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        text = re.sub(r"<[^>]+>", " ", unescape(value))
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    @staticmethod
    def _first_text(value: Any) -> str | None:
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value[0].strip() or None
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _year(item: dict[str, Any]) -> int | None:
        for key in ("published-print", "published-online", "issued"):
            parts = item.get(key, {}).get("date-parts", [])
            if parts and parts[0] and isinstance(parts[0][0], int):
                return parts[0][0]
        return None

    @staticmethod
    def _authors(item: dict[str, Any]) -> list[str]:
        authors = []
        for author in item.get("author", [])[:8]:
            if not isinstance(author, dict):
                continue
            name = " ".join(
                part for part in (author.get("given"), author.get("family")) if part
            ).strip()
            if name:
                authors.append(name)
        return authors

    def _request(self, params: LiteratureSearchToolParams) -> dict[str, Any]:
        query: dict[str, str] = {
            "query.bibliographic": params.query,
            "rows": str(params.max_results),
            "select": (
                "DOI,title,author,published-print,published-online,issued,"
                "URL,abstract,container-title,type"
            ),
        }
        if params.from_year is not None:
            if params.from_year > date.today().year:
                raise ValueError("from_year cannot be in the future")
            query["filter"] = f"from-pub-date:{params.from_year}-01-01"
        if params.sort == "latest":
            query["sort"] = "published"
            query["order"] = "desc"

        url = f"{self.endpoint}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "HamiltonLiteratureGrounding/1.0 (mailto:research@example.invalid)",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def execute(self, session: Any, args_json: str) -> tuple[str, dict[str, Any]]:
        try:
            params = self.parse_params(args_json)
            assert isinstance(params, LiteratureSearchToolParams)
            payload = self._request(params)
            items = payload.get("message", {}).get("items", [])
            results = []
            for item in items[: params.max_results]:
                if not isinstance(item, dict):
                    continue
                doi = self._first_text(item.get("DOI"))
                results.append(
                    {
                        "title": self._first_text(item.get("title")),
                        "authors": self._authors(item),
                        "year": self._year(item),
                        "venue": self._first_text(item.get("container-title")),
                        "doi": doi,
                        "url": (
                            f"https://doi.org/{doi}"
                            if doi
                            else self._first_text(item.get("URL"))
                        ),
                        "abstract": self._plain_text(item.get("abstract")),
                        "type": self._first_text(item.get("type")),
                    }
                )
            output = {
                "source": "Crossref REST API",
                "query": params.query,
                "results": results,
                "research_integrity": (
                    "Use these records only for broad, cited physical priors. "
                    "Do not copy equations, coefficients, monomial lists, or benchmark templates."
                ),
            }
            return json.dumps(output, ensure_ascii=False, indent=2), {
                "source": "crossref",
                "result_count": len(results),
            }
        except (urllib.error.URLError, TimeoutError) as exc:
            return f"Literature search unavailable: {exc}", {"error": "network_error"}
        except Exception as exc:
            return f"Literature search failed: {exc}", {"error": type(exc).__name__}
