#!/usr/bin/env python3
"""
Shopify Blog Publisher — Creates blog article drafts via Shopify Admin API.

Used by Beacon (SEO agent) to publish daily SEO/AEO content.
Articles are ALWAYS created as drafts — Tom reviews and publishes manually.
"""

import os
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ShopifyBlogPublisher:
    """
    Manages Shopify blog articles via Admin REST API 2025-01.

    All articles are created as DRAFTS (published=False).
    Tom reviews and publishes manually from Shopify admin.
    """

    API_VERSION = "2025-01"

    def __init__(self):
        self.store_url = os.environ.get("SHOPIFY_STORE_URL")
        self.token = os.environ.get("SHOPIFY_ACCESS_TOKEN")

    @property
    def available(self) -> bool:
        return bool(self.store_url and self.token)

    @property
    def base_url(self) -> str:
        return f"https://{self.store_url}/admin/api/{self.API_VERSION}"

    @property
    def headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None) -> dict:
        """Make an HTTP request with retry logic."""
        import requests

        url = f"{self.base_url}/{path}"

        for attempt in range(3):
            try:
                resp = requests.request(
                    method, url, headers=self.headers,
                    json=data, params=params, timeout=30
                )

                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 2))
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp.json() if resp.content else {}

            except Exception as e:
                if attempt == 2:
                    logger.error(f"Shopify blog {method} {path} failed: {e}")
                    raise
                time.sleep(2 ** attempt)

        return {}

    def get_blogs(self) -> list:
        """
        Get all blogs for the store.

        GET /admin/api/2025-01/blogs.json

        Returns list of blog objects with id, title, handle.
        """
        result = self._request("GET", "blogs.json")
        blogs = result.get("blogs", [])
        logger.info(f"Found {len(blogs)} blog(s)")
        return blogs

    def get_default_blog_id(self) -> Optional[str]:
        """Get the ID of the first/default blog."""
        blogs = self.get_blogs()
        if blogs:
            return str(blogs[0]["id"])
        return None

    def create_draft_article(self, blog_id: str, title: str, body_html: str,
                              tags: str = "", author: str = "Deep Blue Health",
                              summary_html: str = "",
                              metafields: list = None) -> dict:
        """
        Create a draft blog article.

        POST /admin/api/2025-01/blogs/{blog_id}/articles.json

        Article is ALWAYS created as draft (published=False).

        Args:
            blog_id: The blog to post to
            title: Article title
            body_html: Full article HTML
            tags: Comma-separated tags
            author: Author name
            summary_html: Optional excerpt/summary
            metafields: Optional list of metafield dicts for SEO schema

        Returns:
            Created article object
        """
        article_data = {
            "title": title,
            "body_html": body_html,
            "author": author,
            "tags": tags,
            "published": False,  # ALWAYS draft
        }

        if summary_html:
            article_data["summary_html"] = summary_html

        if metafields:
            article_data["metafields"] = metafields

        result = self._request("POST", f"blogs/{blog_id}/articles.json", {
            "article": article_data
        })

        article = result.get("article", {})
        logger.info(f"Created draft article: '{title}' (ID: {article.get('id', '?')})")
        return article

    def publish_article(self, blog_id: str, article_id: str) -> dict:
        """
        Publish a draft article.

        PUT /admin/api/2025-01/blogs/{blog_id}/articles/{article_id}.json
        """
        from datetime import datetime, timezone

        result = self._request("PUT", f"blogs/{blog_id}/articles/{article_id}.json", {
            "article": {
                "id": int(article_id),
                "published": True,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        })

        article = result.get("article", {})
        logger.info(f"Published article {article_id}: '{article.get('title', '?')}'")
        return article

    def get_articles(self, blog_id: str, limit: int = 5,
                     status: str = None) -> list:
        """
        Get recent articles from a blog.

        GET /admin/api/2025-01/blogs/{blog_id}/articles.json

        Args:
            blog_id: Blog ID
            limit: Number of articles to return
            status: Optional filter: "published" or "unpublished"
        """
        params = {"limit": limit}
        if status:
            params["published_status"] = status  # "published" or "unpublished"

        result = self._request("GET", f"blogs/{blog_id}/articles.json", params=params)
        return result.get("articles", [])

    def get_draft_count(self) -> int:
        """Get count of unpublished draft articles across all blogs."""
        count = 0
        for blog in self.get_blogs():
            articles = self.get_articles(str(blog["id"]), limit=250, status="unpublished")
            count += len(articles)
        return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    publisher = ShopifyBlogPublisher()

    if not publisher.available:
        print("SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN required")
    else:
        blogs = publisher.get_blogs()
        for blog in blogs:
            print(f"Blog: {blog['title']} (ID: {blog['id']}, handle: {blog.get('handle', '')})")
            drafts = publisher.get_articles(str(blog['id']), limit=5, status="unpublished")
            print(f"  Drafts: {len(drafts)}")
