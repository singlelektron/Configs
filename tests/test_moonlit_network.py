import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'config/moonlit/plugins/moonlit-network/network.py'
SPEC = importlib.util.spec_from_file_location('moonlit_network', PATH)
NETWORK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NETWORK)


class NetworkOverviewTests(unittest.TestCase):
    def test_nmcli_escaping_dual_links_and_unavailable_state(self):
        data = r'eth\:0:ethernet:connected' + '\nwlan0:wifi:disconnected\nlo:loopback:connected (externally)\nwlan1:wifi:unavailable\n'
        rows = NETWORK.devices(data)
        self.assertEqual([x['interface'] for x in rows], ['eth:0', 'wlan0', 'wlan1'])
        self.assertEqual(rows[1]['state'], 'disconnected')
        self.assertEqual(rows[2]['state'], 'unavailable')
        self.assertEqual(NETWORK.fields(r'a\\b:ethernet:connected')[0], 'a\\b')
        with self.assertRaises(ValueError):
            NETWORK.devices('malformed:ethernet')

    def test_route_metrics_multipath_ipv6_and_tables_are_not_collapsed(self):
        rows = NETWORK.routes(json.dumps([
            {'dst': 'default', 'gateway': '192.0.2.1', 'dev': 'eth0', 'metric': 100},
            {'dst': 'default', 'metric': 600, 'table': 100, 'nexthops': [
                {'gateway': '198.51.100.1', 'dev': 'wlan0'}, {'gateway': '198.51.100.2', 'dev': 'eth1', 'flags': ['linkdown']}]},
            {'dst': '192.0.2.0/24', 'dev': 'eth0'}]), 'IPv4')
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['metric'] for r in rows], [100, 600, 600])
        self.assertEqual(rows[2]['flags'], ['linkdown'])
        self.assertEqual(rows[2]['table'], 100)
        v6 = NETWORK.routes('[{"dst":"default","dev":"wlan0","gateway":"fe80::1","metric":1024}]', 'IPv6')
        self.assertEqual(v6[0]['family'], 'IPv6')
        self.assertEqual(v6[0]['metric'], 1024)
        self.assertIsNone(NETWORK.routes('[{"dst":"default","dev":"tun0"}]', 'IPv4')[0]['metric'])

    def test_failed_networkmanager_does_not_hide_working_route_read(self):
        with patch.object(NETWORK, 'read', side_effect=[subprocess.TimeoutExpired('nmcli', 3),
                '[{"dst":"default","dev":"eth0","metric":100}]', '[]']):
            data = NETWORK.snapshot()
        self.assertEqual(len(data['errors']), 1)
        self.assertIn('NetworkManager', data['errors'][0])
        self.assertEqual(data['devices'], [])
        self.assertEqual(data['routes'][0]['interface'], 'eth0')

    def test_reader_is_bounded_direct_argv_without_shell(self):
        with patch.object(NETWORK.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '[]')) as run:
            self.assertEqual(NETWORK.read(['ip', '-j', '-4', 'route', 'show', 'table', 'all', 'default']), '[]')
        self.assertEqual(run.call_args.kwargs['timeout'], 3)
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')


if __name__ == '__main__':
    unittest.main()
