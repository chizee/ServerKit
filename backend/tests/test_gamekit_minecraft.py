"""gamekit framework unit tests (plan 53 Phase 1).

gamekit is the dependency-free, extractable game-server framework inside the
serverkit-minecraft extension (D1). It ships no ServerKit imports, so these tests
load it straight off disk (its backend dir on sys.path) and exercise the four
adapters with a scripted fake RCON socket, fixture logs, and temp worlds — no
Docker, no live server. The Docker create/console/backup wiring rides these
adapters and is verified separately on the dev box.
"""
import datetime
import json
import os
import struct
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MC = os.path.join(_REPO_ROOT, 'builtin-extensions', 'serverkit-minecraft')
_MC_BACKEND = os.path.join(_MC, 'backend')
if _MC_BACKEND not in sys.path:
    sys.path.insert(0, _MC_BACKEND)

from gamekit import rcon, log_events, config_form, save_backup  # noqa: E402


# --------------------------------------------------------------------------- #
# RCON (fake socket, no network)
# --------------------------------------------------------------------------- #

class FakeRconSocket:
    """Scripted Source-RCON server over the socket interface RconClient uses."""

    def __init__(self, password='secret', responses=None, fail_auth=False):
        self.password = password
        self.fail_auth = fail_auth
        self.responses = responses or {}
        self._out = b''
        self.sent_commands = []
        self.closed = False

    def settimeout(self, _t):
        pass

    def connect(self, _addr):
        pass

    def close(self):
        self.closed = True

    def sendall(self, data):
        (length,) = struct.unpack('<i', data[:4])
        payload = data[4:4 + length]
        req_id, req_type = struct.unpack('<ii', payload[:8])
        body = payload[8:-2].decode('utf-8')
        if req_type == rcon.SERVERDATA_AUTH:
            ok = (not self.fail_auth) and body == self.password
            echo_id = req_id if ok else -1
            self._out += rcon.encode_packet(echo_id, rcon.SERVERDATA_AUTH_RESPONSE, '')
        elif req_type == rcon.SERVERDATA_EXECCOMMAND:
            self.sent_commands.append(body)
            resp = self.responses.get(body, f'ran: {body}')
            self._out += rcon.encode_packet(req_id, rcon.SERVERDATA_RESPONSE_VALUE, resp)

    def recv(self, n):
        chunk, self._out = self._out[:n], self._out[n:]
        return chunk


def test_rcon_auth_and_command_roundtrip():
    sock = FakeRconSocket(password='secret',
                          responses={'list': 'There are 2 of a max of 20 players online: Steve, Alex'})
    with rcon.RconClient(password='secret', sock=sock) as rc:
        out = rc.command('list')
    assert 'Steve' in out and 'Alex' in out
    assert sock.sent_commands == ['list']
    assert sock.closed is True


def test_rcon_command_before_auth_raises():
    sock = FakeRconSocket(password='secret')
    rc = rcon.RconClient(password='secret', sock=sock).connect()
    with pytest.raises(rcon.RconError):
        rc.command('list')


def test_rcon_auth_failure_raises():
    sock = FakeRconSocket(password='secret', fail_auth=True)
    rc = rcon.RconClient(password='wrong', sock=sock).connect()
    with pytest.raises(rcon.RconAuthError):
        rc.authenticate()


def test_rcon_packet_framing_is_little_endian():
    pkt = rcon.encode_packet(7, rcon.SERVERDATA_EXECCOMMAND, 'say hi')
    (length,) = struct.unpack('<i', pkt[:4])
    assert length == len(pkt) - 4
    req_id, req_type = struct.unpack('<ii', pkt[4:12])
    assert req_id == 7 and req_type == rcon.SERVERDATA_EXECCOMMAND
    assert pkt.endswith(b'\x00\x00')


# --------------------------------------------------------------------------- #
# log_events
# --------------------------------------------------------------------------- #

def test_java_log_events_in_order():
    lines = [
        '[12:34:56] [Server thread/INFO]: Done (12.345s)! For help, type "help"',
        '[12:35:01] [Server thread/INFO]: Steve joined the game',
        '[12:36:10] [Server thread/INFO]: <Steve> hello world',
        '[12:40:00] [Server thread/INFO]: Steve left the game',
        '[12:41:00] [Server thread/INFO]: Stopping server',
    ]
    events = log_events.parse_lines(lines)
    assert [e['event'] for e in events] == [
        'server_started', 'player_join', 'chat', 'player_leave', 'server_stopping']
    assert events[0]['elapsed'] == '12.345'
    assert events[1]['player'] == 'Steve'
    assert events[2]['message'] == 'hello world'


def test_bedrock_log_events():
    lines = [
        '[2026-07-22 12:00:00 INFO] Server started.',
        '[2026-07-22 12:01:00 INFO] Player connected: Steve, xuid: 123',
        '[2026-07-22 12:05:00 INFO] Player disconnected: Steve, xuid: 123',
    ]
    events = log_events.parse_lines(lines)
    assert [e['event'] for e in events] == ['server_started', 'player_join', 'player_leave']
    assert events[1]['player'] == 'Steve'


def test_non_event_lines_ignored():
    assert log_events.parse_line('[12:00:00] [Server thread/INFO]: Preparing spawn area: 42%') is None
    assert log_events.parse_line('') is None


# --------------------------------------------------------------------------- #
# config_form
# --------------------------------------------------------------------------- #

_PROPS = (
    '# Minecraft server properties\n'
    'motd=Hello World\n'
    'difficulty=hard\n'
    'max-players=20\n'
    'white-list=true\n'
    'custom-unlisted-key=keep-me\n'
)


def _sidecar_meta():
    with open(os.path.join(_MC, 'backend', 'gamekit', 'server_properties_meta.json'),
              'r', encoding='utf-8') as f:
        return json.load(f)


def test_parse_properties_ignores_comments_and_blanks():
    props = config_form.parse_properties(_PROPS)
    assert props['motd'] == 'Hello World'
    assert props['max-players'] == '20'
    assert 'custom-unlisted-key' in props
    assert not any(k.startswith('#') for k in props)


def test_build_form_groups_and_coerces_with_real_sidecar():
    form = config_form.build_form(_PROPS, _sidecar_meta())
    all_fields = {f['key']: f for g in form['groups'] for f in g['fields']}
    assert all_fields['max-players']['value'] == 20            # coerced int
    assert all_fields['white-list']['value'] is True           # coerced bool
    assert 'options' in all_fields['difficulty']               # from sidecar
    # unlisted key still surfaces, in the implicit 'other' group
    assert all_fields['custom-unlisted-key']['type'] == 'string'
    group_ids = [g['id'] for g in form['groups']]
    assert group_ids == sorted(group_ids, key=lambda g:
                               {'general': 1, 'world': 2, 'players': 3, 'gameplay': 4,
                                'network': 5, 'performance': 6, 'other': 99}.get(g, 50))


def test_apply_changes_preserves_and_appends():
    new = config_form.apply_changes(_PROPS, {'difficulty': 'peaceful', 'pvp': False})
    assert 'difficulty=peaceful' in new
    assert 'motd=Hello World' in new                 # untouched key preserved
    assert '# Minecraft server properties' in new    # comment preserved
    assert 'custom-unlisted-key=keep-me' in new      # unknown key preserved
    assert 'pvp=false' in new                         # new key appended, bool rendered


# --------------------------------------------------------------------------- #
# save_backup
# --------------------------------------------------------------------------- #

class _FakeRcon:
    def __init__(self):
        self.cmds = []

    def command(self, c):
        self.cmds.append(c)
        return ''


def test_hot_backup_quiesce_order_and_produces_archive(tmp_path):
    world = tmp_path / 'world'
    world.mkdir()
    (world / 'level.dat').write_bytes(b'x' * 32)
    dest = tmp_path / 'backups'
    rc = _FakeRcon()

    res = save_backup.hot_backup(str(world), str(dest), 'world_v1.21', rcon=rc)

    assert res['success'] is True and res['skipped'] is False
    # the correct hot-backup sequence, in order
    assert rc.cmds == ['save-off', 'save-all flush', 'save-on']
    assert os.path.isfile(res['path'])
    assert res['path'].endswith('world_v1.21.zip')


def test_hot_backup_skips_empty_world(tmp_path):
    world = tmp_path / 'world'
    world.mkdir()
    res = save_backup.hot_backup(str(world), str(tmp_path / 'b'), 'x.zip')
    assert res['skipped'] is True
    assert res['commands'] == []


def test_save_on_runs_even_if_zip_fails(tmp_path, monkeypatch):
    world = tmp_path / 'world'
    world.mkdir()
    (world / 'a.dat').write_bytes(b'y')
    rc = _FakeRcon()
    # Fail mid-sequence, after quiesce has started, to prove save-on still runs.
    def boom(_src, _path):
        raise RuntimeError('disk full')
    monkeypatch.setattr(save_backup, '_zip_dir', boom)
    with pytest.raises(RuntimeError):
        save_backup.hot_backup(str(world), str(tmp_path / 'backups'), 'x.zip', rcon=rc)
    assert rc.cmds == ['save-off', 'save-all flush', 'save-on']   # resume always issued


def test_retention_prunes_oldest_keeps_newest(tmp_path):
    dest = tmp_path / 'b'
    dest.mkdir()
    for i in range(4):
        p = dest / f'w{i}.zip'
        p.write_bytes(b'z')
        os.utime(p, (1000 + i, 1000 + i))
    pruned = save_backup.apply_retention(str(dest), 2)
    assert set(pruned) == {'w0.zip', 'w1.zip'}
    remaining = sorted(f for f in os.listdir(dest) if f.endswith('.zip'))
    assert remaining == ['w2.zip', 'w3.zip']


def test_archive_name_is_self_describing():
    when = datetime.datetime(2026, 7, 22, 12, 0)
    assert save_backup.archive_name('myworld', '1.21', when) == 'myworld_v1.21_2026-07-22_1200.zip'


# --------------------------------------------------------------------------- #
# manifest well-formed
# --------------------------------------------------------------------------- #

def test_extension_manifest_is_well_formed():
    with open(os.path.join(_MC, 'plugin.json'), 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    for key in ('name', 'display_name', 'version', 'entry_point', 'url_prefix',
                'models', 'category'):
        assert manifest.get(key), f'manifest missing {key}'
    assert manifest['category'] == 'games'
    assert manifest['entry_point'] == 'minecraft:minecraft_bp'
    assert manifest['url_prefix'] == '/api/v1/minecraft'
