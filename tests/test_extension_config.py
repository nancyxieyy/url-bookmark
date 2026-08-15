import json
from pathlib import Path


EXTENSION_DIR = Path(__file__).resolve().parent.parent / "extension"


def test_extension_uses_storage_and_least_privilege_hosts():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())

    assert "storage" in manifest["permissions"]
    assert "scripting" in manifest["permissions"]
    assert "activeTab" in manifest["permissions"]
    assert "<all_urls>" not in manifest.get("host_permissions", [])
    assert manifest["host_permissions"] == [
        "https://url-bookmark.onrender.com/*"
    ]
    assert set(manifest["optional_host_permissions"]) == {
        "http://*/*",
        "https://*/*",
    }
    assert manifest["options_page"] == "options.html"

    capture = (EXTENSION_DIR / "capture.js").read_text()
    assert "document.cookie" not in capture
    assert "localStorage" not in capture
    assert "sessionStorage" not in capture
    assert '"form", "input", "textarea"' in capture
    assert (EXTENSION_DIR / "vendor" / "Readability.js").is_file()
    assert (EXTENSION_DIR / "vendor" / "turndown.js").is_file()
    assert "[contenteditable]" in capture


def test_extension_requests_bearer_without_hardcoded_popup_server():
    popup = (EXTENSION_DIR / "popup.js").read_text()
    background = (EXTENSION_DIR / "background.js").read_text()
    settings = (EXTENSION_DIR / "settings.js").read_text()

    assert "chrome.storage.local" in settings
    assert "Authorization" in settings
    assert "url-bookmark.onrender.com" not in popup
    assert "url-bookmark.onrender.com" not in background
    assert "API Token 无效" in popup
    assert "API Token 无效" in background
    assert "/api/bookmarks/preview" not in popup
    assert "browser-tag-suggestions" in popup
