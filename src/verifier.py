# src/verifier.py
"""官方来源验证模块。

筛选后的新闻需去官方确认，优先级：
1. 官方网站 / Blog
2. 官方推特（国内公司先查官方微信公众号）
3. CEO 推特
4. 模型负责人推特

确认后检查是否超过 24h，超过则舍弃。
"""

import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, unquote, parse_qs
from loguru import logger

_BEIJING_TZ = timezone(timedelta(hours=8))


class NewsVerifier:
    def __init__(self, llm_client, official_sources: dict):
        self.llm = llm_client
        self.sources = official_sources
        self._company_keywords = self._build_keyword_index()

    def _build_keyword_index(self) -> list[tuple[str, list[str]]]:
        """构建关键词 → 公司映射。"""
        index = []
        for company_key, cfg in self.sources.items():
            kws = cfg.get("keywords", [])
            if kws:
                index.append((company_key, kws))
            for sub_key, sub_cfg in cfg.get("sub_brands", {}).items():
                sub_kws = sub_cfg.get("keywords", [])
                if sub_kws:
                    index.append((company_key, sub_kws))
        return index

    def identify_company(self, title: str, content: str) -> str | None:
        """从新闻标题和内容识别涉及的公司（关键词匹配）。"""
        text = (title + " " + content[:500]).lower()

        best_company = None
        best_score = 0
        for company_key, keywords in self._company_keywords:
            score = sum(1 for kw in keywords if kw.lower() in text)
            if score > best_score:
                best_score = score
                best_company = company_key

        return best_company if best_score > 0 else None

    def verify_official(self, item) -> dict:
        """验证新闻的官方来源，按优先级逐级尝试。"""
        company = self.identify_company(item.title, item.content)
        if not company:
            logger.info(f"No company identified for: {item.title[:50]}")
            return {"verified": False, "reason": "no_company"}

        cfg = self.sources.get(company, {})
        logger.info(f"Identified company: {company} for: {item.title[:50]}")

        # 按优先级逐级验证
        strategies = [
            ("website", lambda: self._search_official_website(item, cfg, company)),
            ("wechat", lambda: self._search_wechat(item, cfg, company)),
            ("twitter", lambda: self._search_official_twitter(item, cfg, company)),
            ("ceo_twitter", lambda: self._search_ceo_twitter(item, cfg, company)),
            ("model_lead_twitter", lambda: self._search_model_lead_twitter(item, cfg, company)),
            ("direct_url", lambda: self._check_existing_url(item, cfg)),
        ]

        for name, strategy in strategies:
            try:
                result = strategy()
                if result.get("verified"):
                    logger.info(f"  Verified via {name}: {item.title[:50]}")
                    return result
            except Exception as e:
                logger.debug(f"  Strategy {name} failed: {e}")

        logger.info(f"Could not verify official source for: {item.title[:50]}")
        return {"verified": False, "reason": "not_found"}

    # ---- 策略 1: 官方网站 ----

    def _search_official_website(self, item, cfg: dict, company: str) -> dict:
        """通过 Web 搜索验证官网信息。"""
        website = cfg.get("website", "")
        blog = cfg.get("blog", website)
        if not website:
            return {"verified": False}

        search_query = self._build_search_query(item, company)
        site_query = f"site:{self._extract_domain(blog)} {search_query}"

        results = self._web_search(site_query, max_results=3)
        if results:
            best = results[0]
            images = self._fetch_page_images(best.get("url", ""))
            return {
                "verified": True,
                "source": "website",
                "official_url": best.get("url", ""),
                "official_image": images[0] if images else "",
                "publish_time": best.get("date", ""),
            }

        return {"verified": False}

    # ---- 策略 2: 官方微信公众号（仅国内公司） ----

    def _search_wechat(self, item, cfg: dict, company: str) -> dict:
        """通过微信公众号搜索验证（仅国内公司有 wechat 字段时生效）。"""
        wechat_name = cfg.get("wechat", "")
        if not wechat_name:
            return {"verified": False}

        search_query = self._build_search_query(item, company)
        # 搜狗微信搜索
        site_query = f"site:weixin.qq.com {wechat_name} {search_query}"

        results = self._web_search(site_query, max_results=3)
        if results:
            best = results[0]
            # 微信文章页面抓图
            images = self._fetch_page_images(best.get("url", ""))
            return {
                "verified": True,
                "source": "wechat",
                "official_url": best.get("url", ""),
                "official_image": images[0] if images else "",
                "publish_time": best.get("date", ""),
            }

        return {"verified": False}

    # ---- 策略 3: 官方推特 ----

    def _search_official_twitter(self, item, cfg: dict, company: str) -> dict:
        """验证官方推特信息。"""
        twitter = cfg.get("twitter", "")
        if not twitter:
            return {"verified": False}

        return self._search_twitter_account(item, company, twitter, "official_twitter")

    # ---- 策略 4: CEO 推特 ----

    def _search_ceo_twitter(self, item, cfg: dict, company: str) -> dict:
        """验证 CEO 推特信息。"""
        ceo_twitter = cfg.get("ceo_twitter", "")
        if not ceo_twitter:
            return {"verified": False}

        return self._search_twitter_account(item, company, ceo_twitter, "ceo_twitter")

    # ---- 策略 5: 模型负责人推特 ----

    def _search_model_lead_twitter(self, item, cfg: dict, company: str) -> dict:
        """根据新闻内容匹配对应模型负责人的推特。"""
        model_leads = cfg.get("model_leads", [])
        if not model_leads:
            return {"verified": False}

        # 从标题中匹配最相关的模型负责人
        text_lower = (item.title + " " + item.content[:300]).lower()
        for lead in model_leads:
            lead_name = lead.get("name", "").lower()
            if lead_name and lead_name in text_lower:
                lead_twitter = lead.get("twitter", "")
                if lead_twitter:
                    return self._search_twitter_account(
                        item, company, lead_twitter, "model_lead_twitter"
                    )

        # 没有匹配到特定模型，尝试第一个负责人
        if model_leads:
            first = model_leads[0]
            return self._search_twitter_account(
                item, company, first.get("twitter", ""), "model_lead_twitter"
            )

        return {"verified": False}

    # ---- 策略 6: 已有 URL 直接验证 ----

    def _check_existing_url(self, item, cfg: dict) -> dict:
        """检查新闻原始 URL 是否就是官方来源。"""
        url = item.url.lower()
        website = cfg.get("website", "").lower()
        blog = cfg.get("blog", "").lower()

        if website and website in url:
            return {
                "verified": True,
                "source": "direct",
                "official_url": item.url,
                "official_image": item.raw_data.get("image_url", ""),
                "publish_time": item.published_at.isoformat() if item.published_at else "",
            }

        if blog and blog in url:
            return {
                "verified": True,
                "source": "direct",
                "official_url": item.url,
                "official_image": item.raw_data.get("image_url", ""),
                "publish_time": item.published_at.isoformat() if item.published_at else "",
            }

        # Twitter 官方账号
        twitter = cfg.get("twitter", "").lower()
        if twitter and f"x.com/{twitter}" in url:
            return {
                "verified": True,
                "source": "twitter_direct",
                "official_url": item.url,
                "official_image": item.raw_data.get("image_url", ""),
                "publish_time": item.published_at.isoformat() if item.published_at else "",
            }

        return {"verified": False}

    # ---- 共用推特搜索 ----

    def _search_twitter_account(
        self, item, company: str, account: str, source_label: str
    ) -> dict:
        """在指定推特账号中搜索相关推文。"""
        search_query = self._build_search_query(item, company)
        site_query = f"site:x.com/{account} {search_query}"

        results = self._web_search(site_query, max_results=3)
        if results:
            best = results[0]
            tweet_url = best.get("url", "")
            # 尝试从推特页面抓取图片
            images = self._fetch_tweet_images(tweet_url)
            return {
                "verified": True,
                "source": source_label,
                "official_url": tweet_url,
                "official_image": images[0] if images else "",
                "publish_time": best.get("date", ""),
            }

        return {"verified": False}

    @staticmethod
    def _fetch_tweet_images(tweet_url: str) -> list[str]:
        """从推特/Nitter 页面抓取图片。"""
        if not tweet_url:
            return []

        try:
            import requests
            from bs4 import BeautifulSoup

            # 先尝试直接抓取推特 URL
            resp = requests.get(
                tweet_url, timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            images = []

            # og:image 通常包含推特卡片图
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                img_url = og["content"]
                # 排除个人头像和通用占位图
                if "profile_images" not in img_url and "default_profile" not in img_url:
                    images.append(img_url)

            # twitter:image
            tw = soup.find("meta", attrs={"name": "twitter:image"})
            if tw and tw.get("content"):
                img_url = tw["content"]
                if "profile_images" not in img_url and img_url not in images:
                    images.append(img_url)

            # 如果直接推特页面没有图片，尝试通过 Nitter 镜像获取
            if not images:
                nitter_images = NewsVerifier._try_nitter_images(tweet_url)
                images.extend(nitter_images)

            return images[:5]
        except Exception as e:
            logger.debug(f"Fetch tweet images failed: {e}")
            return []

    @staticmethod
    def _try_nitter_images(tweet_url: str) -> list[str]:
        """尝试通过 Nitter 镜像获取推特图片。"""
        # 从 URL 提取用户名和推文 ID
        match = re.search(r'x\.com/(\w+)/status/(\d+)', tweet_url)
        if not match:
            return []

        username = match.group(1)
        status_id = match.group(2)
        nitter_instances = [
            "nitter.net",
            "nitter.privacydev.net",
            "nitter.poast.org",
        ]

        for instance in nitter_instances:
            try:
                import requests
                nitter_url = f"https://{instance}/{username}/status/{status_id}"
                resp = requests.get(
                    nitter_url, timeout=10,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code != 200:
                    continue

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                images = []
                for img in soup.select(".attachment img, .gallery-row img"):
                    src = img.get("src", "")
                    if src:
                        if src.startswith("/"):
                            src = f"https://{instance}{src}"
                        # Nitter 图片 URL 转换为原始推特图片
                        if "/pic/" in src:
                            actual = unquote(src.split("/pic/")[-1])
                            if actual.startswith("http"):
                                src = actual
                        images.append(src)
                if images:
                    return images
            except Exception:
                continue

        return []

    # ---- 新鲜度检查 ----

    def check_freshness(self, publish_time: str, max_hours: int = 24) -> bool:
        """检查官方消息是否在指定小时数内。无时间信息时不通过。"""
        if not publish_time:
            # 没有时间信息，保守拒绝
            logger.info("Freshness check: no publish_time, rejecting")
            return False

        try:
            for fmt in [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%a, %d %b %Y %H:%M:%S",
                "%a, %d %b %Y %H:%M:%S %z",
            ]:
                try:
                    dt = datetime.strptime(publish_time.strip(), fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                logger.info(f"Freshness check: cannot parse date '{publish_time}', rejecting")
                return False

            now = datetime.now(timezone.utc)
            age = now - dt
            is_fresh = age <= timedelta(hours=max_hours)
            if not is_fresh:
                logger.info(f"Stale news: {age.total_seconds()/3600:.1f}h old (limit: {max_hours}h)")
            return is_fresh
        except Exception:
            logger.info("Freshness check: exception during parsing, rejecting")
            return False

    # ---- 工具方法 ----

    @staticmethod
    def _build_search_query(item, company: str) -> str:
        """从新闻标题提取搜索关键词。"""
        title = item.title
        title = re.sub(r'^(Pinned:\s*|RT\s+@\w+:\s*|RT by @\w+:\s*)', '', title)
        products = re.findall(r'[A-Z][A-Za-z0-9_.\-]*[A-Za-z0-9]', title)
        if products:
            products.sort(key=len, reverse=True)
            query = " ".join(products[:2])
        else:
            query = title[:60]
        return query.strip()

    @staticmethod
    def _extract_domain(url: str) -> str:
        """从 URL 提取域名。"""
        parsed = urlparse(url)
        return parsed.netloc

    @staticmethod
    def _web_search(query: str, max_results: int = 3) -> list[dict]:
        """使用 DuckDuckGo 搜索。"""
        try:
            import requests
            from bs4 import BeautifulSoup

            url = "https://html.duckduckgo.com/html/"
            resp = requests.post(
                url,
                data={"q": query, "kl": "cn-zh"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            results = []
            soup = BeautifulSoup(resp.text, "html.parser")

            for r in soup.select(".result"):
                link = r.select_one(".result__a")
                snippet = r.select_one(".result__snippet")
                if link:
                    href = link.get("href", "")
                    if "uddg=" in href:
                        parsed = urlparse(href)
                        params = parse_qs(parsed.query)
                        href = unquote(params.get("uddg", [href])[0])
                    date_elem = r.select_one(".result__timestamp")
                    results.append({
                        "url": href,
                        "title": link.get_text(strip=True),
                        "snippet": snippet.get_text(strip=True) if snippet else "",
                        "date": date_elem.get_text(strip=True) if date_elem else "",
                    })
                    if len(results) >= max_results:
                        break

            return results
        except Exception as e:
            logger.debug(f"Web search failed: {e}")
            return []

    @staticmethod
    def _fetch_page_images(url: str) -> list[str]:
        """从网页中提取图片 URL。"""
        try:
            import requests
            from bs4 import BeautifulSoup

            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            images = []

            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                images.append(og["content"])

            tw = soup.find("meta", attrs={"name": "twitter:image"})
            if tw and tw.get("content"):
                images.append(tw["content"])

            for img in soup.find_all("img"):
                src = img.get("src", "")
                if src and not src.startswith("data:"):
                    width = img.get("width", "")
                    if width and width.isdigit() and int(width) >= 400 or len(src) > 30:
                        if src.startswith("//"):
                            src = "https:" + src
                        elif src.startswith("/"):
                            domain = urlparse(url).netloc
                            src = f"https://{domain}{src}"
                        images.append(src)

            return images[:5]
        except Exception as e:
            logger.debug(f"Fetch page images failed: {e}")
            return []
