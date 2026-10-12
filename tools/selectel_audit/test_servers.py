import json
import unittest
from .collector import Collector, Credentials, DEDICATED
from .test_audit import FakeClient
from .test_revision import endpoint


class ServerProfileTests(unittest.TestCase):
    def test_unrelated_products_are_not_requested(self):
        client = FakeClient([{'servers': []}, {'flavors': []}])
        collector = Collector(Credentials('123', token='synthetic-long-token'), client, profile='servers')
        collector.collect_catalog('t', [endpoint('object-store', 'https://r.selcloud.ru/swift'),
            endpoint('dns', 'https://r.selcloud.ru/dns'), endpoint('compute', 'https://r.selcloud.ru/compute')], 'p')
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(all('/compute/' in call[0] for call in client.calls))

    def test_os_secrets_removed_before_field_discovery(self):
        client = FakeClient([{'result': {'os_template': 'ubuntu', 'version': '24.04',
            'password': 'supersecret', 'login': 'private', 'user_ssh_key': 'supersecret',
            'cloud_init_user_data': 'supersecret', 'user_script': 'supersecret'}}])
        collector = Collector(Credentials('123', token='synthetic-long-token'), client, profile='servers')
        collector.detail('operating_system', DEDICATED + '/boot/os/test', 't', 'test')
        encoded = json.dumps(collector.document)
        self.assertNotIn('supersecret', encoded)
        self.assertNotIn('password', encoded)
        self.assertNotIn('user_script', encoded)
        self.assertIn('ubuntu', encoded)


if __name__ == '__main__':
    unittest.main()
