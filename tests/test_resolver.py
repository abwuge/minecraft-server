import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('resolver', Path(__file__).parents[1] / 'scripts/resolve-packages.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ResolverTests(unittest.TestCase):
    def test_mcdr_refreshes_from_pypi_while_plugin_pin_is_preserved(self):
        plugin = {'name': 'mirror', 'source': 'github_release', 'repo': 'owner/plugin',
                  'asset_re': r'^Mirror\.mcdr$', 'tag': 'v1.4.1'}
        release = {'tag_name': 'v1.4.1', 'assets': [
            {'name': 'Mirror.mcdr', 'browser_download_url': 'https://example.com/Mirror.mcdr'}
        ]}
        for version in ('2.16.0', '2.17.0'):
            def get(url):
                if url == 'https://pypi.org/pypi/mcdreforged/json':
                    return {'info': {'version': version}}
                self.assertEqual(url, 'https://api.github.com/repos/owner/plugin/releases/tags/v1.4.1')
                return release
            with patch.object(r, 'MCDR_PLUGINS', [plugin]), patch.object(r, 'http_get_json', side_effect=get):
                result = r.resolve_mcdr_plugins()
            self.assertEqual(result['mcdr_version'], version)
            self.assertEqual(result['mcdr_plugins'][0]['version'], 'v1.4.1')


if __name__ == '__main__':
    unittest.main()
