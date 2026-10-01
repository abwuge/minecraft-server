#!/usr/bin/env python3
"""安装和更新 MCSManager 管理的原生 Docker 实例。"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
from urllib.parse import quote, urlencode, urlparse

ROOT = Path('/mcnet-host')
GAMES = ('main', 'mirror', 'create', 'proxy')
PANELS = ('mcsm-daemon', 'mcsm-web')
SERVICES = (*GAMES, *PANELS, 'gateway')


class DockerError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Connection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__('localhost', timeout=240)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


class Docker:
    def request(self, method, path, data=None, raw=False):
        connection = Connection()
        try:
            body = json.dumps(data).encode() if data is not None else None
            connection.request(method, path, body, {'Content-Type': 'application/json'})
            response = connection.getresponse()
            payload = response.read()
            if response.status >= 400:
                try: message = json.loads(payload)['message']
                except (ValueError, KeyError): message = payload.decode(errors='replace')
                raise DockerError(response.status, message)
            return payload if raw else json.loads(payload) if payload else None
        finally:
            connection.close()

    def inspect(self, name):
        try: return self.request('GET', '/containers/' + quote(name, safe='') + '/json')
        except DockerError as error:
            if error.status == 404: return None
            raise

    def stop(self, name):
        info = self.inspect(name)
        if info and info['State']['Running']:
            try: self.request('POST', '/containers/' + name + '/stop?t=60')
            except DockerError as error:
                if error.status not in (304, 404): raise

    def remove(self, name):
        try: self.request('DELETE', '/containers/' + name)
        except DockerError as error:
            if error.status != 404:
                info = self.inspect(name)
                if error.status != 409 or (info and info['State']['Running']): raise

    def pull(self, image):
        print('[pull] ' + image, flush=True)
        payload = self.request('POST', '/images/create?' + urlencode({'fromImage': image}), raw=True)
        for line in payload.splitlines():
            item = json.loads(line)
            if 'error' in item: raise RuntimeError(item['error'])

    def image_id(self, image):
        return self.request('GET', '/images/' + quote(image, safe='') + '/json')['Id']

    def execute(self, name, command):
        result = self.request('POST', '/containers/' + name + '/exec', {
            'Cmd': command, 'AttachStdout': True, 'AttachStderr': True})
        output = self.request('POST', '/exec/' + result['Id'] + '/start',
                              {'Detach': False, 'Tty': False}, raw=True)
        text = demux(output).decode(errors='replace')
        status = self.request('GET', '/exec/' + result['Id'] + '/json')['ExitCode']
        if status: raise RuntimeError(text.strip() or 'Container command failed')
        return text


def demux(data):
    result = bytearray()
    while data:
        if len(data) < 8: raise RuntimeError('Incomplete Docker output')
        length = struct.unpack('>I', data[4:8])[0]
        if len(data) < 8 + length: raise RuntimeError('Incomplete Docker output frame')
        result.extend(data[8:8 + length])
        data = data[8 + length:]
    return bytes(result)


def read_env():
    result = {}
    for line in (ROOT / '.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            result[key.strip()] = value
    return result


def image(env, service):
    return env.get('IMAGE_' + service.upper().replace('-', '_')) or \
        f"ghcr.io/{env.get('GHCR_OWNER') or 'abwuge'}/mc-{service}:{env.get('IMAGE_TAG') or 'latest'}"


def game_changed(info, config, image_id):
    if not info or info.get('Image') != image_id: return True
    if info['Config'].get('Labels', {}).get('com.docker.compose.project'): return True
    if not info['Config'].get('Labels', {}).get('mcsmanager.instance.uuid'): return True
    actual_env = set(info['Config'].get('Env') or [])
    if not set(config['docker']['env']).issubset(actual_env): return True
    mounts = {m['Destination']: m['Source'] for m in info.get('Mounts', [])}
    for bind in config['docker']['extraVolumes']:
        source, target = bind.split('|', 1)
        if mounts.get(target) != source: return True
    if info['HostConfig']['NetworkMode'] != config['docker']['networkMode']: return True
    wanted_ports = {}
    for mapping in config['docker']['ports']:
        port, protocol = mapping.rsplit('/', 1)
        host, private = port.rsplit(':', 1)
        wanted_ports[private + '/' + protocol] = [{'HostIp': '', 'HostPort': host}]
    return (info['HostConfig'].get('PortBindings') or {}) != wanted_ports


def panel_ready(states, containers):
    if len(states) != len(GAMES): return False
    for state in states:
        info = containers.get(state['service'])
        if info and info['State']['Running'] and \
                info['Config'].get('Labels', {}).get('mcsmanager.instance.uuid') == state['id'] and \
                state['status'] != 3:
            return False
    return True


class Manager:
    def __init__(self, docker=None):
        self.docker = docker or Docker()
        self.env = read_env()
        self.env['TZ'] = self.env.get('TZ') or 'Asia/Shanghai'
        helper = self.docker.inspect(os.environ['HOSTNAME'])
        self.source = next(m['Source'] for m in helper['Mounts'] if m['Destination'] == '/mcnet-host')
        self.env.update(MCNET_DATA_PATH=self.source + '/data', MCNET_NETWORK=self.env.get('MCNET_NETWORK') or 'mcnet')
        existing = self.docker.inspect('mcnet-mcsm-daemon')
        if existing:
            data = next((m['Source'] for m in existing['Mounts'] if m['Destination'] == '/mcnet-data'), None)
            if data and data != self.env['MCNET_DATA_PATH']:
                raise ValueError('已有部署的数据目录为 ' + data + '，请在对应部署目录执行更新')

    def control(self, command, services=()):
        return self.docker.execute('mcnet-mcsm-daemon', ['node', '/opt/mcnet/control.cjs', command, *services])

    def wait(self, condition, description, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if condition(): return
            except (DockerError, RuntimeError): pass
            time.sleep(2)
        raise RuntimeError('等待超时: ' + description)

    def ensure_network(self):
        name = self.env['MCNET_NETWORK']
        try: self.docker.request('GET', '/networks/' + name)
        except DockerError as error:
            if error.status != 404: raise
            self.docker.request('POST', '/networks/create', {'Name': name, 'Driver': 'bridge'})

    def panel_spec(self, service):
        daemon = service == 'mcsm-daemon'
        data = self.env['MCNET_DATA_PATH']
        if daemon:
            environment = self.env
            mounts = [(data + '/mcsm/daemon/data', '/opt/mcsmanager/daemon/data'),
                      (data + '/mcsm/daemon/logs', '/opt/mcsmanager/daemon/logs'),
                      (data, '/mcnet-data'), (data, data),
                      (self.source + '/.env', '/mcnet-env'), ('/var/run/docker.sock', '/var/run/docker.sock')]
        else:
            environment = {k: v for k, v in self.env.items() if k.startswith('MCSM_')}
            environment['TZ'] = self.env.get('TZ') or 'Asia/Shanghai'
            mounts = [(data + '/mcsm/web/data', '/opt/mcsmanager/web/data'),
                      (data + '/mcsm/web/logs', '/opt/mcsmanager/web/logs'),
                      (data + '/mcsm/web/upload_files', '/opt/mcsmanager/web/public/upload_files'),
                      (data + '/mcsm/daemon/data', '/mcnet-daemon-data')]
        return {'Image': image(self.env, service), 'Env': [k + '=' + v for k, v in sorted(environment.items())],
                'HostConfig': {
                    'RestartPolicy': {'Name': 'unless-stopped'}, 'NetworkMode': self.env['MCNET_NETWORK'],
                    'ExtraHosts': ['host.docker.internal:host-gateway'],
                    'Mounts': [{'Type': 'bind', 'Source': source, 'Target': target,
                                'ReadOnly': target == '/mcnet-env'} for source, target in mounts] + self.timezone_mounts()}}

    def timezone_mounts(self):
        timezone = self.env.get('TZ') or 'Asia/Shanghai'
        return [{'Type': 'bind', 'Source': self.env['MCNET_DATA_PATH'] + '/timezone',
                 'Target': target, 'ReadOnly': True}
                for target in ('/etc/localtime', '/usr/share/zoneinfo/' + timezone)]

    def gateway_spec(self):
        hostname = urlparse(self.env.get('MCSM_PUBLIC_URL') or '').hostname or 'localhost'
        return {'Image': 'caddy:2-alpine', 'Env': ['MCSM_HOST=' + hostname, 'TZ=' + (self.env.get('TZ') or 'Asia/Shanghai')],
                'ExposedPorts': {'80/tcp': {}, '443/tcp': {}, '443/udp': {}}, 'HostConfig': {
                    'RestartPolicy': {'Name': 'unless-stopped'}, 'NetworkMode': self.env['MCNET_NETWORK'],
                    'PortBindings': {p: [{'HostPort': p.split('/')[0]}] for p in ('80/tcp', '443/tcp', '443/udp')},
                    'Mounts': [{'Type': 'bind', 'Source': self.source + '/config/gateway/Caddyfile',
                                'Target': '/etc/caddy/Caddyfile', 'ReadOnly': True},
                               {'Type': 'bind', 'Source': self.source + '/data/gateway/data', 'Target': '/data'},
                               {'Type': 'bind', 'Source': self.source + '/data/gateway/config', 'Target': '/config'}] + self.timezone_mounts()}}

    def ensure_panel(self, service):
        spec = self.gateway_spec() if service == 'gateway' else self.panel_spec(service)
        content = (ROOT / 'config/gateway/Caddyfile').read_text() if service == 'gateway' else ''
        digest = hashlib.sha256((json.dumps(spec, sort_keys=True) + content).encode()).hexdigest()
        name = 'mcnet-' + service
        existing = self.docker.inspect(name)
        if existing and (existing['Config'].get('Labels', {}).get('mcnet.config') != digest or
                         existing['Image'] != self.docker.image_id(spec['Image'])):
            self.docker.stop(name); self.docker.remove(name); existing = None
        if not existing:
            spec['Labels'] = {'mcnet.config': digest, 'mcnet.service': service}
            self.docker.request('POST', '/containers/create?name=' + name, spec)
        if not existing or not existing['State']['Running']:
            self.docker.request('POST', '/containers/' + name + '/start')

    def stop_game(self, service):
        name = 'mcnet-' + service
        self.docker.stop(name)
        self.docker.remove(name)
        self.wait(lambda: not self.docker.inspect(name) and
                  all(i['status'] == 0 for i in json.loads(self.control('status', [service]))),
                  service + ' 面板关闭')

    def start_game(self, service):
        self.control('start', [service])
        def running():
            info = self.docker.inspect('mcnet-' + service)
            return info and info['State']['Running'] and \
                info['State'].get('Health', {}).get('Status', 'healthy') == 'healthy'
        self.wait(running, service + ' 启动')

    def up(self, services, pull=False):
        for role in (*GAMES, *PANELS):
            for sub in ('', 'server') if role in GAMES else ('data', 'logs', 'upload_files'):
                (ROOT / 'data' / (role if role in GAMES else role.replace('mcsm-', 'mcsm/')) / sub).mkdir(parents=True, exist_ok=True)
        (ROOT / 'data/whitelist').mkdir(parents=True, exist_ok=True)
        for sub in ('data', 'config'): (ROOT / 'data/gateway' / sub).mkdir(parents=True, exist_ok=True)
        (ROOT / 'data/timezone').write_bytes((Path('/usr/share/zoneinfo') / self.env['TZ']).read_bytes())
        self.ensure_network()
        for service in (*PANELS, *GAMES):
            selected = service in PANELS or service in services
            if not selected: continue
            if pull: self.docker.pull(image(self.env, service))
            else:
                try: self.docker.image_id(image(self.env, service))
                except DockerError as error:
                    if error.status != 404: raise
                    self.docker.pull(image(self.env, service))
        if pull: self.docker.pull('caddy:2-alpine')
        else:
            try: self.docker.image_id('caddy:2-alpine')
            except DockerError as error:
                if error.status != 404: raise
                self.docker.pull('caddy:2-alpine')
        self.ensure_panel('mcsm-daemon')
        # 节点认证就绪后，原生实例仍会依次接管；等待接管完成再发启动请求。
        self.wait(lambda: panel_ready(json.loads(self.control('status')),
                  {s: self.docker.inspect('mcnet-' + s) for s in GAMES}), 'MCSManager 实例接管')
        self.control('sync')
        self.ensure_panel('mcsm-web')
        self.ensure_panel('gateway')
        configurations = json.loads(self.control('config'))
        for service in GAMES:
            if service not in services: continue
            info = self.docker.inspect('mcnet-' + service)
            if game_changed(info, configurations[service], self.docker.image_id(image(self.env, service))):
                self.stop_game(service)
            self.start_game(service)
        if all(self.docker.inspect('mcnet-' + s) for s in GAMES[:3]): self.runtime(['whitelist', 'sync'])
        # 旧 Compose 文件不再是服务配置入口。
        (ROOT / 'compose.yaml').unlink(missing_ok=True)
        self.status()

    def runtime(self, args):
        os.environ.update(self.env)
        subprocess.run([sys.executable, '/opt/mcnet/runtime.py', *args], check=True)

    def status(self):
        try: states = {i['service']: i for i in json.loads(self.control('status'))}
        except (DockerError, RuntimeError): states = {}
        for service in SERVICES:
            info = self.docker.inspect('mcnet-' + service)
            status = info['State']['Status'] if info else 'stopped'
            panel = states.get(service)
            print(service + ': ' + status + (f"；面板状态 {panel['status']}；{panel['processType']}" if panel else ''))

    def run(self, command, args):
        if command in ('mode', 'whitelist'):
            self.runtime([command, *args])
            if command == 'mode' and args != ['status']:
                self.__init__(self.docker)
                self.up(GAMES)
            elif command == 'whitelist' and args and args[0] in ('on', 'off'):
                self.control('sync')
            return
        if any(s not in SERVICES for s in args): raise ValueError('未知服务')
        games = [s for s in (args or GAMES) if s in GAMES]
        if command in ('up', 'update'): self.up(games, pull=command == 'update')
        elif command == 'restart':
            for service in games: self.stop_game(service); self.start_game(service)
            for service in args:
                if service in (*PANELS, 'gateway'):
                    self.docker.request('POST', '/containers/mcnet-' + service + '/restart?t=30')
            self.status()
        elif command == 'down':
            for service in (*reversed(GAMES), 'gateway', 'mcsm-web', 'mcsm-daemon'):
                self.docker.stop('mcnet-' + service)
        elif command == 'ps': self.status()
        else: raise ValueError('未知命令: ' + command)


if __name__ == '__main__':
    try: Manager().run(sys.argv[1], sys.argv[2:])
    except (DockerError, RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print('[error] ' + str(error), file=sys.stderr)
        sys.exit(1)
