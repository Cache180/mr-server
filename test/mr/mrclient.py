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

import json
import socket
import struct
import time

_HEADER = struct.Struct("<i")


def connect(host, port, rcvbuf=None):
    """Abre una conexion TCP al servidor.

    `rcvbuf` (bytes) reduce el buffer de recepcion antes de conectar, para
    simular un cliente lento cuyo socket se llena enseguida.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if rcvbuf is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        sock.settimeout(5.0)
        sock.connect((host, port))
    except BaseException:
        sock.close()
        raise
    return sock


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


# --- Sesion completa (resincronizacion de recursos hasta quedar "synced") ---

class ProtocolError(Exception):
    """El servidor no siguio la secuencia esperada del protocolo."""


# Magic que el servidor entrego en el paquete `U` de cada sesion abierta con
# `join`, por id de jugador; `open_udp` lo consume como hace el launcher real.
_MAGIC_BY_PID = {}

_MAGIC_SIZE = 64
_UDP_MAGIC_REPEATS = 10  # el launcher real repite el magic 10 veces
_UDP_MAX_PAYLOAD = 400  # por encima de esto el launcher comprime (`ABG:`); aqui no se necesita


def identity_json(name, install):
    return json.dumps({"name": name, "install": install}, separators=(",", ":")).encode("utf-8")


def complete_resources(sock, timeout=5.0):
    """Cierra la fase de recursos: envia `Done` y lee `U` (magic) y `M` (mapa).

    Devuelve el magic (64 bytes) que el servidor espera ver por UDP.
    """
    send_packet(sock, b"Done")
    magic = recv_packet(sock, timeout)
    if magic[:1] != b"U" or len(magic) != 1 + _MAGIC_SIZE:
        raise ProtocolError("esperaba el paquete U, llego %r" % (magic[:16],))
    map_packet = recv_packet(sock, timeout)
    if map_packet[:1] != b"M":
        raise ProtocolError("esperaba el paquete M, llego %r" % (map_packet[:16],))
    return magic[1:]


def recv_until(sock, predicate, timeout=5.0):
    """Lee paquetes TCP hasta que `predicate(paquete)` sea verdadero.

    Devuelve ese paquete, o None si vence `timeout` (segundos, plazo total).
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            packet = recv_packet(sock, remaining)
        except socket.timeout:
            return None
        if predicate(packet):
            return packet


def collect(sock, duration):
    """Todos los paquetes TCP que llegan durante `duration` segundos."""
    seen = []
    recv_until(sock, lambda packet: seen.append(packet) or False, duration)
    return seen


def join(host, port, name, install, header="MR1.0", timeout=5.0, rcvbuf=None):
    """Entra como `name` y deja la sesion sincronizada. Devuelve `(sock, pid)`.

    Hace lo que un launcher: saludo, identidad, `Done`, `H` y espera `Sn`. Un
    `p` posterior confirma que el servidor termino de sincronizarnos: su
    respuesta `Ss` solo sale por la cola del cliente cuando ya esta "synced".
    """
    sock = connect(host, port, rcvbuf)
    try:
        ok, reply = handshake(sock, header, identity_json(name, install), timeout)
        if not ok:
            raise ProtocolError("no aceptado: %r" % (reply,))
        pid = int(reply[1:])
        _MAGIC_BY_PID[pid] = complete_resources(sock, timeout)
        send_packet(sock, b"H")
        if recv_until(sock, lambda packet: packet[:2] == b"Sn", timeout) is None:
            raise ProtocolError("el servidor no envio Sn tras H")
        send_packet(sock, b"p")
        if recv_until(sock, lambda packet: packet[:2] == b"Ss", timeout) is None:
            raise ProtocolError("el servidor no completo la sincronizacion")
    except BaseException:
        sock.close()
        raise
    return sock, pid


# --- UDP (formato del launcher: chr(id + 1) + ":" + payload) ---

def udp_send(udpsock, pid, payload):
    """Envia `payload` por UDP como lo hace el launcher (sin compresion)."""
    payload = _as_bytes(payload)
    if len(payload) > _UDP_MAX_PAYLOAD:
        raise ValueError("payload UDP de %d bytes: el launcher comprimiria, aqui no" % len(payload))
    udpsock.send(bytes([pid + 1]) + b":" + payload)


def udp_recv(udpsock, timeout=5.0):
    """Recibe un datagrama del servidor (sin prefijo de id). Lanza socket.timeout."""
    udpsock.settimeout(timeout)
    return udpsock.recv(4096)


def udp_recv_until(udpsock, predicate, timeout=5.0):
    """Como `recv_until` pero por UDP; devuelve el datagrama o None al vencer."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            datagram = udp_recv(udpsock, remaining)
        except socket.timeout:
            return None
        if predicate(datagram):
            return datagram


def open_udp(host, port, pid, magic=None, timeout=5.0):
    """Abre el canal UDP como el launcher y espera a que el servidor lo enlace.

    Envia el magic de la sesion (el de `join` para `pid`) 10 veces y comprueba
    el enlace con `p` hasta recibir la respuesta `p` por UDP. Devuelve el socket.
    """
    if magic is None:
        magic = _MAGIC_BY_PID.pop(pid, None)
    if magic is None:
        raise ProtocolError("no hay magic para el jugador %d (falta join)" % pid)
    udpsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udpsock.connect((host, port))
        for _ in range(_UDP_MAGIC_REPEATS):
            udp_send(udpsock, pid, magic)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            udp_send(udpsock, pid, b"p")
            if udp_recv_until(udpsock, lambda datagram: datagram == b"p", 0.25) is not None:
                return udpsock
        raise ProtocolError("el servidor no enlazo el canal UDP del jugador %d" % pid)
    except BaseException:
        udpsock.close()
        raise
