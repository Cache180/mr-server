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

"""Pruebas del tope duro de la cola de envio por cliente (32 MiB).

El servidor ya debe estar corriendo (lo arranca el workflow de CI) con
`test/mr/ServerConfig.ci.toml`. Variables de entorno (todas obligatorias salvo
host y puerto):

    MR_SERVER_PORT  puerto (por defecto 30899)
    MR_SERVER_HOST  host (por defecto 127.0.0.1)
    MR_SERVER_LOG   log del servidor
    MR_SERVER_PID   PID del servidor (se lee su RSS de /proc)

Cada prueba usa nombres de piloto propios y cierra sus sockets, para poder
compartir el servidor con las demas suites.

Dos caminos hacen crecer la cola de un cliente que no lee, sin ningun tope
general antes del tope duro:
  - `p` -> UpdatePlayer encola un paquete `Ss` (lista de jugadores) por cada
    `p`: 5 bytes enviados, decenas de bytes encolados.
  - un paquete fiable grande (`N`) de otro cliente se reenvia a todos.
"""

import hashlib
import os
import socket
import struct
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mrclient  # noqa: E402

HOST = os.environ.get("MR_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("MR_SERVER_PORT", "30899"))
LOG = os.environ.get("MR_SERVER_LOG", "")
SERVER_PID = int(os.environ.get("MR_SERVER_PID", "0"))

OVERFLOW_PHRASE = "cola de envio desbordada"
RSS_LIMIT_KB = 96 * 1024
TEST_DEADLINE_S = 90.0
FRAME_P = struct.pack("<i", 1) + b"p"
P_BATCH_FRAMES = 20000
# 5 bytes enviados -> >= ~70 bytes encolados: sobra con creces para llegar a
# 32 MiB (+ buffers del kernel) mucho antes de este limite.
P_MAX_FRAMES = 1200000
N_PAYLOAD_BYTES = 128 * 1024
N_MAX_FRAMES = 800

# Nombres de 20 caracteres (el maximo): el paquete `Ss` con cuatro jugadores
# ocupa asi ~90 bytes por cada `p` de 5 bytes.
SPAMMER = "PilotoSaturadorCola1"
READER = "PilotoLectorCola0001"
FILLERS = ("PilotoRellenoColaA00", "PilotoRellenoColaB00")
N_SENDER = "PilotoEmisorNCola001"
N_VICTIM = "PilotoVictimaNCola01"
assert all(len(n) == 20 for n in (SPAMMER, READER, N_SENDER, N_VICTIM) + FILLERS)


def install_key(name):
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]


def read_log():
    with open(LOG, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def overflow_lines(name):
    return [line for line in read_log().splitlines() if OVERFLOW_PHRASE in line and name in line]


def server_rss_kb():
    with open("/proc/%d/status" % SERVER_PID, "r") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    raise RuntimeError("VmRSS no encontrado")


class QueueHardCapTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(LOG, "MR_SERVER_LOG no esta definido")
        self.assertTrue(SERVER_PID, "MR_SERVER_PID no esta definido")

    def pilot(self, name, rcvbuf=None):
        """Entra como `name` (sincronizado). Reintenta si el servidor aun esta lleno."""
        deadline = time.monotonic() + 15.0
        while True:
            try:
                sock, pid = mrclient.join(HOST, PORT, name, install_key(name), rcvbuf=rcvbuf)
            except (mrclient.ProtocolError, ConnectionError, socket.timeout):
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
                continue
            self.addCleanup(sock.close)
            return sock, pid

    def assert_served(self, sock, who):
        """El servidor sigue atendiendo a `sock`: un `p` recibe su lista de jugadores."""
        mrclient.send_packet(sock, b"p")
        self.assertIsNotNone(
            mrclient.recv_until(sock, lambda packet: packet[:2] == b"Ss", 5.0),
            "%s dejo de ser atendido" % who,
        )

    def assert_closed_by_server(self, sock, who):
        """Drena lo que el kernel guardaba y comprueba que el servidor cerro la conexion."""
        deadline = time.monotonic() + 20.0
        sock.settimeout(5.0)
        while time.monotonic() < deadline:
            try:
                if not sock.recv(65536):
                    return
            except ConnectionError:
                return
            except socket.timeout:
                continue
        self.fail("%s sigue conectado: el servidor no cerro la conexion" % who)

    def assert_owner_disconnected(self, name):
        """El hilo dueno del socket llego a OnDisconnect (escribe `<name> Connection Terminated`).

        El tope duro lo marca el hilo productor (aviso + shutdown), pero solo el hilo
        dueno del socket ejecuta OnDisconnect: sin su linea, nadie cerro al cliente.
        """
        line = "%s Connection Terminated" % name
        deadline = time.monotonic() + 10.0
        while line not in read_log() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertIn(line, read_log(), "%s: el hilo dueno no desconecto al cliente" % name)

    def test_player_list_flood_disconnects_client(self):
        spammer, _ = self.pilot(SPAMMER, rcvbuf=4096)  # nunca lee
        reader, _ = self.pilot(READER)
        for name in FILLERS:
            self.pilot(name)
        self.assert_served(reader, "el otro cliente (antes)")

        rss_before_kb = server_rss_kb()
        peak_kb = rss_before_kb
        spammer.settimeout(30.0)
        batch = FRAME_P * P_BATCH_FRAMES
        started = time.monotonic()
        sent = 0
        checked_reader = False
        while sent < P_MAX_FRAMES and time.monotonic() - started < TEST_DEADLINE_S:
            try:
                spammer.sendall(batch)
            except ConnectionError:
                break  # el servidor ya cerro la conexion
            sent += P_BATCH_FRAMES
            peak_kb = max(peak_kb, server_rss_kb())
            if overflow_lines(SPAMMER):
                break
            if not checked_reader and sent >= 4 * P_BATCH_FRAMES:
                checked_reader = True
                self.assert_served(reader, "el otro cliente (durante)")
        elapsed = time.monotonic() - started

        lines = []
        wait_deadline = time.monotonic() + 10.0
        while not lines and time.monotonic() < wait_deadline:
            lines = overflow_lines(SPAMMER)
            time.sleep(0.1)
        print("test_player_list_flood: %d p enviados en %.1f s, pico +%d KB RSS"
              % (sent, elapsed, peak_kb - rss_before_kb))
        self.assertEqual(len(lines), 1, "se esperaba una linea de log con '%s': %r" % (OVERFLOW_PHRASE, lines))
        self.assert_closed_by_server(spammer, SPAMMER)
        self.assert_owner_disconnected(SPAMMER)

        peak_kb = max(peak_kb, server_rss_kb())
        self.assertLess(peak_kb - rss_before_kb, RSS_LIMIT_KB,
                        "el RSS del server crecio %d KB" % (peak_kb - rss_before_kb))
        self.assert_served(reader, "el otro cliente (despues)")

    def test_large_reliable_fanout_disconnects_slow_client(self):
        sender, _ = self.pilot(N_SENDER)
        victim, _ = self.pilot(N_VICTIM, rcvbuf=4096)  # nunca lee

        rss_before_kb = server_rss_kb()
        peak_kb = rss_before_kb
        body = b"N" + os.urandom(N_PAYLOAD_BYTES - 1)  # incompresible: se encola entero
        frame = struct.pack("<i", len(body)) + body
        sender.settimeout(30.0)
        started = time.monotonic()
        sent = 0
        while sent < N_MAX_FRAMES and time.monotonic() - started < TEST_DEADLINE_S:
            try:
                sender.sendall(frame)
            except ConnectionError:
                break
            sent += 1
            if sent % 8 == 0:
                peak_kb = max(peak_kb, server_rss_kb())
                if overflow_lines(N_VICTIM):
                    break
        elapsed = time.monotonic() - started

        lines = []
        wait_deadline = time.monotonic() + 10.0
        while not lines and time.monotonic() < wait_deadline:
            lines = overflow_lines(N_VICTIM)
            time.sleep(0.1)
        print("test_large_reliable_fanout: %d paquetes de %d KB en %.1f s, pico +%d KB RSS"
              % (sent, N_PAYLOAD_BYTES // 1024, elapsed, peak_kb - rss_before_kb))
        self.assertEqual(len(lines), 1, "se esperaba una linea de log con '%s': %r" % (OVERFLOW_PHRASE, lines))
        self.assert_closed_by_server(victim, N_VICTIM)
        self.assert_owner_disconnected(N_VICTIM)

        peak_kb = max(peak_kb, server_rss_kb())
        self.assertLess(peak_kb - rss_before_kb, RSS_LIMIT_KB,
                        "el RSS del server crecio %d KB" % (peak_kb - rss_before_kb))
        # el emisor no se ve afectado
        self.assert_served(sender, "el emisor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
