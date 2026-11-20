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

"""Cliente TCP minimo para las pruebas de integracion del servidor.

Marco del protocolo (igual que TNetwork::TCPSend / TCPRcv): 4 bytes de
longitud (int32 little-endian) seguidos del cuerpo. Solo la identificacion
inicial (un byte de codigo como `I`) viaja sin marco.
"""

import socket
import struct

_HEADER = struct.Struct("<i")


def connect(host, port):
    """Abre una conexion TCP al servidor."""
    return socket.create_connection((host, port), timeout=5.0)


def send_packet(sock, data):
    """Envia `data` (bytes) con el marco de 4 bytes de longitud."""
    sock.sendall(_HEADER.pack(len(data)) + data)


def _recv_exact(sock, count):
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError(
                "conexion cerrada con %d bytes pendientes de %d" % (remaining, count)
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_packet(sock, timeout=5.0):
    """Recibe un paquete con marco y devuelve el cuerpo (bytes)."""
    sock.settimeout(timeout)
    (length,) = _HEADER.unpack(_recv_exact(sock, _HEADER.size))
    if length < 0:
        raise ValueError("longitud de paquete negativa: %d" % length)
    return _recv_exact(sock, length)
