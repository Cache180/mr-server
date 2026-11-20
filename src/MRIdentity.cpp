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

#include "MRIdentity.h"

#include <algorithm>
#include <array>
#include <fmt/format.h>
#include <nlohmann/json.hpp>
#include <openssl/evp.h>

namespace MR {

namespace {
    constexpr size_t MaxPacketBytes = 256;
    constexpr size_t NameMin = 3;
    constexpr size_t NameMax = 20;
    constexpr size_t InstallMin = 32;
    constexpr size_t InstallMax = 64;
    constexpr size_t MrIdLength = 32;

    // Solo se admite ASCII: la longitud en bytes coincide con la longitud en caracteres.
    // Cualquier byte >= 0x80 (UTF-8 multibyte) cae fuera de las clases y se rechaza.
    bool IsAlnum(char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
    }

    char ToLowerAscii(char c) {
        return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
    }

    bool EqualsIgnoreCaseAscii(std::string_view A, std::string_view B) {
        return std::equal(A.begin(), A.end(), B.begin(), B.end(),
            [](char X, char Y) { return ToLowerAscii(X) == ToLowerAscii(Y); });
    }
}

bool IsValidPilotName(std::string_view Name) {
    if (Name.size() < NameMin || Name.size() > NameMax) {
        return false;
    }
    return std::all_of(Name.begin(), Name.end(), [](char c) {
        return IsAlnum(c) || c == '_' || c == '.' || c == '-';
    });
}

bool IsValidInstallKey(std::string_view Install) {
    if (Install.size() < InstallMin || Install.size() > InstallMax) {
        return false;
    }
    return std::all_of(Install.begin(), Install.end(), IsAlnum);
}

std::string DeriveMrId(std::string_view Install) {
    std::array<unsigned char, EVP_MAX_MD_SIZE> Digest {};
    unsigned int DigestLen = 0;
    if (EVP_Digest(Install.data(), Install.size(), Digest.data(), &DigestLen, EVP_sha256(), nullptr) != 1) {
        return {};
    }
    std::string Hex;
    Hex.reserve(DigestLen * 2);
    for (unsigned int i = 0; i < DigestLen; ++i) {
        Hex += fmt::format("{:02x}", Digest[i]);
    }
    Hex.resize(MrIdLength);
    return Hex;
}

std::optional<Identity> ParseIdentityPacket(std::string_view Raw, std::string& Reason) {
    if (Raw.size() > MaxPacketBytes) {
        Reason = "paquete demasiado grande";
        return std::nullopt;
    }
    // allow_exceptions = false: JSON o UTF-8 invalidos producen un valor "discarded", no una excepcion.
    nlohmann::json Json = nlohmann::json::parse(Raw.begin(), Raw.end(), nullptr, false);
    if (!Json.is_object()) {
        Reason = "formato invalido";
        return std::nullopt;
    }
    auto NameIt = Json.find("name");
    auto InstallIt = Json.find("install");
    if (NameIt == Json.end() || InstallIt == Json.end() || !NameIt->is_string() || !InstallIt->is_string()) {
        Reason = "formato invalido";
        return std::nullopt;
    }
    const auto& Name = NameIt->get_ref<const std::string&>();
    const auto& Install = InstallIt->get_ref<const std::string&>();
    if (!IsValidPilotName(Name)) {
        Reason = "nombre invalido (3-20 caracteres: letras, numeros, _ . -)";
        return std::nullopt;
    }
    if (!IsValidInstallKey(Install)) {
        Reason = "instalacion invalida";
        return std::nullopt;
    }
    return Identity { Name, DeriveMrId(Install) };
}

NameClash ClassifyNameClash(std::string_view Name, std::string_view MrId, std::string_view ExistingName, std::string_view ExistingMrId) {
    if (!EqualsIgnoreCaseAscii(Name, ExistingName)) {
        return NameClash::None;
    }
    return MrId == ExistingMrId ? NameClash::SameInstall : NameClash::OtherInstall;
}

std::string KickOutdated(const Version& Min) {
    Version Copy = Min; // Version::AsString no es const
    return fmt::format("MR Launcher desactualizado: se requiere la version >= {}", Copy.AsString());
}

std::string KickBadIdentity(std::string_view Reason) {
    return fmt::format("Identidad invalida: {}", Reason);
}

}

TEST_CASE("MR::IsValidPilotName") {
    CHECK(MR::IsValidPilotName("abc"));
    CHECK(MR::IsValidPilotName("Piloto.Uno_mr-123")); // 17
    CHECK(MR::IsValidPilotName(std::string(20, 'a')));
    CHECK_FALSE(MR::IsValidPilotName("ab"));
    CHECK_FALSE(MR::IsValidPilotName(std::string(21, 'a')));
    CHECK_FALSE(MR::IsValidPilotName("con espacio"));
    CHECK_FALSE(MR::IsValidPilotName("ni\xC3\xB1o")); // enie en UTF-8
    CHECK_FALSE(MR::IsValidPilotName("a\nb"));
    CHECK_FALSE(MR::IsValidPilotName(""));
}

TEST_CASE("MR::DeriveMrId") {
    auto id = MR::DeriveMrId(std::string(32, 'a'));
    CHECK(id == "3ba3f5f43b92602683c19aee62a20342"); // sha256("a"*32)[:32]
    CHECK(MR::DeriveMrId(std::string(32, 'b')) != id);
}

TEST_CASE("MR::ParseIdentityPacket") {
    std::string why;
    auto ok = MR::ParseIdentityPacket(R"({"name":"Piloto_1","install":")" + std::string(32, 'a') + R"("})", why);
    REQUIRE(ok.has_value());
    CHECK(ok->Name == "Piloto_1");
    CHECK(ok->MrId == "3ba3f5f43b92602683c19aee62a20342");
    CHECK_FALSE(MR::ParseIdentityPacket(std::string(257, 'x'), why).has_value());
    CHECK(why == "paquete demasiado grande");
    CHECK_FALSE(MR::ParseIdentityPacket("no json", why).has_value());
    CHECK(why == "formato invalido");
    CHECK_FALSE(MR::ParseIdentityPacket(R"({"name":123,"install":"x"})", why).has_value());
    CHECK(why == "formato invalido");
    CHECK_FALSE(MR::ParseIdentityPacket(R"({"name":"a b","install":")" + std::string(32, 'a') + R"("})", why).has_value());
    CHECK(why == "nombre invalido (3-20 caracteres: letras, numeros, _ . -)");
    CHECK_FALSE(MR::ParseIdentityPacket(R"({"name":"abc","install":"corta"})", why).has_value());
    CHECK(why == "instalacion invalida");
    CHECK_FALSE(MR::ParseIdentityPacket("\xff\xfe{", why).has_value()); // UTF-8 invalido: no lanza
}

TEST_CASE("MR::ClassifyNameClash") {
    CHECK(MR::ClassifyNameClash("Pepe", "aa", "Juan", "bb") == MR::NameClash::None);
    CHECK(MR::ClassifyNameClash("Pepe", "aa", "pepe", "aa") == MR::NameClash::SameInstall);
    CHECK(MR::ClassifyNameClash("PEPE", "aa", "pepe", "bb") == MR::NameClash::OtherInstall);
}
