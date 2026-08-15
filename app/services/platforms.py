from urllib.parse import urlparse


OTHER_PLATFORM = "其他"

# The first matching domain wins. Subdomains are included automatically.
PLATFORM_DOMAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("知乎", ("zhihu.com",)),
    ("小红书", ("xiaohongshu.com", "xhslink.com")),
    ("YouTube", ("youtube.com", "youtu.be")),
    ("Reddit", ("reddit.com", "redd.it")),
    ("哔哩哔哩", ("bilibili.com", "b23.tv")),
    ("GitHub", ("github.com", "github.io")),
    ("微信公众号", ("mp.weixin.qq.com",)),
    ("微博", ("weibo.com", "weibo.cn")),
    ("抖音", ("douyin.com",)),
    ("快手", ("kuaishou.com",)),
    ("豆瓣", ("douban.com",)),
    ("掘金", ("juejin.cn",)),
    ("CSDN", ("csdn.net",)),
    ("博客园", ("cnblogs.com",)),
    ("简书", ("jianshu.com",)),
    ("Medium", ("medium.com",)),
    ("Stack Overflow", ("stackoverflow.com", "stackexchange.com")),
    ("LinkedIn", ("linkedin.com",)),
    ("X", ("x.com", "twitter.com")),
    ("TikTok", ("tiktok.com",)),
    ("Twitch", ("twitch.tv",)),
    ("Vimeo", ("vimeo.com",)),
    ("Quora", ("quora.com",)),
)

KNOWN_PLATFORMS = tuple(name for name, _ in PLATFORM_DOMAINS)


def platform_for_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    for platform, domains in PLATFORM_DOMAINS:
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            return platform
    return OTHER_PLATFORM
