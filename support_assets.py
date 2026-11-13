"""Author-supplied receipts bundled with the app, never user-editable settings."""
from pathlib import Path
import hashlib

AUTHOR_NAME = '汪同学'
AUTHOR_GITHUB = 'wwwwwwjy'
ASSET_ROOT = Path(__file__).resolve().parent / 'web' / 'assets'
SUPPORT_ASSETS = {
    '/assets/author-alipay.png': {
        'file': 'author-alipay.png', 'type': 'image/png', 'label': '支付宝',
        'sha256': '7a4ee0f2e2a71d0cf5877046f5d1ed020eeb1da03dcb325190c322f7ca009e4c',
    },
    '/assets/author-wechat.png': {
        'file': 'author-wechat.png', 'type': 'image/png', 'label': '微信',
        'sha256': 'f4e86581f176d22a0abe726f10ca826019ae4eb650f8044c85fdaa47c017a5d8',
    },
}


def read_support_asset(route):
    """Exact route whitelist plus integrity check; no uploads, URL or path input."""
    asset = SUPPORT_ASSETS[route]
    path = ASSET_ROOT / asset['file']
    if path.is_symlink():
        raise ValueError('作者收款码资源校验失败，请重新安装官方发布版本。')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != asset['sha256']:
        raise ValueError('作者收款码资源校验失败，请重新安装官方发布版本。')
    return data, asset['type']


def verify_support_assets():
    for route in SUPPORT_ASSETS:
        read_support_asset(route)
    return {asset['file']: asset['sha256'] for asset in SUPPORT_ASSETS.values()}
