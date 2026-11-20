// MR Server, servidor multijugador de Muertazos Racing.
// Copyright (C) 2026 Muertazos Racing
//
// Este programa es software libre: puedes redistribuirlo y/o modificarlo
// bajo los terminos de la GNU Affero General Public License publicada por
// la Free Software Foundation, ya sea la version 3 de la Licencia o
// (a tu eleccion) cualquier version posterior.
//
// Este programa se distribuye con la esperanza de que sea util, pero SIN
// NINGUNA GARANTIA; sin siquiera la garantia implicita de COMERCIABILIDAD
// o IDONEIDAD PARA UN PROPOSITO PARTICULAR. Consulta la GNU Affero General
// Public License para mas detalles.
//
// Deberias haber recibido una copia de la GNU Affero General Public License
// junto con este programa. Si no, consulta <https://www.gnu.org/licenses/>.
//
// SPDX-License-Identifier: AGPL-3.0-or-later

#pragma once

#include "Common.h"
#include <optional>
#include <string>
#include <string_view>

// Identidad MR: nombre de piloto + clave de instalacion autodeclarados.
// Modulo puro: sin sockets, sin globales, sin logging.
namespace MR {

struct Identity {
    std::string Name;
    std::string MrId;
};

enum class NameClash {
    None,
    SameInstall,
    OtherInstall,
};

// 3-20 caracteres, solo [A-Za-z0-9_.-].
bool IsValidPilotName(std::string_view Name);
// 32-64 caracteres, solo [A-Za-z0-9].
bool IsValidInstallKey(std::string_view Install);
// sha256(Install) en hex minusculas, primeros 32 caracteres.
std::string DeriveMrId(std::string_view Install);
// Parsea el paquete JSON {"name":"...","install":"..."} (<= 256 bytes).
// Nunca lanza excepciones; si falla devuelve nullopt y deja el motivo en Reason.
std::optional<Identity> ParseIdentityPacket(std::string_view Raw, std::string& Reason);
// Compara nombres sin distinguir mayusculas (ASCII).
NameClash ClassifyNameClash(std::string_view Name, std::string_view MrId, std::string_view ExistingName, std::string_view ExistingMrId);

inline constexpr std::string_view KickWrongLauncher = "Este servidor requiere MR Launcher: https://muertazosracing.com/launcher";
inline constexpr std::string_view KickNameInUse = "Nombre en uso: elige otro nombre de piloto";
std::string KickOutdated(const Version& Min);
std::string KickBadIdentity(std::string_view Reason);

}
