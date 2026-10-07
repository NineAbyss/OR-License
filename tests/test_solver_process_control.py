import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from harbor_integration.coding_agent.solver_process_control import ProcessGroups
from harbor_integration.coding_agent.solver_watchdog import SolverWatchdog


class NamespaceProcessTests(unittest.TestCase):
    def test_zero_pid_cannot_match_timeout_ancestry(self):
        with tempfile.TemporaryDirectory() as directory:
            watchdog = SolverWatchdog(directory, Path(directory) / 'private')
            watchdog.record_agent_intent(0, {'kind': 'timeout', 'argv': ['5', 'python']})
            result = watchdog.classify_disconnect({'pid': 0})
            self.assertEqual(result['classification'], 'unattributed')
            with self.assertRaisesRegex(RuntimeError, 'PID must be resolved'):
                watchdog.begin(0, 'highs.run', None)

    def test_missing_kernel_peer_fd_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'socket FD required'):
            ProcessGroups().command({'action': 'identify', 'pid': 123})

    def test_same_process_calls_have_independent_completion(self):
        groups = ProcessGroups()
        identity = {'pid': 123, 'start': '42'}
        with patch('harbor_integration.coding_agent.solver_process_control._same', return_value=True), \
             patch.object(groups, 'scan'):
            for call in ('one', 'two'):
                groups.command({'action': 'arm', 'identity': identity, 'timeout': 30, 'call_id': call})
            groups.command({'action': 'complete', 'identity': identity, 'call_id': 'one'})
            self.assertEqual(set(groups.groups[(123, '42')]['calls']), {'two'})
            groups.command({'action': 'complete', 'identity': identity, 'call_id': 'two'})
            self.assertFalse(groups.groups)

    def test_reused_pid_is_not_killed(self):
        groups = ProcessGroups()
        groups.groups[(123, '42')] = {'members': {123: {'pid': 123, 'start': '42'}}, 'calls': {}}
        with patch.object(groups, 'scan'), \
             patch('harbor_integration.coding_agent.solver_process_control._same', return_value=False), \
             patch('harbor_integration.coding_agent.solver_process_control.os.kill') as kill:
            groups.kill((123, '42'))
            kill.assert_not_called()

    def test_other_process_deadline_survives_kill(self):
        groups = ProcessGroups()
        for pid in (123, 456):
            groups.groups[(pid, '42')] = {'members': {pid: {'pid': pid, 'start': '42'}},
                                          'calls': {'call': time.monotonic() + 30}}
        with patch.object(groups, 'scan'), \
             patch('harbor_integration.coding_agent.solver_process_control._same', return_value=False):
            groups.kill((123, '42'))
        self.assertIn((456, '42'), groups.groups)


if __name__ == '__main__':
    unittest.main()
