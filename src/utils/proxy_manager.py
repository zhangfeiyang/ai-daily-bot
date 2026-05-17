"""
Proxy Manager — 自动通过 Clash API 切换代理节点

用法:
    pm = ProxyManager()
    node = pm.get_working_node("huggingface.co")
    resp = pm.fetch_with_node(url, node)

或者直接用自动重试:
    resp = pm.fetch("https://huggingface.co/papers", timeout=8)
    # 内部自动尝试多个节点直到成功
"""

import requests
import time
from loguru import logger
from typing import Optional

CLASH_API = "http://127.0.0.1:9090"
PROXY_GROUP = "Proxy"  # Clash 中的 Proxy 组名称


class ProxyManager:
    """管理 Clash 节点切换，失败时自动换节点重试。"""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "Mozilla/5.0 (compatible; ai-news-bot/1.0)"
        self._node_cache: dict[str, str] = {}  # domain -> working node name

    # ── Clash API ──────────────────────────────────────────────────────────

    def _clash_get(self, path: str) -> dict:
        r = self._session.get(f"{CLASH_API}{path}", timeout=5)
        r.raise_for_status()
        return r.json()

    def _clash_put(self, path: str, data: dict) -> None:
        r = self._session.put(
            f"{CLASH_API}{path}",
            json=data,
            timeout=5,
        )
        r.raise_for_status()

    def get_all_nodes(self) -> list[str]:
        """返回 Proxy 组里所有节点名称列表（按配置顺序）。"""
        data = self._clash_get("/proxies")
        proxies = data.get("proxies", {})  # dict keyed by name, not list
        group = proxies.get(PROXY_GROUP)
        if not group:
            logger.warning(f"ProxyManager: '{PROXY_GROUP}' group not found")
            return []
        all_nodes = group.get("all", [])
        # "all" contains both leaf proxies AND sub-group names.
        # Sub-groups have type != "select" (they are url-test/fallback/ etc).
        # We want only leaf proxies in the candidates list.
        special = {"DIRECT", "REJECT", "自动选择", "故障转移"}
        real_nodes = []
        for n in all_nodes:
            if n in special:
                continue
            if n in proxies and proxies[n].get("type") in ("select",):
                continue  # skip sub-selectors
            real_nodes.append(n)
        return real_nodes

    def get_current_node(self) -> str:
        """返回当前选中的节点名称。"""
        data = self._clash_get(f"/proxies/{PROXY_GROUP}")
        return data.get("now", "")

    def switch_node(self, node_name: str) -> bool:
        """切换到指定节点。成功返回 True。"""
        try:
            self._clash_put(f"/proxies/{PROXY_GROUP}", {"name": node_name})
            logger.info(f"ProxyManager: switched to '{node_name}'")
            return True
        except Exception as e:
            logger.warning(f"ProxyManager: failed to switch to '{node_name}': {e}")
            return False

    # ── 健康检查 ─────────────────────────────────────────────────────────

    def _check_node_health(self, node_name: str, test_url: str, timeout: int = 8) -> bool:
        """测试指定节点能否访问 test_url。"""
        # 临时切换到该节点
        self._clash_put(f"/proxies/{PROXY_GROUP}", {"name": node_name})
        try:
            r = self._session.get(test_url, timeout=timeout)
            return r.status_code < 500
        except Exception:
            return False

    def get_working_node(self, domain: str, max_try: int = 8) -> Optional[str]:
        """为指定域名找到一个可达的节点（缓存优先）。"""
        if domain in self._node_cache:
            cached = self._node_cache[domain]
            if self._check_node_health(cached, f"https://{domain}", timeout=6):
                return cached
            # 缓存失效，删掉
            del self._node_cache[domain]

        nodes = self.get_all_nodes()
        if not nodes:
            return None

        # 先用当前节点试试
        current = self.get_current_node()
        if current and current not in ("DIRECT", "REJECT"):
            if self._check_node_health(current, f"https://{domain}", timeout=6):
                self._node_cache[domain] = current
                return current

        # 随机打乱尝试顺序，避免总是用同一个
        import random
        candidates = [n for n in nodes if n not in ("DIRECT", "REJECT", "自动选择", "故障转移")]
        random.shuffle(candidates)

        tried = []
        for node in candidates:
            if node in tried or len(tried) >= max_try:
                break
            tried.append(node)
            if node == current:
                continue
            if self._check_node_health(node, f"https://{domain}", timeout=6):
                self._node_cache[domain] = node
                return node

        logger.warning(f"ProxyManager: no working node found for '{domain}' (tried {len(tried)})")
        return None

    # ── 高层接口：自动重试 ──────────────────────────────────────────────

    def fetch(
        self,
        url: str,
        timeout: int = 10,
        max_nodes: int = 8,
        headers: Optional[dict] = None,
    ) -> Optional[requests.Response]:
        """
        带自动节点切换的 GET 请求。
        依次尝试不同节点，任何一个成功就返回。
        """
        domain = url.split("/")[2] if "//" in url else ""
        nodes = self.get_all_nodes()
        if not nodes:
            return None

        import random
        candidates = [n for n in nodes if n not in ("DIRECT", "REJECT", "自动选择", "故障转移")]

        # 优先试当前节点
        current = self.get_current_node()
        if current in candidates:
            candidates.remove(current)
            candidates.insert(0, current)

        # 随机打乱其余节点
        rest = [n for n in candidates if n != current]
        random.shuffle(rest)
        order = candidates[:1] + rest  # 当前节点优先

        for node in order[:max_nodes]:
            try:
                # 切换到该节点
                self._clash_put(f"/proxies/{PROXY_GROUP}", {"name": node})
                # 发请求
                extra = headers or {}
                resp = self._session.get(url, timeout=timeout, headers=extra)
                if resp.status_code < 500:
                    return resp
            except Exception as e:
                logger.debug(f"ProxyManager: {node} → {url[:50]} failed: {e}")

        return None

    def health_check_all(self) -> dict[str, bool]:
        """检查所有节点到几个主要目标的可达性（用于调试）。"""
        targets = {
            "github.com": "https://api.github.com",
            "huggingface.co": "https://huggingface.co",
            "arxiv.org": "https://arxiv.org",
            "reddit.com": "https://www.reddit.com",
            "nitter.net": "https://nitter.net",
        }
        results = {}
        for name, url in targets.items():
            working = self.get_working_node(name, max_try=5)
            results[name] = working
        return results


# 全局单例
_pm: Optional[ProxyManager] = None


def get_proxy_manager() -> ProxyManager:
    global _pm
    if _pm is None:
        _pm = ProxyManager()
    return _pm


if __name__ == "__main__":
    pm = get_proxy_manager()
    print("当前节点:", pm.get_current_node())
    print("总节点数:", len(pm.get_all_nodes()))
    print("\n节点健康检查:")
    for domain, node in pm.health_check_all().items():
        print(f"  {domain}: {'❌' if not node else '✅ ' + node}")