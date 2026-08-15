from app.services.platforms import OTHER_PLATFORM, platform_for_url


def test_recognizes_known_platform_hosts_and_subdomains():
    assert platform_for_url("https://www.zhihu.com/question/1") == "知乎"
    assert platform_for_url("https://www.xiaohongshu.com/explore/1") == "小红书"
    assert platform_for_url("https://youtu.be/abc") == "YouTube"
    assert platform_for_url("https://old.reddit.com/r/python") == "Reddit"


def test_unknown_or_lookalike_domains_are_other():
    assert platform_for_url("https://programmercarl.com/") == OTHER_PLATFORM
    assert platform_for_url("https://youtube.com.example.org/watch") == OTHER_PLATFORM
