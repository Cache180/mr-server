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


def _as_bytes(value):
    return value.encode("utf-8") if isinstance(value, str) else bytes(value)


def handshake(sock, header, identity_json, timeout=5.0):
    """Hace el saludo de un launcher: `C`, cabecera de version, identidad.

    Envia el byte de tipo de conexion `C` (sin marco), el paquete de version
    `header` (p. ej. `MR1.0`) y, si el servidor contesta `A`, el paquete de
    identidad. Devuelve `(ok, reply)`: `ok` es True solo si la respuesta final
    es `P<id>` (jugador aceptado); `reply` es el cuerpo de ese ultimo paquete
    (o el de la expulsion `K...` si el servidor rechazo en cualquier paso).
    """
    sock.sendall(b"C")
    send_packet(sock, _as_bytes(header))
    first = recv_packet(sock, timeout)
    if first != b"A":
        return False, first
    send_packet(sock, _as_bytes(identity_json))
    reply = recv_packet(sock, timeout)
    return reply[:1] == b"P" and reply[1:].isdigit(), reply
