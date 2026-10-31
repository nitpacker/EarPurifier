"""
EarPurifier - GitHub Release Auto-Update Checker.
Provides resilient SemVer comparisons, bilingual changelog extraction,
frequency throttling, raw release manifest parsing, and non-blocking background polling.
"""

import re
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any, Union

import requests
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

APP_VERSION = "0.0.1"
GITHUB_OWNER = "nitpacker"
GITHUB_REPO = "EarPurifier"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
MANIFEST_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/releases/latest.json"
CHECK_INTERVAL_SECONDS = 86400  # 24 hours


def get_current_os() -> str:
    """
    Detects current operating system.
    Returns: 'windows', 'macos', or 'linux'.
    """
    if sys.platform.startswith("win"):
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    elif sys.platform.startswith("linux"):
        return "linux"
    return "windows"


# ─── Semantic Version Parsing & Comparison ────────────────────────────────────

try:
    from packaging.version import parse as _packaging_parse, Version as _PackagingVersion
    _HAS_PACKAGING = True
except ImportError:
    _HAS_PACKAGING = False


def _fallback_parse_semver(v_str: str) -> Tuple[int, int, int, int, tuple]:
    """
    Pure-Python SemVer 2.0.0 parser fallback.
    Returns: (major, minor, patch, is_prerelease_flag, prerelease_tokens)
    In SemVer: A release without prerelease tags has higher precedence than with prerelease tags.
    Hence: is_prerelease_flag = 1 for normal releases, 0 for prereleases.
    """
    cleaned = v_str.strip().lstrip("vV")
    pattern = r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"
    m = re.match(pattern, cleaned)
    if not m:
        # Extreme fallback: extract all integer segments
        digits = [int(d) for d in re.findall(r"\d+", cleaned)]
        major = digits[0] if len(digits) > 0 else 0
        minor = digits[1] if len(digits) > 1 else 0
        patch = digits[2] if len(digits) > 2 else 0
        return (major, minor, patch, 1, ())

    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2) is not None else 0
    patch = int(m.group(3)) if m.group(3) is not None else 0
    prerelease = m.group(4)

    if prerelease:
        is_prerelease = 0
        tokens = []
        for part in prerelease.split("."):
            if part.isdigit():
                tokens.append((1, int(part)))
            else:
                tokens.append((0, part))
        prerelease_tokens = tuple(tokens)
    else:
        is_prerelease = 1
        prerelease_tokens = ()

    return (major, minor, patch, is_prerelease, prerelease_tokens)


def is_newer_version(remote_ver: str, current_ver: str = APP_VERSION) -> bool:
    """
    Compares remote_ver against current_ver.
    Returns True if and only if remote_ver > current_ver according to SemVer rules.
    """
    if not remote_ver:
        return False

    r_clean = remote_ver.strip().lstrip("vV")
    c_clean = current_ver.strip().lstrip("vV")

    if r_clean == c_clean:
        return False

    if _HAS_PACKAGING:
        try:
            return _packaging_parse(r_clean) > _packaging_parse(c_clean)
        except Exception:
            pass

    # Use pure Python fallback parser
    return _fallback_parse_semver(r_clean) > _fallback_parse_semver(c_clean)


# ─── Bilingual Release Notes Extractor ────────────────────────────────────────

def extract_release_notes(body: Union[str, Dict[str, str], None], lang: str = "ar") -> str:
    """
    Extracts the localized release notes portion.
    Accepts:
    1. A dictionary: {"ar": "...", "en": "..."} (from releases/latest.json)
    2. A markdown string with HTML comment tags: <!-- ar -->...<!-- /ar -->
    3. A markdown string with bracket tags: [ar]...[/ar]
    4. A markdown string with section headers: '## العربية' / '## English'
    Falls back gracefully if language markers are not present.
    """
    if not body:
        return ""

    # Direct dictionary lookup
    if isinstance(body, dict):
        if lang in body and body[lang]:
            return str(body[lang]).strip()
        fallback_key = "en" if lang == "ar" else "ar"
        if fallback_key in body and body[fallback_key]:
            return str(body[fallback_key]).strip()
        # Return first available value
        for val in body.values():
            if val:
                return str(val).strip()
        return ""

    text = str(body).strip()

    # 1. Check HTML comments <!-- ar -->...<!-- /ar -->
    comment_pattern = rf"<!--\s*{lang}\s*-->([\s\S]*?)<!--\s*/{lang}\s*-->"
    m_comment = re.search(comment_pattern, text, re.IGNORECASE)
    if m_comment and m_comment.group(1).strip():
        return m_comment.group(1).strip()

    # 2. Check bracket tags [ar]...[/ar]
    bracket_pattern = rf"\[{lang}\]([\s\S]*?)\[/{lang}\]"
    m_bracket = re.search(bracket_pattern, text, re.IGNORECASE)
    if m_bracket and m_bracket.group(1).strip():
        return m_bracket.group(1).strip()

    # 3. Check Markdown section headers
    if lang == "ar":
        hdr_pattern = r"(?:^|\n)#{1,3}\s*(?:العربية|عربي|Arabic)([\s\S]*?)(?=(?:\n#{1,3}\s+[^\n]+)|\Z)"
    else:
        hdr_pattern = r"(?:^|\n)#{1,3}\s*(?:English|EN)([\s\S]*?)(?=(?:\n#{1,3}\s+[^\n]+)|\Z)"
    m_hdr = re.search(hdr_pattern, text, re.IGNORECASE)
    if m_hdr and m_hdr.group(1).strip():
        return m_hdr.group(1).strip()

    # 4. Fallback: Clean return of whole body
    return text


# ─── Startup Check Evaluation ─────────────────────────────────────────────────

def should_check_for_updates(config, force: bool = False) -> bool:
    """
    Evaluates whether an update check should proceed.
    - If force is True: always returns True.
    - If check_updates is False in config: returns False.
    - Otherwise returns True on every launch (no artificial 24h throttling).
    """
    if force:
        return True

    if config is None:
        return True

    return bool(config.get("check_updates", True))


# ─── Background Worker Thread ─────────────────────────────────────────────────

_ACTIVE_CHECKERS = set()

class GitHubUpdateChecker(QThread):
    """
    Non-blocking QThread worker for GitHub update checks.
    Prioritizes raw repo manifest (releases/latest.json), falling back to GitHub Releases API.
    Signals:
        sig_update_available(latest_version, release_notes, html_url, download_url)
        sig_check_finished(success, status_code_or_reason, message)
    """
    sig_update_available = Signal(str, object, str, str)
    sig_check_finished = Signal(bool, str, str)

    def __init__(self, config=None, force: bool = False, parent=None):
        super().__init__(parent)
        self.config = config
        self.force = force
        self._is_stopped = False
        _ACTIVE_CHECKERS.add(self)
        self.finished.connect(self._on_worker_finished)

    def _on_worker_finished(self):
        _ACTIVE_CHECKERS.discard(self)

    def stop(self):
        """Immediately requests worker to stop and forcefully terminates if running."""
        self._is_stopped = True
        self.requestInterruption()
        if self.isRunning():
            try:
                self.wait(500)
            except Exception:
                pass

    def run(self):
        if not should_check_for_updates(self.config, self.force):
            self.sig_check_finished.emit(True, "throttled", "Update check skipped (throttled)")
            return

        headers = {
            "User-Agent": f"EarPurifier/{APP_VERSION}",
            "Accept": "application/json, text/plain, */*",
        }

        # ── 1. Primary: Query raw releases/latest.json manifest (Zero rate limits) ──
        logger.debug(f"Checking raw releases manifest: {MANIFEST_RAW_URL}")
        try:
            raw_resp = requests.get(MANIFEST_RAW_URL, headers=headers, timeout=5)
            if raw_resp.status_code == 200:
                data = raw_resp.json()
                remote_ver = data.get("version", "").strip()
                if remote_ver:
                    messages = data.get("message", {})
                    os_name = get_current_os()
                    download_urls = data.get("download_urls")
                    if isinstance(download_urls, dict) and os_name in download_urls:
                        download_url = download_urls[os_name]
                    else:
                        download_url = data.get("download_url") or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
                    html_url = data.get("html_url") or download_url

                    if self.config is not None:
                        try:
                            self.config.set("last_update_check", datetime.now(timezone.utc).isoformat())
                        except Exception as e:
                            logger.debug(f"Failed to record last_update_check: {e}")

                    if self._is_stopped or self.isInterruptionRequested():
                        return

                    if is_newer_version(remote_ver, APP_VERSION):
                        logger.info(f"New EarPurifier update available from manifest: {remote_ver} (current: {APP_VERSION})")
                        self.sig_update_available.emit(remote_ver, messages, html_url, download_url)
                        self.sig_check_finished.emit(True, "update_available", remote_ver)
                    else:
                        logger.debug(f"EarPurifier is up-to-date: {APP_VERSION} (remote: {remote_ver})")
                        self.sig_check_finished.emit(True, "latest", remote_ver)
                    return
        except requests.Timeout:
            logger.debug("Raw manifest check timed out after 5s.")
        except Exception as e:
            logger.debug(f"Raw manifest query failed or unavailable, trying releases API: {e}")

        if self._is_stopped or self.isInterruptionRequested():
            return

        # ── 2. Fallback: Query GitHub Releases API ──
        logger.debug(f"Querying GitHub latest release API: {GITHUB_API_URL}")
        headers["Accept"] = "application/vnd.github.v3+json"
        try:
            resp = requests.get(GITHUB_API_URL, headers=headers, timeout=5)
        except requests.Timeout:
            logger.debug("GitHub release check timed out after 5 seconds.")
            self.sig_check_finished.emit(False, "timeout", "Connection timed out")
            return
        except requests.RequestException as e:
            logger.debug(f"GitHub release check network error: {e}")
            self.sig_check_finished.emit(False, "network_error", str(e))
            return
        except Exception as e:
            logger.debug(f"Unexpected error during GitHub update check: {e}")
            self.sig_check_finished.emit(False, "error", str(e))
            return

        if self.config is not None:
            try:
                self.config.set("last_update_check", datetime.now(timezone.utc).isoformat())
            except Exception as e:
                logger.debug(f"Failed to record last_update_check in config: {e}")

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception as e:
                logger.debug(f"Failed to decode GitHub API JSON response: {e}")
                self.sig_check_finished.emit(False, "invalid_json", "Malformed JSON response")
                return

            tag_name = data.get("tag_name", "")
            if not tag_name:
                self.sig_check_finished.emit(False, "no_tag", "No tag_name in response")
                return

            body = data.get("body", "")
            html_url = data.get("html_url", "")

            # Identify platform-specific binary asset if present
            os_name = get_current_os()
            if os_name == "macos":
                target_exts = (".dmg", ".pkg", ".zip")
            elif os_name == "linux":
                target_exts = (".appimage", ".tar.gz", ".deb")
            else:
                target_exts = (".exe", ".msi")

            download_url = html_url
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if any(name.endswith(ext) for ext in target_exts):
                    download_url = asset.get("browser_download_url", html_url)
                    break

            if self._is_stopped or self.isInterruptionRequested():
                return

            if is_newer_version(tag_name, APP_VERSION):
                logger.info(f"New EarPurifier update available: {tag_name} (current: {APP_VERSION})")
                self.sig_update_available.emit(tag_name, body, html_url, download_url)
                self.sig_check_finished.emit(True, "update_available", tag_name)
            else:
                logger.debug(f"EarPurifier is up-to-date: {APP_VERSION} (remote: {tag_name})")
                self.sig_check_finished.emit(True, "latest", tag_name)

        elif resp.status_code == 403:
            logger.debug("GitHub API rate limit exceeded (HTTP 403).")
            self.sig_check_finished.emit(False, "rate_limited", "Rate limit exceeded")
        elif resp.status_code == 404:
            logger.debug("GitHub release endpoint returned 404 (private repo or no releases yet).")
            self.sig_check_finished.emit(False, "not_found", "No public release found")
        else:
            logger.debug(f"GitHub release API returned HTTP {resp.status_code}: {resp.text[:200]}")
            self.sig_check_finished.emit(False, str(resp.status_code), f"HTTP {resp.status_code}")


def stop_all_active_checkers():
    """Forcefully stops and clears all registered GitHubUpdateChecker instances."""
    for checker in list(_ACTIVE_CHECKERS):
        try:
            checker.stop()
        except Exception:
            pass
    _ACTIVE_CHECKERS.clear()

