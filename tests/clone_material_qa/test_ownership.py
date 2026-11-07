"""Ownership gate tests never call adb, Docker, a game process, or native APIs."""
from copy import deepcopy
import unittest
from ownership import CONTAINER, IMAGE, validate_container


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': '/tmp/job-123'}
        self.container = {'Name': '/' + CONTAINER, 'State': {'Running': True},
            'Config': {'Image': IMAGE, 'Labels': {'elichika.qa.scope': 'clone-material', 'elichika.qa.run': '123'}},
            'NetworkSettings': {'Ports': {'5555/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '5555'}]}},
            'Mounts': [{'Destination': '/data', 'Type': 'bind', 'Source': '/tmp/job-123/clone-material-data', 'RW': True}]}

    def test_exact_owned_container(self):
        self.assertEqual(validate_container(self.container, self.env)['run_id'], '123')

    def test_rejects_active_other_lane_and_public_port(self):
        for mutation in ('scope', 'run', 'name', 'image', 'port', 'mount', 'readonly', 'stopped'):
            value = deepcopy(self.container)
            if mutation == 'scope': value['Config']['Labels']['elichika.qa.scope'] = 'rina-scenes'
            elif mutation == 'run': value['Config']['Labels']['elichika.qa.run'] = '999'
            elif mutation == 'name': value['Name'] = '/rina-unity-qa'
            elif mutation == 'image': value['Config']['Image'] = 'redroid/redroid:latest'
            elif mutation == 'port': value['NetworkSettings']['Ports']['5555/tcp'][0]['HostIp'] = '0.0.0.0'
            elif mutation == 'mount': value['Mounts'][0]['Source'] = '/tmp/other-lane/android-data'
            elif mutation == 'readonly': value['Mounts'][0]['RW'] = False
            elif mutation == 'stopped': value['State']['Running'] = False
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_container(value, self.env)

    def test_rejects_local_or_unidentified_job(self):
        for patch in ({'GITHUB_ACTIONS': 'false'}, {'GITHUB_RUN_ID': ''}, {'GITHUB_RUN_ID': '../123'}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_container(self.container, self.env | patch)


if __name__ == '__main__':
    unittest.main()
