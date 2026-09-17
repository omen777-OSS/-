#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智诊通 · AI智能问诊 - API代理服务器
支持两种运行方式：
  1. 本地运行：双击 启动智诊通.bat，局域网内手机/电脑可访问
  2. 云端部署：部署到 Render/Railway 等平台，任何人手机打开网址即可使用
     环境变量：LLM_API_KEY（必填）、LLM_BASE_URL（可选）、LLM_MODEL（可选）
"""
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import socket

# 云平台会注入 PORT 环境变量；本地默认 8765
PORT = int(os.environ.get('PORT', 8765))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
HTML_FILE = os.path.join(BASE_DIR, 'zhizhentong.html')

# 判断是否在云端环境（有 PORT 环境变量、无交互终端、或平台标识）
IS_CLOUD = (
    os.environ.get('PORT') is not None
    or os.environ.get('RENDER') is not None
    or os.environ.get('RAILWAY_ENVIRONMENT') is not None
    or os.environ.get('DYNO') is not None
    or not sys.stdin.isatty()
)

DEFAULT_CONFIG = {
    'baseUrl': 'https://api.deepseek.com/v1',
    'apiKey': '',
    'model': 'deepseek-chat',
    'mode': 'llm-first'
}


def load_config():
    """加载配置：环境变量（云端）> config.json（本地）> 默认值"""
    cfg = DEFAULT_CONFIG.copy()

    # 1. 从 config.json 读取（本地部署）
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                file_cfg = json.load(f)
                for k, v in file_cfg.items():
                    if v:
                        cfg[k] = v
        except Exception:
            pass

    # 2. 环境变量优先级最高（云端部署，密钥不写在代码/文件里）
    if os.environ.get('LLM_API_KEY'):
        cfg['apiKey'] = os.environ['LLM_API_KEY'].strip()
    if os.environ.get('LLM_BASE_URL'):
        cfg['baseUrl'] = os.environ['LLM_BASE_URL'].strip()
    if os.environ.get('LLM_MODEL'):
        cfg['model'] = os.environ['LLM_MODEL'].strip()

    return cfg


def save_config(cfg):
    """保存配置到 config.json（云端文件系统是临时的，此操作在云端无效但不报错）"""
    if IS_CLOUD:
        # 云端不保存到文件（重启会丢失），密钥应通过环境变量配置
        return
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  {args[0]}")

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/index.html'):
            self._serve_html()
        elif path == '/api/config':
            self._serve_config()
        elif path == '/api/models':
            self._proxy_models()
        elif path == '/api/health':
            self._json({'ok': True, 'proxy': True, 'cloud': IS_CLOUD})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/api/chat':
            self._proxy_chat()
        elif path == '/api/config':
            self._save_config_handler()
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        try:
            with open(HTML_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self._cors()
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        except FileNotFoundError:
            self._json({'error': 'zhizhentong.html not found'}, 404)

    def _serve_config(self):
        cfg = load_config()
        public = {
            'baseUrl': cfg['baseUrl'],
            'model': cfg['model'],
            'mode': cfg['mode'],
            'hasKey': bool(cfg['apiKey']),
            'keyMasked': (cfg['apiKey'][:6] + '...' + cfg['apiKey'][-4:]) if cfg['apiKey'] else '',
            'proxy': True,
            'cloud': IS_CLOUD
        }
        self._json(public)

    def _save_config_handler(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            cfg = load_config()
            if 'baseUrl' in data:
                cfg['baseUrl'] = data['baseUrl'].strip()
            if 'model' in data:
                cfg['model'] = data['model'].strip()
            if 'mode' in data:
                cfg['mode'] = data['mode']
            if data.get('apiKey'):
                cfg['apiKey'] = data['apiKey'].strip()
            if data.get('clearKey'):
                cfg['apiKey'] = ''
            save_config(cfg)
            self._json({'ok': True, 'cloud': IS_CLOUD})
        except Exception as e:
            self._json({'ok': False, 'error': str(e)}, 500)

    def _forward(self, url, method='GET', body=None):
        cfg = load_config()
        headers = {
            'Authorization': 'Bearer ' + cfg['apiKey'],
            'Content-Type': 'application/json'
        }
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=90) as resp:
                return resp.status, resp.read()
        except HTTPError as e:
            return e.code, e.read()
        except URLError as e:
            return 502, json.dumps({'error': {'message': '上游连接失败: ' + str(e.reason)}}).encode()
        except Exception as e:
            return 500, json.dumps({'error': {'message': str(e)}}).encode()

    def _proxy_models(self):
        cfg = load_config()
        if not cfg['apiKey']:
            self._json({'error': '未配置 API 密钥'}, 400)
            return
        url = cfg['baseUrl'].rstrip('/') + '/models'
        status, body = self._forward(url)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _proxy_chat(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            cfg = load_config()
            if not cfg['apiKey']:
                self._json({'error': {'message': '服务端未配置 API 密钥' + ('，请在平台环境变量中设置 LLM_API_KEY' if IS_CLOUD else '，请在设置中配置')}}, 400)
                return
            data['model'] = cfg['model']
            url = cfg['baseUrl'].rstrip('/') + '/chat/completions'
            status, body = self._forward(url, method='POST', body=json.dumps(data, ensure_ascii=False).encode('utf-8'))
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._json({'error': {'message': str(e)}}, 500)


def main():
    cfg = load_config()

    if IS_CLOUD:
        # ===== 云端部署模式 =====
        print("=" * 60)
        print("  智诊通 · AI智能问诊 — 云端服务启动")
        print("=" * 60)
        print(f"  端口：{PORT}")
        print(f"  接口：{cfg['baseUrl']}")
        print(f"  模型：{cfg['model']}")
        print(f"  密钥：{'已配置 (环境变量 LLM_API_KEY)' if cfg['apiKey'] else '⚠️  未配置！请设置环境变量 LLM_API_KEY'}")
        print("=" * 60)
        if not cfg['apiKey']:
            print("  ⚠️  警告：未检测到 API 密钥，大模型功能将不可用。")
            print("     请在平台环境变量中设置 LLM_API_KEY。")
            print("=" * 60)
    else:
        # ===== 本地运行模式 =====
        print()
        print("=" * 62)
        print("   智诊通 · AI智能问诊  —  本地服务启动中...")
        print("=" * 62)

        if not cfg['apiKey']:
            print()
            print("  [首次配置] 检测到未配置 API 密钥")
            print("  请粘贴您的 API 密钥（仅保存在本机 config.json）：")
            print("  （直接回车可跳过，稍后在页面设置中配置）")
            try:
                key = input("  > ").strip()
                if key:
                    cfg['apiKey'] = key
                    save_config(cfg)
                    print("  ✅ 密钥已保存")
            except Exception:
                pass

        print()
        print("  当前配置：")
        print(f"    接口：{cfg['baseUrl']}")
        print(f"    模型：{cfg['model']}")
        print(f"    密钥：{'已配置' if cfg['apiKey'] else '⚠️  未配置'}")

    try:
        server = HTTPServer(('0.0.0.0', PORT), ProxyHandler)
    except OSError as e:
        print(f"\n  ❌ 端口 {PORT} 被占用：{e}")
        if not IS_CLOUD:
            print("  请关闭占用该端口的程序后重试，或修改脚本中的 PORT 值。")
            input("\n  按回车键退出...")
        return

    if not IS_CLOUD:
        lan_ip = get_lan_ip()
        local_url = f"http://127.0.0.1:{PORT}"
        lan_url = f"http://{lan_ip}:{PORT}"
        print()
        print("=" * 62)
        print("   ✅ 服务已启动！")
        print("=" * 62)
        print(f"   本机访问：      {local_url}")
        print(f"   手机/其他电脑： {lan_url}")
        print("                    （需连接同一 WiFi / 局域网）")
        print()
        print("   💡 如需让任何人在任何地方使用，请部署到云端（见部署指南）")
        print("   按 Ctrl+C 停止服务")
        print("=" * 62)
        print()
        try:
            import webbrowser
            webbrowser.open(local_url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务已停止")
        server.server_close()


if __name__ == '__main__':
    main()
