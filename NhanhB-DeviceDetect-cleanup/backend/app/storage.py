import json,sqlite3
import os
import secrets
import tempfile
from pathlib import Path
from datetime import datetime,timezone

def utc():return datetime.now(timezone.utc).isoformat()
class Store:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        path = self.root / 'metadata.sqlite3'
        # The local registry now stores consented MACs for UART provisioning.
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.executescript('CREATE TABLE IF NOT EXISTS probe_sessions (id TEXT PRIMARY KEY, metadata TEXT); CREATE TABLE IF NOT EXISTS events (at TEXT, kind TEXT, detail TEXT);')
        self.db.execute('''CREATE TABLE IF NOT EXISTS registered_devices (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, channel INTEGER NOT NULL,
            mac_hmac TEXT NOT NULL UNIQUE, consent_at TEXT NOT NULL)''')
        if 'wifi_mac' not in {column[1] for column in self.db.execute('PRAGMA table_info(registered_devices)')}:
            self.db.execute('ALTER TABLE registered_devices ADD COLUMN wifi_mac TEXT')
        self.db.execute('CREATE TABLE IF NOT EXISTS activity_settings (id INTEGER PRIMARY KEY CHECK(id=1), channel INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS csi_quality_replays (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS reliability_sessions (
            id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reliability_batches (
            session_id TEXT NOT NULL, start_us INTEGER NOT NULL, end_us INTEGER NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY (session_id, start_us));''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS device_csi_markers (
            id INTEGER PRIMARY KEY, scope TEXT NOT NULL, session_id TEXT NOT NULL,
            at TEXT NOT NULL, elapsed_s REAL, label TEXT NOT NULL)''')
        self._activity_key = None

    def activity_key(self):
        if self._activity_key is not None:
            return self._activity_key
        path = self.root / '.device-activity.key'
        if not path.exists():
            if self.db.execute('SELECT 1 FROM registered_devices LIMIT 1').fetchone():
                raise ValueError('Thiếu khóa HMAC của registry hiện có')
            with tempfile.NamedTemporaryFile(dir=self.root) as pending:
                pending.write(secrets.token_bytes(32))
                pending.flush()
                os.fsync(pending.fileno())
                try:
                    os.link(pending.name, path)
                except FileExistsError:
                    pass
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as key_file:
            if os.fstat(key_file.fileno()).st_mode & 0o077:
                raise ValueError('Khóa HMAC cần quyền tệp riêng tư (0600)')
            key = key_file.read(33)
        if len(key) != 32:
            raise ValueError('Khóa HMAC không hợp lệ')
        self._activity_key = key
        return key

    def registered_devices(self, *, include_mac=False):
        fields = ('id', 'name', 'channel', 'consent_at', 'wifi_mac')
        if not include_mac:
            fields = fields[:-1]
        rows = self.db.execute(f'SELECT {", ".join(fields)} FROM registered_devices ORDER BY consent_at, id')
        return [dict(zip(fields, row)) for row in rows]

    def activity_bindings(self):
        return dict(self.db.execute('SELECT mac_hmac, id FROM registered_devices'))

    def register_device(self, device, digest, mac):
        self.check_registry_limit(device['channel'])
        with self.db:
            cursor = self.db.execute('''INSERT INTO registered_devices (id,name,channel,mac_hmac,consent_at,wifi_mac)
                VALUES (?,?,?,?,?,?) ON CONFLICT(mac_hmac) DO NOTHING''',
                (device['id'], device['name'], device['channel'], digest, device['consent_at'], mac))
        return cursor.rowcount == 1

    def check_registry_limit(self, channel, exclude=''):
        count, = self.db.execute('SELECT count(*) FROM registered_devices WHERE channel=? AND id!=?',
                                 (channel, exclude)).fetchone()
        if count >= 16:
            raise ValueError('Mỗi kênh hỗ trợ tối đa 16 thiết bị đăng ký')

    def update_device(self, device_id, name, *, channel=None, mac=None, digest=None):
        with self.db:
            if channel is None:
                cursor = self.db.execute('UPDATE registered_devices SET name=? WHERE id=?', (name, device_id))
            else:
                self.check_registry_limit(channel, device_id)
                cursor = self.db.execute('UPDATE registered_devices SET name=?, channel=?, wifi_mac=?, mac_hmac=?, consent_at=? WHERE id=?',
                                         (name, channel, mac, digest, utc(), device_id))
        return cursor.rowcount == 1

    def delete_device(self, device_id):
        with self.db:
            return self.db.execute('DELETE FROM registered_devices WHERE id=?', (device_id,)).rowcount == 1

    def activity_channel(self):
        row = self.db.execute('SELECT channel FROM activity_settings WHERE id=1').fetchone()
        return row[0] if row else None

    def set_activity_channel(self, channel):
        with self.db:
            self.db.execute('''INSERT INTO activity_settings VALUES (1,?) ON CONFLICT(id)
                DO UPDATE SET channel=excluded.channel''', (channel,))

    def save_quality_replay(self, replay_id, data):
        with self.db:
            self.db.execute('INSERT INTO csi_quality_replays VALUES (?,?)', (replay_id, json.dumps(data)))

    def quality_replay(self, replay_id):
        row = self.db.execute('SELECT data FROM csi_quality_replays WHERE id=?', (replay_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def quality_replays(self):
        return [dict(id=row[0], provenance=row[1], channel=row[2], duration_s=row[3]) for row in self.db.execute('''
            SELECT id, json_extract(data, '$.trace.provenance'), json_extract(data, '$.trace.channel'),
                json_extract(data, '$.trace.duration_s') FROM csi_quality_replays ORDER BY rowid DESC''')]

    def add_device_csi_marker(self, scope, session_id, elapsed_s, label):
        at = utc()
        with self.db:
            cursor = self.db.execute('INSERT INTO device_csi_markers (scope,session_id,at,elapsed_s,label) VALUES (?,?,?,?,?)',
                                     (scope, session_id, at, elapsed_s, label))
        return dict(id=cursor.lastrowid, at=at, elapsed_s=elapsed_s, label=label)

    def device_csi_markers(self, scope, session_id):
        return [dict(zip(('id', 'at', 'elapsed_s', 'label'), row)) for row in self.db.execute('''
            SELECT id,at,elapsed_s,label FROM device_csi_markers WHERE scope=? AND session_id=? ORDER BY id''', (scope, session_id))]

    def save_reliability_session(self, session, batch=None):
        with self.db:
            self.db.execute('INSERT INTO reliability_sessions VALUES (?,?)', (session['id'], json.dumps(session)))
            if batch:
                self.save_reliability_batch(session['id'], *batch)

    def reliability_sessions(self):
        rows = self.db.execute('SELECT data FROM reliability_sessions ORDER BY rowid DESC LIMIT 100')
        return [json.loads(row[0]) for row in rows]

    def reliability_session(self, session_id):
        row = self.db.execute('SELECT data FROM reliability_sessions WHERE id=?', (session_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_reliability_batch(self, session_id, start_us, end_us, data):
        payload = json.dumps(data)
        overlaps = self.db.execute('''SELECT start_us, end_us, data FROM reliability_batches
            WHERE session_id=? AND start_us < ? AND end_us > ?''', (session_id, end_us, start_us)).fetchall()
        if overlaps:
            if (len(overlaps) == 1 and overlaps[0][:2] == (start_us, end_us)
                    and json.loads(overlaps[0][2])['reports'] == data['reports']):
                return
            raise ValueError('Reliability batches overlap')
        with self.db:
            self.db.execute('INSERT INTO reliability_batches VALUES (?,?,?,?)', (session_id, start_us, end_us, payload))

    def reliability_batches(self, session_id, limit=100):
        rows = self.db.execute('''SELECT data FROM reliability_batches WHERE session_id=?
            ORDER BY start_us DESC LIMIT ?''', (session_id, limit))
        return [json.loads(row[0]) for row in reversed(rows.fetchall())]

    def stop_reliability_session(self, session):
        if not session.get('ended_at'):
            session = session | {'ended_at': utc()}
            with self.db:
                self.db.execute('UPDATE reliability_sessions SET data=? WHERE id=?', (json.dumps(session), session['id']))
        return session

    def event(self,kind,detail):
        self.db.execute('INSERT INTO events VALUES (?,?,?)',(utc(),kind,json.dumps(detail,ensure_ascii=False)));self.db.commit()
    def save(self,meta):
        self.db.execute('INSERT OR REPLACE INTO probe_sessions VALUES (?,?)',(meta['id'],json.dumps(meta,ensure_ascii=False)));self.db.commit()
    def close(self):self.db.close()
