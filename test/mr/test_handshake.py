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

"""Pruebas del handshake `MR` y de la identidad autodeclarada.

El servidor ya debe estar corriendo (lo arranca el workflow de CI) con
`test/mr/ServerConfig.ci.toml`. Variables de entorno:

    MR_SERVER_PORT  puerto (por defecto 30899)
    MR_SERVER_HOST  host (por defecto 127.0.0.1)

Cada prueba usa un nombre de piloto propio y cierra sus sockets, para poder
compartir el servidor con las demas suites.
"""

import json
import os
import re
import struct
import sys
import time
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mrclient  # noqa: E402

HOST = os.environ.get("MR_SERVER_HOST", "127.0.0.1")
PORT = int(os.environ.get("MR_SERVER_PORT", "30899"))

KICK_WRONG_LAUNCHER = "Este servidor requiere MR Launcher: https://muertazosracing.com/launcher"
KICK_OUTDATED = "MR Launcher desactualizado"
KICK_NAME_IN_USE = "Nombre en uso: elige otro nombre de piloto"

INSTALL_A = "a" * 32
INSTALL_B = "b" * 32


def identity(name, install):
    return json.dumps({"name": name, "install": install}, separators=(",", ":")).encode("utf-8")


class HandshakeTests(unittest.TestCase):
    def open(self):
        sock = mrclient.connect(HOST, PORT)
        self.addCleanup(sock.close)
        return sock

    def join(self, name, install, header="MR1.0"):
        """Entra como `name`; devuelve el socket ya aceptado (`P<id>`)."""
        sock = self.open()
        ok, reply = mrclient.handshake(sock, header, identity(name, install))
        self.assertTrue(ok, "no aceptado: %r" % (reply,))
        return sock

    def assert_kicked(self, reply, text):
        self.assertEqual(reply[:1], b"K", "no es una expulsion: %r" % (reply,))
        self.assertIn(text.encode("utf-8"), reply)

    def assert_still_in_server(self, sock):
        """El servidor sigue atendiendo a este cliente: tras `Done` envia `U` y `M`."""
        try:
            mrclient.complete_resources(sock)
        except mrclient.ProtocolError as err:
            self.fail(str(err))

    def test_official_header_rejected(self):
        ok, reply = mrclient.handshake(self.open(), "VC2.8", identity("CiOficial", INSTALL_A))
        self.assertFalse(ok)
        self.assert_kicked(reply, KICK_WRONG_LAUNCHER)

    def test_outdated_rejected(self):
        ok, reply = mrclient.handshake(self.open(), "MR0.9", identity("CiViejo", INSTALL_A))
        self.assertFalse(ok)
        self.assert_kicked(reply, KICK_OUTDATED)

    def test_bare_mr_header(self):
        # `MR` sin version: es un launcher MR (roto o viejo), no uno "equivocado"
        ok, reply = mrclient.handshake(self.open(), "MR", identity("CiSinVersion", INSTALL_A))
        self.assertFalse(ok)
        self.assert_kicked(reply, KICK_OUTDATED)
        self.assert_kicked(reply, "se requiere la version >= 1.0.0")

    def test_oversized_mr_header(self):
        ok, reply = mrclient.handshake(self.open(), "MR1." + "0" * 40, identity("CiCabeceraLarga", INSTALL_A))
        self.assertFalse(ok)
        self.assert_kicked(reply, KICK_OUTDATED)

    def accept_header_only(self):
        """Saluda con `MR1.0` y espera `A`: el cliente queda sin nombre (sin autenticar)."""
        sock = self.open()
        sock.sendall(b"C")
        mrclient.send_packet(sock, b"MR1.0")
        self.assertEqual(mrclient.recv_packet(sock), b"A")
        return sock

    def assert_other_client_accepted(self, name):
        ok, reply = mrclient.handshake(self.open(), "MR1.0", identity(name, INSTALL_B))
        self.assertTrue(ok, "el servidor dejo de aceptar clientes: %r" % (reply,))

    def test_compressed_packet_before_auth_rejected(self):
        sock = self.accept_header_only()
        mrclient.send_packet(sock, b"ABG:" + zlib.compress(b"\x00" * 4096))
        self.assert_kicked(mrclient.recv_packet(sock), "Identidad invalida: formato invalido")
        self.assert_other_client_accepted("CiTrasZip")

    def test_compressed_valid_identity_before_auth_rejected(self):
        # Una identidad valida pero comprimida tampoco se descomprime antes de autenticar.
        sock = self.accept_header_only()
        mrclient.send_packet(sock, b"ABG:" + zlib.compress(identity("CiComprimido", INSTALL_A)))
        self.assert_kicked(mrclient.recv_packet(sock), "Identidad invalida: formato invalido")
        self.assert_other_client_accepted("CiTrasZip2")

    def test_compressed_header_rejected(self):
        sock = self.open()
        sock.sendall(b"C")
        mrclient.send_packet(sock, b"ABG:" + zlib.compress(b"MR1.0"))
        self.assert_kicked(mrclient.recv_packet(sock), "Identidad invalida: formato invalido")
        self.assert_other_client_accepted("CiTrasZip3")

    def test_large_packet_before_auth_rejected(self):
        # antes de autenticar el cuerpo de un paquete se acota a 4096 bytes: basta la cabecera de longitud
        sock = self.accept_header_only()
        sock.sendall(struct.pack("<i", 5000))
        self.assert_kicked(mrclient.recv_packet(sock), "Header size limit exceeded")
        self.assert_other_client_accepted("CiTrasGrande")

    def test_valid_identity_accepted(self):
        ok, reply = mrclient.handshake(self.open(), "MR1.0", identity("CiPiloto", INSTALL_A))
        self.assertTrue(ok, reply)
        self.assertRegex(reply, re.compile(rb"^P[0-9]+$"))

    def test_bad_name_rejected(self):
        ok, reply = mrclient.handshake(self.open(), "MR1.0", identity("a b", INSTALL_A))
        self.assertFalse(ok)
        self.assert_kicked(reply, "Identidad invalida: nombre invalido")

    def test_oversized_identity_rejected(self):
        ok, reply = mrclient.handshake(self.open(), "MR1.0", b"x" * 300)
        self.assertFalse(ok)
        self.assert_kicked(reply, "Identidad invalida: paquete demasiado grande")

    def test_garbage_identity_rejected(self):
        ok, reply = mrclient.handshake(self.open(), "MR1.0", b"\xff\xfe{")
        self.assertFalse(ok)
        self.assert_kicked(reply, "Identidad invalida: formato invalido")

    def test_name_in_use_other_install(self):
        first = self.join("CiOcupado", INSTALL_A)
        ok, reply = mrclient.handshake(self.open(), "MR1.0", identity("CIOCUPADO", INSTALL_B))
        self.assertFalse(ok)
        self.assert_kicked(reply, KICK_NAME_IN_USE)
        # el jugador original no se toca: su socket sigue abierto y el server le responde
        self.assert_still_in_server(first)

    def test_same_install_replaces(self):
        first = self.join("CiReemplazo", INSTALL_A)
        ok, reply = mrclient.handshake(self.open(), "MR1.0", identity("CiReemplazo", INSTALL_A))
        self.assertTrue(ok, "el reemplazo no fue aceptado: %r" % (reply,))
        self.assertRegex(reply, re.compile(rb"^P[0-9]+$"))
        # el socket del jugador viejo se cierra (no basta un simple timeout)
        with self.assertRaises(ConnectionError):
            mrclient.recv_packet(first)

    def test_silent_client_does_not_block(self):
        silent = self.open()
        silent.sendall(b"C")
        mrclient.send_packet(silent, b"MR1.0")
        # el server ya esta a mitad de autenticacion con este cliente: espera su identidad
        self.assertEqual(mrclient.recv_packet(silent), b"A")
        started = time.monotonic()
        ok, reply = mrclient.handshake(self.open(), "MR1.0", identity("CiSilencio", INSTALL_B))
        elapsed = time.monotonic() - started
        self.assertTrue(ok, reply)
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
