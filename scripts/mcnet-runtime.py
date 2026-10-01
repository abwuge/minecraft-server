#!/usr/bin/env python3
"""启动时应用群组服配置，并管理三个子服共用的白名单。"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

SERVICES = ('main', 'mirror', 'create')
SHARED = Path('/whitelist')
DATA = Path('/data')
HOST = Path('/mcnet-host')


def boolean(value):
    if str(value).lower() not in ('true', 'false'):
        raise ValueError(f'布尔设置应为 true 或 false: {value}')
    return str(value).lower() == 'true'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


@contextmanager
def whitelist_lock():
    SHARED.mkdir(parents=True, exist_ok=True)
    with (SHARED / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def set_field(path, key, value, separator='='):
    text = path.read_text() if path.exists() else ''
    pattern = rf'(?m)^\s*{re.escape(key)}\s*{re.escape(separator)}[^\n]*$'
    replacement = f'{key}{separator}{value}'
    if re.search(pattern, text):
        text = re.sub(pattern, lambda _: replacement, text)
    else:
        text = text.rstrip() + '\n' + replacement + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def set_yaml(path, keys, value):
    """只更新指定的映射键，保留其它设置和注释。"""
    lines = path.read_text().splitlines() if path.exists() else []
    start, end = 0, len(lines)
    indent = 0
    for depth, key in enumerate(keys):
        found = next((i for i in range(start, end)
                      if re.match(rf'^{" " * indent}{re.escape(key)}\s*:', lines[i])), None)
        if found is None:
            lines.insert(end, ' ' * indent + key + (': ' + value if depth == len(keys) - 1 else ':'))
            found = end
            end += 1
        elif depth == len(keys) - 1:
            lines[found] = ' ' * indent + key + ': ' + value
        if depth < len(keys) - 1:
            start = found + 1
            end = next((i for i in range(start, end)
                        if lines[i].strip() and not lines[i].lstrip().startswith('#')
                        and len(lines[i]) - len(lines[i].lstrip()) <= indent), end)
            indent += 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')


def prepare_proxy():
    online = boolean(os.environ.get('ONLINE_MODE', 'true'))
    set_field(DATA / 'velocity.toml', 'online-mode', str(online).lower(), ' = ')
    set_field(DATA / 'velocity.toml', 'force-key-authentication', str(online).lower(), ' = ')
    geyser = DATA / 'plugins/Geyser-Velocity/config.yml'
    if not geyser.exists():
        geyser.parent.mkdir(parents=True, exist_ok=True)
        geyser.write_text('config-version: 8\nbedrock:\n  address: 0.0.0.0\n  port: 19132\n')
    set_yaml(geyser, ['java', 'auth-type'], 'floodgate')
    set_yaml(geyser, ['advanced', 'floodgate-key-file'], '/data/plugins/floodgate/key.pem')
    floodgate = DATA / 'plugins/floodgate/config.yml'
    if not floodgate.exists():
        jar = next((DATA / 'plugins').glob('*floodgate*.jar'))
        with zipfile.ZipFile(jar) as archive:
            text = archive.read('config.yml').decode().replace('${metrics.uuid}', str(uuid.uuid4()))
        floodgate.parent.mkdir(parents=True, exist_ok=True)
        floodgate.write_text(text)
    set_yaml(floodgate, ['username-prefix'], '"."')
    set_yaml(floodgate, ['replace-spaces'], 'true')
    set_yaml(floodgate, ['player-link', 'require-link'], 'false')


def offline_uuid(name):
    return str(uuid.UUID(bytes=hashlib.md5(('OfflinePlayer:' + name).encode()).digest(), version=3))


def load_players():
    path = SHARED / 'players.json'
    players = json.loads(path.read_text()) if path.exists() else []
    canonical = SHARED / 'whitelist.json'
    if canonical.exists():
        identities = {entry['uuid'] for entry in json.loads(canonical.read_text())}
        players = [p for p in players if p.get('uuid') in identities or
                   p.get('online_uuid') in identities or
                   (p['platform'] == 'java' and offline_uuid(p['name']) in identities)]
    return players


def import_entries(players, entries):
    known = ({p.get('uuid') for p in players} | {p.get('online_uuid') for p in players} |
             {offline_uuid(p['name']) for p in players if p['platform'] == 'java'})
    for entry in entries:
        identity = str(uuid.UUID(entry['uuid']))
        if identity in known:
            continue
        bedrock = entry['name'].startswith('.') or identity.startswith('00000000-0000-0000-')
        record = {'platform': 'bedrock' if bedrock else 'java', 'name': entry['name'], 'uuid': identity}
        if not bedrock:
            record['online_uuid'] = identity
        players.append(record)
        known.add(identity)


def render_whitelist(players, online):
    result = {}
    for player in players:
        if player['platform'] == 'java':
            identity = player.get('online_uuid') if online else offline_uuid(player['name'])
            if not identity:
                profile = get_json('https://api.mojang.com/users/profiles/minecraft/' +
                                   urllib.parse.quote(player['name'], safe=''))
                identity = str(uuid.UUID(profile['id']))
                player['online_uuid'] = identity
                player['name'] = profile['name']
        else:
            identity = player['uuid']
        result[identity] = {'uuid': identity, 'name': player['name']}
        # 旧白名单无法区分 Java 身份与已绑定 Java 的基岩版身份。
        if not online and player['platform'] == 'java' and player.get('online_uuid'):
            original = player['online_uuid']
            result[original] = {'uuid': original, 'name': player['name']}
    return list(result.values())


def save_players(players, online):
    entries = render_whitelist(players, online)
    write_json(SHARED / 'players.json', players)
    write_json(SHARED / 'whitelist.json', entries)


def import_server_whitelist(path):
    players = load_players()
    if path.exists() and not path.is_symlink():
        import_entries(players, json.loads(path.read_text()))
    canonical = SHARED / 'whitelist.json'
    if canonical.exists():
        import_entries(players, json.loads(canonical.read_text()))
    save_players(players, boolean(os.environ.get('ONLINE_MODE', 'true')))
    if path.is_symlink() or path.exists():
        path.unlink()
    path.symlink_to('../../whitelist/whitelist.json')


def prepare_prime_backup():
    path = DATA / 'config/prime_backup/config.json'
    if not path.exists():
        return
    config = json.loads(path.read_text())
    patterns = config.get('server', {}).get('saved_world_regex', [])
    message = 'System chat: Saved the game'
    # 新版 MC 给保存提示加了前缀；PB 对提示做全串匹配。
    if (any(re.fullmatch(p, 'Saved the game') for p in patterns)
            and not any(re.fullmatch(p, message) for p in patterns)):
        patterns.append(message)
        write_json(path, config)


def prepare_mirror(connection_path=Path('/mcnet-mirror/connection.json')):
    path = DATA / 'config/mirror_mcsmcdr/config.json'
    pattern = '^(?:System chat: )?Saved the game$'
    if not path.exists():
        # 插件在首次加载时补齐其它默认值，包括关闭控制接口。
        config = {'!!mirror': {'command': {'action': {'sync': {
            'save_world': {'saved_world_regex': pattern}
        }}}}}
    else:
        config = json.loads(path.read_text())
    original = json.dumps(config) if path.exists() else None
    changed = False
    for mirror in config.values():
        save = mirror.get('command', {}).get('action', {}).get('sync', {}).get('save_world', {})
        if save.get('saved_world_regex') == '^Saved the game$':
            save['saved_world_regex'] = pattern
            changed = True
    if os.environ.get('SERVER_NAME') == 'main' and connection_path.exists():
        mirror = config.setdefault('!!mirror', {})
        mirror['mcsm'] = json.loads(connection_path.read_text())
        sync = mirror.setdefault('sync', {})
        sync.setdefault('source', './server')
        sync['target'] = ['/mirror/server']
        if not sync.get('world') or sync['world'] == ['world']:
            props = DATA / 'server/server.properties'
            match = re.search(r'(?m)^level-name=(.+)$', props.read_text()) if props.exists() else None
            sync['world'] = [match.group(1).strip() if match else 'world']
    if changed or json.dumps(config) != original:
        write_json(path, config)
        path.chmod(0o600)


def prepare_server():
    online = boolean(os.environ.get('ONLINE_MODE', 'true'))
    enabled = boolean(os.environ.get('WHITE_LIST', str(online).lower()))
    server = DATA / 'server'
    set_field(server / 'server.properties', 'white-list', str(enabled).lower())
    set_field(server / 'server.properties', 'enforce-whitelist', str(enabled).lower())
    set_field(server / 'server.properties', 'rcon.password', os.environ['RCON_PASSWORD'])
    set_field(server / 'config/FabricProxy-Lite.toml', 'hackOnlineMode', str(online).lower(), ' = ')
    set_field(server / 'config/FabricProxy-Lite.toml', 'secret',
              json.dumps(os.environ['VELOCITY_FORWARDING_SECRET']), ' = ')
    with whitelist_lock():
        import_server_whitelist(server / 'whitelist.json')
    prepare_prime_backup()
    prepare_mirror()


def get_json(url, missing=False):
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'mcnet/1.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            if missing and response.status == 204:
                return None
            return json.load(response)
    except urllib.error.HTTPError as error:
        if missing and error.code in (204, 404):
            return None
        raise RuntimeError(f'身份查询失败（HTTP {error.code}），白名单未改动') from None


def lookup_player(platform, name, xuid=None):
    if platform == 'java':
        if not re.fullmatch(r'[A-Za-z0-9_]{1,16}', name):
            raise ValueError('Java 玩家名称应为 1–16 位字母、数字或下划线')
        record = {'platform': 'java', 'name': name}
        if boolean(os.environ.get('ONLINE_MODE', 'true')):
            profile = get_json('https://api.mojang.com/users/profiles/minecraft/' + name)
            record.update(name=profile['name'], online_uuid=str(uuid.UUID(profile['id'])))
        return record
    gamertag = name.removeprefix('.').replace('_', ' ')
    if not 1 <= len(gamertag) <= 16 or '\n' in gamertag or '\r' in gamertag:
        raise ValueError('请提供有效的 Xbox Gamertag')
    xuid = int(xuid) if xuid else int(get_json('https://api.geysermc.org/v2/xbox/xuid/' +
                                             urllib.parse.quote(gamertag, safe=''))['xuid'])
    if not 0 < xuid < 2**64:
        raise ValueError('XUID 超出范围')
    link = get_json(f'https://api.geysermc.org/v2/link/bedrock/{xuid}', missing=True)
    if link:
        identity = str(uuid.UUID(link['java_id']))
        display_name = link['java_name']
    else:
        identity = str(uuid.UUID(int=xuid))
        display_name = '.' + gamertag.replace(' ', '_')
    return {'platform': 'bedrock', 'name': display_name, 'gamertag': gamertag,
            'xuid': str(xuid), 'uuid': identity}


def receive(sock):
    def exact(length):
        data = b''
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError('RCON 连接已关闭')
            data += chunk
        return data
    size = struct.unpack('<i', exact(4))[0]
    if not 10 <= size <= 1048576:
        raise ConnectionError('RCON 返回无效数据')
    packet = exact(size)
    identity, kind = struct.unpack('<ii', packet[:8])
    return identity, kind, packet[8:-2].decode(errors='replace')


def rcon(service, command):
    def send(sock, identity, kind, text):
        payload = struct.pack('<ii', identity, kind) + text.encode() + b'\0\0'
        sock.sendall(struct.pack('<i', len(payload)) + payload)
    with socket.create_connection((service, 25575), timeout=8) as sock:
        send(sock, 1, 3, os.environ['RCON_PASSWORD'])
        for _ in range(3):
            identity, kind, _ = receive(sock)
            if identity == -1:
                raise RuntimeError('RCON 密码验证失败')
            if kind == 2:
                break
        else:
            raise RuntimeError('RCON 没有返回认证结果')
        send(sock, 2, 2, command)
        identity, _, output = receive(sock)
        if identity != 2:
            raise RuntimeError('RCON 响应不匹配')
        return output


def reload_servers(enabled=None):
    failed = []
    for service in SERVICES:
        try:
            if enabled is not None:
                rcon(service, 'whitelist ' + ('on' if enabled else 'off'))
            rcon(service, 'whitelist reload')
            print(f'{service}: 白名单已同步')
        except OSError as error:
            # 已停止的子服会在下一次启动时读取共享白名单。
            print(f'{service}: 下次启动时应用（{error.strerror or type(error).__name__}）')
            failed.append(service)
    return failed


def update_env(values):
    path = HOST / '.env'
    for key, value in values.items():
        set_field(path, key, value)
    path.chmod(0o600)


def whitelist(action, platform=None, name=None, xuid=None):
    online = boolean(os.environ.get('ONLINE_MODE', 'true'))
    with whitelist_lock():
        players = load_players()
        path = SHARED / 'whitelist.json'
        if path.exists():
            import_entries(players, json.loads(path.read_text()))
        if action == 'list':
            print('白名单: ' + ('开启' if boolean(os.environ.get('WHITE_LIST', str(online).lower())) else '关闭'))
            for player in players:
                print(f'{player["platform"]}: {player.get("gamertag", player["name"])}')
            return
        if action in ('add', 'remove'):
            if not platform or not name:
                raise ValueError('用法: whitelist add|remove java|bedrock 玩家名称 [--xuid XUID]')
            key = name.removeprefix('.').replace('_', ' ').lower() if platform == 'bedrock' else name.lower()
            matches = [p for p in players if p['platform'] == platform and
                       (p.get('gamertag', p['name']).removeprefix('.').replace('_', ' ').lower()
                        if platform == 'bedrock' else p['name'].lower()) == key]
            if action == 'add':
                if not matches:
                    players.append(lookup_player(platform, name, xuid))
            else:
                players = [p for p in players if p not in matches]
        if action == 'sync':
            players = [lookup_player(p['platform'], p.get('gamertag', p['name']), p.get('xuid'))
                       if p['platform'] == 'bedrock' and p.get('xuid') else p for p in players]
        save_players(players, online)
        enabled = None
        if action in ('on', 'off'):
            enabled = action == 'on'
            update_env({'WHITE_LIST': str(enabled).lower()})
            for service in SERVICES:
                props = HOST / 'data' / service / 'server/server.properties'
                if props.exists():
                    set_field(props, 'white-list', str(enabled).lower())
                    set_field(props, 'enforce-whitelist', str(enabled).lower())
    reload_servers(enabled)


def mode(value):
    if value == 'status':
        print('认证模式: ' + ('online' if boolean(os.environ.get('ONLINE_MODE', 'true')) else 'offline'))
        return
    online = value == 'online'
    with whitelist_lock():
        players = load_players()
        save_players(players, online)
        update_env({'ONLINE_MODE': str(online).lower(), 'WHITE_LIST': str(online).lower()})
    print('认证模式: ' + value + '；白名单默认' + ('开启' if online else '关闭'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare-proxy')
    sub.add_parser('prepare-server')
    modes = sub.add_parser('mode')
    modes.add_argument('value', choices=('online', 'offline', 'status'))
    lists = sub.add_parser('whitelist')
    lists.add_argument('action', choices=('list', 'add', 'remove', 'on', 'off', 'sync'))
    lists.add_argument('platform', choices=('java', 'bedrock'), nargs='?')
    lists.add_argument('name', nargs='?')
    lists.add_argument('--xuid')
    args = parser.parse_args()
    if args.command == 'prepare-proxy':
        prepare_proxy()
    elif args.command == 'prepare-server':
        prepare_server()
    elif args.command == 'mode':
        mode(args.value)
    else:
        whitelist(args.action, args.platform, args.name, args.xuid)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f'[error] {error}', file=sys.stderr)
        sys.exit(1)
