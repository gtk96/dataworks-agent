"""Chrome DevTools Protocol 客户端 — 集成 Chrome 生命周期管理。

功能:
- 自动检测/启动 Chrome 调试浏览器 (:9222)
- 自动导航到 DataWorks IDE
- 崩溃自动恢复
- DOM 操作、Cookie 提取
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import httpx

from dataworks_agent.config import settings

logger = logging.getLogger(__name__)

SELECTORS_FILE = Path(settings.data_dir) / "selectors.json"

DEFAULT_SELECTORS = {
    "version": 1,
    "selectors": {
        "ide_new_file_btn": "[data-testid='ide-new-file-btn']",
        "ide_new_maxcompute_sql": "[data-testid='ide-new-maxcompute-sql']",
        "ide_node_name_input": "[data-testid='ide-node-name-input']",
        "ide_confirm_btn": "[data-testid='ide-confirm-btn']",
        "ide_editor_area": ".monaco-editor",
        "fallback_create_node": "text=新建...",
    },
}


def _load_selectors() -> dict:
    if SELECTORS_FILE.exists():
        with open(SELECTORS_FILE, encoding="utf-8") as f:
            return json.load(f)
    SELECTORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SELECTORS_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_SELECTORS, f, indent=2, ensure_ascii=False)
    return DEFAULT_SELECTORS


def _find_chrome() -> str:
    """查找 Chrome 可执行文件路径。"""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return "chrome"  # fallback to PATH


async def _is_cdp_alive(url: str = "http://localhost:9222") -> bool:
    """检测 Chrome 调试端口是否已运行。"""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as c:
            resp = await c.get(f"{url}/json/version")
            return resp.status_code == 200
    except Exception:
        return False


def _launch_chrome() -> subprocess.Popen | None:
    """启动 Chrome 调试浏览器并导航到 DataWorks IDE。"""
    chrome = _find_chrome()
    profile_dir = r"C:\chrome-debug-profile"
    project_id = settings.dataworks_project_id
    ide_url = f"https://dataworks.data.aliyun.com/cn-shenzhen/ide?defaultProjectId={project_id}"

    args = [
        chrome,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        ide_url,
    ]

    logger.info("启动 Chrome: %s", chrome)
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        return proc
    except Exception as e:
        logger.error("启动 Chrome 失败: %s", e)
        return None


class CDPClient:
    """Chrome DevTools Protocol 客户端 — 含完整 Chrome 生命周期管理。"""

    CDP_URL: str = settings.cdp_url

    def __init__(self) -> None:
        self._browser: Any = None
        self._page: Any = None
        self._playwright: Any = None
        self._chrome_proc: subprocess.Popen | None = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._selectors: dict = _load_selectors()

    # ── Chrome 生命周期 ──────────────────────────────────────

    async def ensure_chrome(self, auto_launch: bool = True) -> bool:
        """确保 Chrome 调试浏览器可用。已运行→连接；未运行→启动。"""
        if await _is_cdp_alive():
            logger.info("Chrome :9222 已在运行")
            await self._connect_playwright()
            return True

        if not auto_launch:
            return False

        logger.info("Chrome :9222 未运行，正在启动...")
        self._chrome_proc = _launch_chrome()
        if self._chrome_proc is None:
            return False

        # 等待 Chrome 启动完成（最多 15 秒）
        for _ in range(15):
            await asyncio.sleep(1)
            if await _is_cdp_alive():
                logger.info("Chrome 启动成功")
                await self._connect_playwright()
                return True

        logger.warning("Chrome 启动超时")
        return False

    async def _connect_playwright(self) -> None:
        """用 playwright 连接到已有的 Chrome :9222。"""
        if self._browser is not None:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(self.CDP_URL)
        contexts = self._browser.contexts
        pages = contexts[0].pages if contexts else []
        self._page = pages[0] if pages else await contexts[0].new_page()
        logger.info("Chrome 已连接，%d 个页面", len(pages))

    async def _ensure_connected(self) -> None:
        if self._browser is not None and self._page is not None:
            return
        await self._connect_playwright()

    async def test_connection(self) -> bool:
        try:
            if not await _is_cdp_alive():
                return False
            await self._ensure_connected()
            title = await self._page.title()
            logger.debug("Chrome 页面: %s", title[:60])
            return bool(title)
        except Exception:
            return False

    async def shutdown_chrome(self) -> None:
        """关闭 Chrome 浏览器实例。"""
        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
        if self._chrome_proc:
            try:
                self._chrome_proc.terminate()
                self._chrome_proc.wait(timeout=5)
            except Exception:
                self._chrome_proc.kill()
            self._chrome_proc = None
            logger.info("Chrome 已关闭")

    # ── IDE 操作 ─────────────────────────────────────────────

    async def get_ide_page(self) -> Any:
        """获取或导航到 DataWorks IDE 页面。"""
        await self._ensure_connected()
        for ctx in self._browser.contexts:
            for p in ctx.pages:
                url = await p.evaluate("document.location.href")
                if "dataworks" in (url or "").lower():
                    self._page = p
                    return p
        await self.navigate_to_ide()
        return self._page

    async def navigate_to_ide(self) -> None:
        async with self._lock:
            await self._ensure_connected()
            project_id = settings.dataworks_project_id
            url = f"https://dataworks.data.aliyun.com/cn-shenzhen/ide?defaultProjectId={project_id}"
            await self._page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(2)

    async def check_logged_in(self) -> bool:
        """检查 DataWorks 是否已登录。"""
        try:
            await self._ensure_connected()
            page = await self.get_ide_page()
            url = await page.evaluate("document.location.href")
            # 如果在 IDE 页面（非登录页），且 cookie 中含登录标识
            if "login" not in url.lower() and "signin" not in url.lower():
                cookies = await self.extract_cookies_via_cdp()
                return "login_aliyunid" in cookies and len(cookies) > 100
        except Exception:
            pass
        return False

    async def wait_for_login(self, timeout: int = 120) -> bool:
        """等待用户在浏览器中完成登录，自动检测。返回是否登录成功。"""
        logger.info("等待用户登录 DataWorks（超时 %ds）...", timeout)
        # 确保在登录页
        await self._ensure_connected()
        login_url = "https://dataworks.data.aliyun.com/cn-shenzhen/ide"
        await self._page.goto(login_url, wait_until="domcontentloaded")
        logger.info("浏览器已打开 DataWorks，请在浏览器中扫码或输入密码登录")

        for i in range(timeout // 3):
            await asyncio.sleep(3)
            if await self.check_logged_in():
                logger.info("检测到登录成功（耗时约 %ds）", i * 3)
                return True

            if i % 10 == 9:
                logger.info("仍在等待登录... (%ds/%ds)", (i + 1) * 3, timeout)

        logger.warning("登录等待超时")
        return False

    async def extract_cookies_via_cdp(self) -> str:
        """通过 CDP Network.getCookies 提取全部 Cookie（含 httpOnly）。"""
        await self._ensure_connected()
        if not self._page:
            pages = self._browser.contexts[0].pages if self._browser.contexts else []
            if not pages:
                return ""
            self._page = pages[0]

        current_url = await self._page.evaluate("document.location.href")
        logger.debug("CDP Cookie 提取 — 当前页面: %s", current_url[:80])

        cdp_session = await self._browser.contexts[0].new_cdp_session(self._page)
        try:
            cookies = await cdp_session.send("Network.getCookies")
        finally:
            await cdp_session.detach()

        parts = [f"{c['name']}={c['value']}" for c in cookies.get("cookies", [])]
        return "; ".join(parts)

    async def create_node_via_dom(self, parent_dir: str, node_name: str) -> str:
        """在 IDE 中创建新节点，返回 UUID。"""
        async with self._lock:
            await self.get_ide_page()
            sel = self._selectors["selectors"]
            try:
                await self._page.click(sel["ide_new_file_btn"], timeout=5000)
            except Exception:
                await self._page.click(sel["fallback_create_node"], timeout=5000)
            await asyncio.sleep(0.5)
            try:
                await self._page.click(sel["ide_new_maxcompute_sql"], timeout=5000)
            except Exception:
                await self._page.click("text=MaxCompute SQL", timeout=5000)
            await asyncio.sleep(0.5)
            await self._page.fill(sel["ide_node_name_input"], node_name)
            await self._page.click(sel["ide_confirm_btn"])
            await asyncio.sleep(2)
            return await self._extract_node_uuid(node_name)

    async def _extract_node_uuid(self, node_name: str) -> str:
        await self._ensure_connected()
        uuid: str = ""

        async def _on_response(response):
            nonlocal uuid
            if "getVertex" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    content = data.get("data", {}).get("content", "")
                    if node_name.lower() in str(content).lower():
                        uuid = response.url.split("uuid=")[-1]
                except Exception:
                    pass

        self._page.on("response", _on_response)
        await self._page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(3)
        self._page.remove_listener("response", _on_response)
        return uuid

    async def format_and_save(self) -> None:
        async with self._lock:
            await self._ensure_connected()
            await self._page.keyboard.press("Shift+Alt+F")
            await asyncio.sleep(1)
            await self._page.keyboard.press("Control+s")
            await asyncio.sleep(0.5)

    async def refresh_page(self) -> None:
        async with self._lock:
            await self._ensure_connected()
            await self._page.reload(wait_until="domcontentloaded")
            await asyncio.sleep(2)

    async def element_exists(self, selector: str) -> bool:
        try:
            await self._ensure_connected()
            return await self._page.query_selector(selector) is not None
        except Exception:
            return False
