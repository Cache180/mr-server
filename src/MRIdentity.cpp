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

TEST_CASE("MR::IsValidPilotName") {
    CHECK(MR::IsValidPilotName("abc"));
    CHECK(MR::IsValidPilotName("Jesus.211_cache-1")); // 17
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
