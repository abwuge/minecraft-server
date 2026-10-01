import importlib.util
import json
import os
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

spec = importlib.util.spec_from_file_location('runtime', Path(__file__).parents[1] / 'scripts/mcnet-runtime.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, ONLINE_MODE='true', WHITE_LIST='true', RCON_PASSWORD='test-rcon', VELOCITY_FORWARDING_SECRET='test-forward')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.paths = patch.multiple(r, DATA=self.root/'data', SHARED=self.root/'whitelist', HOST=self.root/'host')
        self.paths.start()
        self.addCleanup(self.paths.stop)
        r.DATA.mkdir()
        r.HOST.mkdir()
        (r.HOST/'.env').write_text('UNRELATED=value\n')

    def test_existing_config_preserved_and_mode_applied(self):
        props = r.DATA/'server/server.properties'
        props.parent.mkdir()
        props.write_text('motd=custom\nwhite-list=false\n')
        toml = props.parent/'config/FabricProxy-Lite.toml'
        toml.parent.mkdir()
        toml.write_text('hackOnlineMode = false\nsecret = "old"\ncustom = 1\n')
        r.prepare_server()
        self.assertIn('motd=custom', props.read_text())
        self.assertIn('white-list=true', props.read_text())
        self.assertIn('hackOnlineMode = true', toml.read_text())
        self.assertIn('custom = 1', toml.read_text())
        self.assertEqual((props.parent/'whitelist.json').resolve(), (r.SHARED/'whitelist.json').resolve())
        os.environ.update(ONLINE_MODE='false', WHITE_LIST='false')
        r.prepare_server()
        self.assertIn('hackOnlineMode = false', toml.read_text())
        self.assertIn('enforce-whitelist=false', props.read_text())

    def test_legacy_backup_detects_saved_world_and_preserves_settings(self):
        path = r.DATA / 'config/prime_backup/config.json'
        path.parent.mkdir(parents=True)
        config = {
            'enabled': True, 'storage_root': './pb_files',
            'server': {'saved_world_regex': ['Saved the game', 'Saved the world'],
                       'save_world_max_wait': '10m'},
            'backup': {'targets': ['SurvivalForever']},
            'scheduled_backup': {'crontab': '*/10 * * * *'},
        }
        path.write_text(json.dumps(config))
        r.prepare_server()
        result = json.loads(path.read_text())
        self.assertTrue(any(re.fullmatch(p, 'System chat: Saved the game')
                            for p in result['server']['saved_world_regex']))
        config['server']['saved_world_regex'].append('System chat: Saved the game')
        self.assertEqual(result, config)
        text = path.read_text()
        r.prepare_server()
        self.assertEqual(path.read_text(), text)

    def test_custom_backup_save_detection_preserved(self):
        path = r.DATA / 'config/prime_backup/config.json'
        path.parent.mkdir(parents=True)
        for patterns in ([], ['custom save complete'], ['(?:System chat: )?Saved the game']):
            text = json.dumps({'enabled': False, 'server': {'saved_world_regex': patterns}})
            path.write_text(text)
            r.prepare_prime_backup()
            self.assertEqual(path.read_text(), text)
        path.unlink()
        r.prepare_prime_backup()
        self.assertFalse(path.exists())

    def test_mirror_save_detection_for_fresh_and_existing_config(self):
        path = r.DATA / 'config/mirror_mcsmcdr/config.json'
        r.prepare_mirror()
        config = json.loads(path.read_text())
        save = config['!!mirror']['command']['action']['sync']['save_world']
        for text in ('Saved the game', 'System chat: Saved the game'):
            self.assertIsNotNone(re.match(save['saved_world_regex'], text))
        config['!!mirror'].update({'mcsm': {'uuid': 'existing'},
                                 'sync': {'world': ['SurvivalForever'], 'target': ['../mirror/server']}})
        save['saved_world_regex'] = '^Saved the game$'
        config['!!custom'] = {'command': {'action': {'sync': {'save_world': {
            'saved_world_regex': '^custom save$'
        }}}}}
        path.write_text(json.dumps(config))
        r.prepare_mirror()
        save['saved_world_regex'] = '^(?:System chat: )?Saved the game$'
        self.assertEqual(json.loads(path.read_text()), config)
        text = path.read_text()
        r.prepare_mirror()
        self.assertEqual(path.read_text(), text)

    def test_main_mirror_connection_and_paths_migrate_without_changing_other_tasks(self):
        connection = self.root / 'connection.json'
        control = {'enable': True, 'url': 'http://mcnet-mcsm-web:23333',
                   'uuid': 'actual-mirror', 'remote_uuid': 'actual-node', 'apikey': 'scoped'}
        connection.write_text(json.dumps(control))
        props = r.DATA / 'server/server.properties'
        props.parent.mkdir()
        props.write_text('level-name=SurvivalForever\n')
        config_path = r.DATA / 'config/mirror_mcsmcdr/config.json'
        with patch.dict(os.environ, SERVER_NAME='main'):
            r.prepare_mirror(connection)
            config = json.loads(config_path.read_text())
            self.assertEqual(config['!!mirror']['mcsm'], control)
            self.assertEqual(config['!!mirror']['sync'], {'world': ['SurvivalForever'],
                             'source': './server', 'target': ['/mirror/server']})
            config['!!mirror']['command']['action']['sync']['require_confirm'] = True
            config['!!mirror']['sync']['world'] = ['custom']
            config['!!extra'] = {'mcsm': {'enable': False}, 'sync': {'target': ['elsewhere']}}
            config_path.write_text(json.dumps(config))
            r.prepare_mirror(connection)
            self.assertEqual(json.loads(config_path.read_text()), config)
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
        original = config_path.read_text()
        with patch.dict(os.environ, SERVER_NAME='mirror'):
            r.prepare_mirror(connection)
        self.assertEqual(config_path.read_text(), original)

    def test_union_existing_lists_and_mode_uuid_round_trip(self):
        for name in ('Alice', 'Bob'):
            d = self.root/name/'server'
            d.mkdir(parents=True)
            p = d/'whitelist.json'
            p.write_text(json.dumps([{'uuid':str(uuid.uuid5(uuid.NAMESPACE_DNS,name)), 'name':name}]))
            with r.whitelist_lock(): r.import_server_whitelist(p)
        online = json.loads((r.SHARED/'whitelist.json').read_text())
        self.assertEqual(len(online), 2)
        r.mode('offline')
        self.assertEqual({p['uuid'] for p in json.loads((r.SHARED/'whitelist.json').read_text())}, {r.offline_uuid('Alice'),r.offline_uuid('Bob')} | {p['uuid'] for p in online})
        os.environ['ONLINE_MODE'] = 'false'
        with patch.object(r,'reload_servers'): r.whitelist('sync')
        r.mode('online')
        self.assertEqual(json.loads((r.SHARED/'whitelist.json').read_text()), online)
        self.assertIn('WHITE_LIST=true', (r.HOST/'.env').read_text())

    def test_console_removal_stays_removed_after_sync(self):
        with r.whitelist_lock():
            r.save_players([{'platform':'java','name':'Alice','online_uuid':str(uuid.uuid4())}],True)
        (r.SHARED/'whitelist.json').write_text('[]')
        with patch.object(r,'reload_servers'): r.whitelist('sync')
        self.assertEqual(r.load_players(),[])
        self.assertEqual(json.loads((r.SHARED/'whitelist.json').read_text()),[])

    def test_fresh_and_existing_geyser_floodgate(self):
        plugins = r.DATA/'plugins'
        plugins.mkdir()
        with zipfile.ZipFile(plugins/'floodgate.jar','w') as z:
            z.writestr('config.yml','username-prefix: "old"\nplayer-link:\n  require-link: true\n  enable-global-linking: true\n')
        r.prepare_proxy()
        p = plugins/'Geyser-Velocity/config.yml'
        self.assertIn('auth-type: floodgate', p.read_text())
        self.assertIn('/data/plugins/floodgate/key.pem', p.read_text())
        f = plugins/'floodgate/config.yml'
        self.assertIn('require-link: false', f.read_text())
        self.assertIn('enable-global-linking: true', f.read_text())
        p.write_text(p.read_text()+'custom: keep\n')
        r.prepare_proxy()
        self.assertEqual(p.read_text().count('auth-type:'),1)
        self.assertIn('custom: keep',p.read_text())

    def test_bedrock_linked_and_unlinked(self):
        with patch.object(r,'get_json',side_effect=[{'xuid':'2533274790000000'},None]):
            p = r.lookup_player('bedrock','Test Player')
        self.assertEqual(p['name'],'.Test_Player')
        self.assertEqual(uuid.UUID(p['uuid']).int,2533274790000000)
        identity = str(uuid.uuid4())
        with patch.object(r,'get_json',return_value={'java_id':identity,'java_name':'Linked'}):
            p = r.lookup_player('bedrock','Test Player','2533274790000000')
        self.assertEqual(p['uuid'],identity)
        self.assertEqual(p['name'],'Linked')

    def test_whitelist_on_off_updates_all_and_reloads(self):
        for s in r.SERVICES:
            p = r.HOST/'data'/s/'server/server.properties'
            p.parent.mkdir(parents=True)
            p.write_text('white-list=true\n')
        with patch.object(r,'reload_servers') as reload:
            r.whitelist('off')
            reload.assert_called_once_with(False)
        for s in r.SERVICES:
            self.assertIn('white-list=false',(r.HOST/'data'/s/'server/server.properties').read_text())
        self.assertIn('WHITE_LIST=false',(r.HOST/'.env').read_text())

if __name__ == '__main__': unittest.main()
