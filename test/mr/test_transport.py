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

"""Pruebas del transporte: clientes UDP y clientes "solo TCP" (paquete `Ft`).

El servidor ya debe estar corriendo (lo arranca el workflow de CI) con
`test/mr/ServerConfig.ci.toml`. Variables de entorno:

    MR_SERVER_PORT  puerto (por defecto 30899)
    MR_SERVER_HOST  host (por defecto 127.0.0.1)
    MR_SERVER_LOG   log del servidor (obligatorio: varias pruebas lo leen)

Cada prueba usa nombres de piloto propios y cierra sus sockets, para poder
compartir el servidor con las demas suites.
"""

import collections
import hashlib
import os
import socket
import sys
import time
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mrclient  # noqa: E402

HOST = os.environ.get("MR_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("MR_SERVER_PORT", "30899"))
LOG = os.environ.get("MR_SERVER_LOG", "")
SERVER_PID = int(os.environ.get("MR_SERVER_PID", "0"))

TCP_ONLY_LINE = "%s usa solo TCP (UDP no disponible)"

# Por debajo de 400 bytes ni el launcher ni el servidor comprimen el paquete.
POSITION_PADDING = 330

Pilot = collections.namedtuple("Pilot", "name pid sock udp")


def install_key(name):
    """Clave de instalacion de prueba, distinta por piloto (32 alfanumericos)."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]


def position(pid, seq=None, padding=0):
    """Paquete de posicion `Zp:<pid>-0:{...}` con la forma que acepta el servidor."""
    if seq is None:
        return b"Zp:%d-0:{}" % pid
    return b'Zp:%d-0:{"n":%d,"pad":"%s"}' % (pid, seq, b"x" * padding)


def read_log():
    with open(LOG, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def wait_for_log(needle, timeout=5.0):
    """Espera a que `needle` aparezca en el log; devuelve el texto del log."""
    deadline = time.monotonic() + timeout
    while True:
        text = read_log()
        if needle in text or time.monotonic() >= deadline:
            return text
        time.sleep(0.1)


def server_rss_kb():
    with open("/proc/%d/status" % SERVER_PID, "r") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    raise RuntimeError("VmRSS no encontrado")


def tcp_wmem_max():
    with open("/proc/sys/net/ipv4/tcp_wmem", "r") as handle:
        return int(handle.read().split()[2])


def drain_udp(udpsock):
    """Vacia sin esperar el buffer de recepcion UDP; devuelve los datagramas leidos."""
    got = []
    udpsock.settimeout(0.0)
    try:
        while True:
            got.append(udpsock.recv(4096))
    except (BlockingIOError, socket.timeout):
        return got


def drain_tcp(sock, idle):
    """Lee bytes crudos hasta `idle` segundos sin datos; devuelve cuantos leyo."""
    total = 0
    sock.settimeout(idle)
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            total += len(chunk)
    except socket.timeout:
        pass
    return total


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(LOG, "MR_SERVER_LOG no esta definido")

    def pilot(self, name, udp=True, rcvbuf=None):
        """Entra como `name` (sincronizado); con `udp` abre ademas el canal UDP."""
        sock, pid = mrclient.join(HOST, PORT, name, install_key(name), rcvbuf=rcvbuf)
        self.addCleanup(sock.close)
        udpsock = None
        if udp:
            udpsock = mrclient.open_udp(HOST, PORT, pid)
            self.addCleanup(udpsock.close)
        return Pilot(name, pid, sock, udpsock)

    def make_tcp_only(self, pilot):
        """Manda `Ft` y espera a que el servidor lo haya procesado.

        El `p` va por la misma conexion TCP que `Ft`, asi que su respuesta
        (por TCP, ya que no hay UDP) prueba que el servidor atendio `Ft` antes.
        """
        mrclient.send_packet(pilot.sock, b"Ft")
        mrclient.send_packet(pilot.sock, b"p")
        reply = mrclient.recv_until(pilot.sock, lambda packet: packet == b"p", 2.0)
        self.assertIsNotNone(reply, "%s: sin respuesta p por TCP tras Ft" % pilot.name)

    def test_udp_client_unchanged(self):
        a = self.pilot("PilotoA1")
        b = self.pilot("PilotoB1")

        mrclient.udp_send(a.udp, a.pid, b"p")
        self.assertIsNotNone(
            mrclient.udp_recv_until(a.udp, lambda datagram: datagram == b"p", 2.0),
            "A no recibio p por UDP",
        )

        sent = position(a.pid)
        mrclient.udp_send(a.udp, a.pid, sent)
        self.assertIsNotNone(
            mrclient.udp_recv_until(b.udp, lambda datagram: datagram == sent, 2.0),
            "B no recibio por UDP la posicion de A",
        )

    def test_tcp_only_ping(self):
        c = self.pilot("PilotoC2", udp=False)
        mrclient.send_packet(c.sock, b"Ft")
        mrclient.send_packet(c.sock, b"p")
        started = time.monotonic()
        reply = mrclient.recv_until(c.sock, lambda packet: packet == b"p", 2.0)
        self.assertIsNotNone(reply, "C no recibio p por TCP")
        self.assertLess(time.monotonic() - started, 2.0)

    def test_tcp_only_exchanges_positions(self):
        a = self.pilot("PilotoA3")
        c = self.pilot("PilotoC3", udp=False)
        self.make_tcp_only(c)

        from_a = position(a.pid)
        mrclient.udp_send(a.udp, a.pid, from_a)
        self.assertIsNotNone(
            mrclient.recv_until(c.sock, lambda packet: packet == from_a, 2.0),
            "C no recibio por TCP la posicion de A",
        )

        from_c = position(c.pid)
        mrclient.send_packet(c.sock, from_c)
        self.assertIsNotNone(
            mrclient.udp_recv_until(a.udp, lambda datagram: datagram == from_c, 2.0),
            "A no recibio por UDP la posicion de C",
        )

    def test_ft_over_udp_ignored(self):
        a = self.pilot("PilotoA4")

        mrclient.udp_send(a.udp, a.pid, b"Ft")
        # misma conexion UDP, mismo hilo del servidor: `p` se procesa despues de `Ft`
        mrclient.udp_send(a.udp, a.pid, b"p")
        self.assertIsNotNone(
            mrclient.udp_recv_until(a.udp, lambda datagram: datagram == b"p", 2.0),
            "A dejo de recibir p por UDP: Ft por UDP lo marco como solo TCP",
        )
        self.assertNotIn(TCP_ONLY_LINE % a.name, read_log())

    def test_ft_repeated_single_event(self):
        c = self.pilot("PilotoC5", udp=False)
        for _ in range(50):
            mrclient.send_packet(c.sock, b"Ft")
        # el `p` final solo se atiende despues de los 50 `Ft`
        mrclient.send_packet(c.sock, b"p")
        self.assertIsNotNone(
            mrclient.recv_until(c.sock, lambda packet: packet == b"p", 2.0),
            "C no recibio p por TCP",
        )
        text = wait_for_log(TCP_ONLY_LINE % c.name)
        self.assertEqual(text.count(TCP_ONLY_LINE % c.name), 1)

    def test_slow_tcp_only_client_does_not_stall_others(self):
        a = self.pilot("PilotoA6")
        b = self.pilot("PilotoB6")
        c = self.pilot("PilotoC6", udp=False)
        self.make_tcp_only(c)
        # C deja de leer desde aqui.

        # 1) Inundacion: mas posiciones hacia C de las que caben en los buffers del
        # kernel (2 x tcp_wmem max + 64 KB), para que el Looper de C acabe bloqueado
        # en su escritura y la cola de C llegue al tope. A ritmo moderado para que
        # el buffer UDP del server no tire datagramas; B drena lo que le llega.
        target = 2 * tcp_wmem_max() + 64 * 1024
        rss_before_kb = server_rss_kb()
        offered = 0  # bytes que el server tuvo que entregar a C (marco TCP incluido)
        seq = 0
        flood_deadline = time.monotonic() + 60.0
        while offered < target:
            self.assertLess(time.monotonic(), flood_deadline, "la inundacion no avanza")
            for _ in range(40):
                mrclient.udp_send(a.udp, a.pid, position(a.pid, seq, POSITION_PADDING))
                seq += 1
            # lo que B recibe es lo que el server proceso (y entrego tambien a C)
            offered += sum(len(d) + 4 for d in drain_udp(b.udp) if d.startswith(b"Zp:"))
            time.sleep(0.002)

        # 2) Con el Looper de C bloqueado, A y B siguen intercambiando a tiempo.
        exchanges = 200
        started = time.monotonic()
        deadline = started + 5.0
        for n in range(exchanges):
            from_a = position(a.pid, 1000000 + n, POSITION_PADDING)
            mrclient.udp_send(a.udp, a.pid, from_a)
            got_b = mrclient.udp_recv_until(
                b.udp, lambda datagram, want=from_a: datagram == want, deadline - time.monotonic()
            )
            self.assertIsNotNone(got_b, "B no recibio la posicion %d de A a tiempo" % n)

            from_b = position(b.pid, 1000000 + n, POSITION_PADDING)
            mrclient.udp_send(b.udp, b.pid, from_b)
            got_a = mrclient.udp_recv_until(
                a.udp, lambda datagram, want=from_b: datagram == want, deadline - time.monotonic()
            )
            self.assertIsNotNone(got_a, "A no recibio la posicion %d de B a tiempo" % n)
        self.assertLess(time.monotonic() - started, 5.0)

        # 3) El server no acumulo la inundacion en memoria.
        growth_kb = server_rss_kb() - rss_before_kb
        self.assertLess(growth_kb, 64 * 1024, "el RSS del server crecio %d KB" % growth_kb)

        # 4) Tope de la cola: C vuelve a leer y recibe MENOS de lo ofrecido (el server
        # descarto posiciones al llenarse la cola) pero sigue conectado y atendido.
        self.assertGreater(offered, 0.9 * target, "la inundacion no llego al server")
        received = drain_tcp(c.sock, 2.0)
        self.assertGreater(received, 64 * 1024, "C no recibio nada de lo acumulado")
        self.assertLess(
            received, 0.9 * offered,
            "C recibio %d de %d bytes ofrecidos: el server no descarto posiciones" % (received, offered),
        )
        mrclient.send_packet(c.sock, b"p")
        self.assertIsNotNone(
            mrclient.recv_until(c.sock, lambda packet: packet == b"p", 3.0),
            "C no recibio p por TCP tras volver a leer",
        )

    def test_large_position_to_tcp_only_is_compressed(self):
        a = self.pilot("PilotoA8", udp=False)
        c = self.pilot("PilotoC8", udp=False)
        self.make_tcp_only(c)

        sent = position(a.pid, 1, 700)  # entre 400 y 1000 bytes: el server lo comprime
        self.assertTrue(400 < len(sent) < 1000)
        mrclient.send_packet(a.sock, sent)
        packet = mrclient.recv_until(c.sock, lambda p: p.startswith(b"ABG:"), 2.0)
        self.assertIsNotNone(packet, "C no recibio la posicion grande comprimida por TCP")
        self.assertEqual(zlib.decompress(packet[4:]), sent)

    def test_on_player_transport_event_and_reliable_path(self):
        c = self.pilot("PilotoC9", udp=False)
        for _ in range(50):
            mrclient.send_packet(c.sock, b"Ft")
        mrclient.send_packet(c.sock, b"p")

        events = []

        def collect_events(packet):
            if packet.startswith(b"E:mrci"):
                events.append(packet)
            return packet.startswith(b"E:mrci3:")

        self.assertIsNotNone(mrclient.recv_until(c.sock, collect_events, 3.0), "faltan eventos fiables por TCP")
        self.assertEqual(events, [b"E:mrci1:a", b"E:mrci2:b", b"E:mrci3:c"])
        # nada mas llega: el evento Lua se disparo una sola vez
        self.assertEqual([p for p in mrclient.collect(c.sock, 0.5) if p.startswith(b"E:mrci")], [])
        line = "MRCI transport name=%s kind=tcp" % c.name
        self.assertEqual(wait_for_log(line).count(line), 1)

        # ida y vuelta fiable: evento del cliente -> Lua -> TriggerClientEvent -> TCP
        mrclient.send_packet(c.sock, b"E:mrciEcho:hola")
        self.assertIsNotNone(
            mrclient.recv_until(c.sock, lambda p: p == b"E:mrciPong:hola", 2.0),
            "no volvio el evento fiable por TCP",
        )

    def test_old_launcher_without_ft(self):
        # Un launcher 1.0: sin `Ft`, sin UDP. Sigue conectado y atendido por TCP.
        old = self.pilot("PilotoO7", udp=False)
        time.sleep(15.0)

        mrclient.send_packet(old.sock, b"p")
        self.assertIsNotNone(
            mrclient.recv_until(old.sock, lambda packet: packet[:2] == b"Ss", 2.0),
            "el cliente sin Ft dejo de ser atendido por TCP",
        )
        # sin Ft, el p de respuesta sigue siendo solo UDP: nunca por TCP
        leftovers = mrclient.collect(old.sock, 1.0)
        self.assertNotIn(b"p", leftovers)
        self.assertNotIn(TCP_ONLY_LINE % old.name, read_log())


if __name__ == "__main__":
    unittest.main(verbosity=2)
