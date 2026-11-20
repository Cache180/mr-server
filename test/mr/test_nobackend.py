# MR Server, a BeamMP-Server fork for Muertazos Racing.
# Copyright (C) 2026 Muertazos Racing
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Pruebas del servidor sin backend de BeamMP y con marca MR.

El servidor ya debe estar corriendo (lo arranca el workflow de CI) con
`test/mr/ServerConfig.ci.toml`. Variables de entorno:

    MR_SERVER_BIN   ruta del binario (para buscar hosts del backend)
    MR_SERVER_LOG   archivo donde se redirigio la salida del servidor
    MR_SERVER_PORT  puerto (por defecto 30899)
    MR_SERVER_HOST  host (por defecto 127.0.0.1)
"""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mrclient  # noqa: E402

HOST = os.environ.get("MR_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("MR_SERVER_PORT", "30899"))
BINARY = os.environ.get("MR_SERVER_BIN", "")
LOG = os.environ.get("MR_SERVER_LOG", "")

STARTED_LINE = "ALL SYSTEMS STARTED SUCCESSFULLY"
STARTUP_TIMEOUT_S = 20.0

BACKEND_HOSTS = (
    "backend.beammp.com",
    "auth.beammp.com",
    "backup1.beammp.com",
    "backup2.beammp.com",
    "keymaster.beammp.com",
)


def read_log():
    with open(LOG, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def wait_for_log(needle, timeout):
    deadline = time.monotonic() + timeout
    while True:
        text = read_log()
        if needle in text:
            return text
        if time.monotonic() >= deadline:
            return text
        time.sleep(0.25)


class NoBackendTests(unittest.TestCase):
    def test_starts_without_authkey(self):
        text = wait_for_log(STARTED_LINE, STARTUP_TIMEOUT_S)
        self.assertIn(STARTED_LINE, text)

    def test_info_query(self):
        wait_for_log(STARTED_LINE, STARTUP_TIMEOUT_S)
        sock = mrclient.connect(HOST, PORT)
        try:
            # La consulta es un unico byte `I` sin marco; la respuesta si lleva marco.
            sock.sendall(b"I")
            body = mrclient.recv_packet(sock)
        finally:
            sock.close()
        info = json.loads(body.decode("utf-8"))
        for key in ("players", "maxplayers", "map", "name", "version", "clientversion"):
            self.assertIn(key, info)
        self.assertEqual(info["clientversion"], "1.0.0")
        self.assertNotIn("uuid", info)

    def test_no_backend_hosts_in_binary(self):
        self.assertTrue(BINARY, "MR_SERVER_BIN no esta definida")
        with open(BINARY, "rb") as handle:
            blob = handle.read()
        for host in BACKEND_HOSTS:
            self.assertEqual(blob.find(host.encode("ascii")), -1, host)

    def test_banner(self):
        text = wait_for_log("basado en BeamMP-Server, AGPL-3.0", STARTUP_TIMEOUT_S)
        self.assertIn("MR Server", text)
        self.assertIn("basado en BeamMP-Server, AGPL-3.0", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
