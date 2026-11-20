// BeamMP, the BeamNG.drive multiplayer mod.
// Copyright (C) 2024 BeamMP Ltd., BeamMP team and contributors.
//
// BeamMP Ltd. can be contacted by electronic mail via contact@beammp.com.
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published
// by the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

#include "THeartbeatThread.h"

#include "Client.h"
#include "Common.h"
#include <chrono>
#include <nlohmann/json.hpp>
#include <thread>

// MR Server does not talk to any backend. This thread is kept because
// - the "Heartbeat" subsystem must become Good for the server to finish starting
//   (joins are refused while "Main" is still Starting), and
// - it keeps `lastCall` fresh, which is the body of the information packet (`I` query).
void THeartbeatThread::operator()() {
    RegisterThread("Heartbeat");
    constexpr auto RefreshInterval = std::chrono::seconds(5);
    constexpr auto PollInterval = std::chrono::milliseconds(100);

    // lastCall must be filled before anyone can be served an `I` query.
    GenerateCall();
    Application::SetSubsystemStatus("Heartbeat", Application::Status::Good);

    auto LastRefresh = std::chrono::steady_clock::now();
    while (!Application::IsShuttingDown()) {
        std::this_thread::sleep_for(PollInterval);
        const auto Now = std::chrono::steady_clock::now();
        if (Now - LastRefresh >= RefreshInterval) {
            GenerateCall();
            LastRefresh = Now;
        }
    }
}

void THeartbeatThread::GenerateCall() {
    nlohmann::json Ret = {
        { "players", std::to_string(mServer.ClientCount()) },
        { "maxplayers", std::to_string(Application::Settings.getAsInt(Settings::Key::General_MaxPlayers)) },
        { "port", std::to_string(Application::Settings.getAsInt(Settings::Key::General_Port)) },
        { "map", Application::Settings.getAsString(Settings::Key::General_Map) },
        { "private", Application::Settings.getAsBool(Settings::Key::General_Private) ? "true" : "false" },
        { "version", Application::ServerVersionString() },
        { "clientversion", Application::ClientMinimumVersion().AsString() },
        { "name", Application::Settings.getAsString(Settings::Key::General_Name) },
        { "tags", Application::Settings.getAsString(Settings::Key::General_Tags) },
        { "guests", Application::Settings.getAsBool(Settings::Key::General_AllowGuests) ? "true" : "false" },
        { "modlist", mResourceManager.TrimmedList() },
        { "modstotalsize", std::to_string(mResourceManager.MaxModSize()) },
        { "modstotal", std::to_string(mResourceManager.ModsLoaded()) },
        { "playerslist", GetPlayers() },
        { "desc", Application::Settings.getAsString(Settings::Key::General_Description) }
    };

    lastCall = Ret.dump();
}
THeartbeatThread::THeartbeatThread(TResourceManager& ResourceManager, TServer& Server)
    : mResourceManager(ResourceManager)
    , mServer(Server) {
    Application::SetSubsystemStatus("Heartbeat", Application::Status::Starting);
    Application::RegisterShutdownHandler([&] {
        Application::SetSubsystemStatus("Heartbeat", Application::Status::ShuttingDown);
        if (mThread.joinable()) {
            mThread.join();
        }
        Application::SetSubsystemStatus("Heartbeat", Application::Status::Shutdown);
    });
    Start();
}
std::string THeartbeatThread::GetPlayers() {
    std::string Return;
    mServer.ForEachClient([&](const std::weak_ptr<TClient>& ClientPtr) -> bool {
        ReadLock Lock(mServer.GetClientMutex());
        if (auto Client = ClientPtr.lock()) {
            Return += Client->GetName() + ";";
        }
        return true;
    });
    return Return;
}
/*THeartbeatThread::~THeartbeatThread() {
}*/
