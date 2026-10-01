import copy
import importlib.util
import json
from pathlib import Path
import struct
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location('manager', Path(__file__).parents[1] / 'mcnet.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ManagerTests(unittest.TestCase):
    def test_windows_and_iana_host_timezones_keep_offset_and_daylight_saving(self):
        mapping = Path(__file__).parents[1] / 'config/windows-timezones.json'
        self.assertEqual(m.timezone_name('China Standard Time', mapping), 'Asia/Shanghai')
        self.assertEqual(m.timezone_name('Asia/Tokyo', mapping), 'Asia/Tokyo')
        zone = ZoneInfo(m.timezone_name('Eastern Standard Time', mapping))
        self.assertEqual(datetime(2026, 1, 1, tzinfo=zone).utcoffset().total_seconds(), -5 * 3600)
        self.assertEqual(datetime(2026, 7, 1, tzinfo=zone).utcoffset().total_seconds(), -4 * 3600)

    def test_existing_native_games_wait_for_takeover_before_starting(self):
        states = [{'service': s, 'id': s, 'status': 0} for s in m.GAMES]
        containers = {s: {'State': {'Running': True}, 'Config': {
            'Labels': {'mcsmanager.instance.uuid': s}}} for s in m.GAMES}
        self.assertFalse(m.panel_ready(states, containers))
        for state in states: state['status'] = 3
        self.assertTrue(m.panel_ready(states, containers))
        for state in states: state['status'] = 0
        for info in containers.values(): info['Config']['Labels'] = {'com.docker.compose.project': 'mcnet'}
        self.assertTrue(m.panel_ready(states, containers))

    def test_matching_native_container_is_kept_and_legacy_container_is_migrated(self):
        config = {'docker': {'env': ['ONLINE_MODE=true'], 'networkMode': 'mcnet',
                            'extraVolumes': ['/srv/data/main|/data'], 'ports': []}}
        info = {'Image': 'sha256:current', 'Config': {'Env': ['ONLINE_MODE=true'],
                'Labels': {'mcsmanager.instance.uuid': 'stable'}},
                'Mounts': [{'Source': '/srv/data/main', 'Destination': '/data'}],
                'HostConfig': {'NetworkMode': 'mcnet', 'PortBindings': {}}}
        self.assertFalse(m.game_changed(info, config, 'sha256:current'))
        legacy = copy.deepcopy(info)
        legacy['Config']['Labels'] = {'com.docker.compose.project': 'mcnet'}
        self.assertTrue(m.game_changed(legacy, config, 'sha256:current'))
        self.assertTrue(m.game_changed(info, config, 'sha256:new'))
        changed = copy.deepcopy(config)
        changed['docker']['env'] = ['ONLINE_MODE=false']
        self.assertTrue(m.game_changed(info, changed, 'sha256:current'))

    def test_port_and_mount_changes_require_recreation(self):
        config = {'docker': {'env': [], 'networkMode': 'mcnet',
                            'extraVolumes': ['/srv/data/proxy|/data'],
                            'ports': ['25565:25565/tcp', '19132:19132/udp']}}
        info = {'Image': 'id', 'Config': {'Labels': {'mcsmanager.instance.uuid': 'id'}},
                'Mounts': [{'Source': '/srv/data/proxy', 'Destination': '/data'}],
                'HostConfig': {'NetworkMode': 'mcnet', 'PortBindings': {
                    '25565/tcp': [{'HostIp': '', 'HostPort': '25565'}],
                    '19132/udp': [{'HostIp': '', 'HostPort': '19132'}]}}}
        self.assertFalse(m.game_changed(info, config, 'id'))
        config['docker']['ports'][1] = '19135:19132/udp'
        self.assertTrue(m.game_changed(info, config, 'id'))

    def test_panel_ports_are_internal_and_caddy_owns_80_443(self):
        manager = object.__new__(m.Manager)
        manager.source = '/host_mnt/c/mcnet'
        manager.env = {'MCNET_DATA_PATH': manager.source + '/data',
                       'MCNET_NETWORK': 'mcnet', 'MCSM_PUBLIC_URL': 'https://mcsm.example.com', 'TZ': 'Asia/Tokyo'}
        for role in m.PANELS:
            spec = manager.panel_spec(role)
            self.assertNotIn('PortBindings', spec['HostConfig'])
        gateway = manager.gateway_spec()
        self.assertEqual(set(gateway['HostConfig']['PortBindings']), {'80/tcp', '443/tcp', '443/udp'})
        self.assertIn('MCSM_HOST=mcsm.example.com', gateway['Env'])
        daemon = manager.panel_spec('mcsm-daemon')
        self.assertTrue(any(bind['Target'] == manager.source + '/data'
                            for bind in daemon['HostConfig']['Mounts']))

    def test_docker_exec_output_is_demultiplexed(self):
        def frame(stream, text):
            data = text.encode()
            return bytes([stream, 0, 0, 0]) + struct.pack('>I', len(data)) + data
        self.assertEqual(m.demux(frame(1, 'ok') + frame(2, 'error')), b'okerror')
        with self.assertRaises(RuntimeError): m.demux(b'broken')


if __name__ == '__main__': unittest.main()
