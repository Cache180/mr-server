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

#pragma once

#include <atomic>
#include <chrono>
#include <memory>
#include <optional>
#include <queue>
#include <string>
#include <unordered_set>
#include <utility>

#include "BoostAliases.h"
#include "Common.h"
#include "Compat.h"
#include "VehicleData.h"

class TServer;

#ifdef BEAMMP_WINDOWS
// for socklen_t
#include <WS2tcpip.h>
#endif // WINDOWS

struct TConnection final {
    ip::tcp::socket Socket;
    ip::tcp::endpoint SockAddr;
};

class TClient final {
public:
    using TSetOfVehicleData = std::vector<TVehicleData>;

    struct TVehicleDataLockPair {
        TSetOfVehicleData* VehicleData;
        std::unique_lock<std::mutex> Lock;
    };

    TClient(TServer& Server, ip::tcp::socket&& Socket);
    TClient(const TClient&) = delete;
    ~TClient();
    TClient& operator=(const TClient&) = delete;

    void AddNewCar(int Ident, const nlohmann::json& Data);
    void SetCarData(int Ident, const nlohmann::json& Data);
    void SetCarPosition(int Ident, const std::string& Data);
    TVehicleDataLockPair GetAllCars();
    void SetName(const std::string& Name) { mName = Name; }
    void SetRoles(const std::string& Role) { mRole = Role; }
    void SetIdentifier(const std::string& key, const std::string& value) { mIdentifiers[key] = value; }
    nlohmann::json GetCarData(int Ident);
    std::string GetCarPositionRaw(int Ident);
    void SetUDPAddr(const ip::udp::endpoint& Addr) { mUDPAddress = Addr; }
    void SetTCPSock(ip::tcp::socket&& CSock) { mSocket = std::move(CSock); }
    // Returns true only for the thread that actually performs socket shutdown/close.
    [[nodiscard]] bool Disconnect(std::string_view Reason);
    bool IsDisconnected() const {
        return mDisconnectState.load(std::memory_order_acquire) != EDisconnectState::Connected;
    }
    // locks
    void DeleteCar(int Ident);
    [[nodiscard]] const std::unordered_map<std::string, std::string>& GetIdentifiers() const { return mIdentifiers; }
    [[nodiscard]] const ip::udp::endpoint& GetUDPAddr() const { return mUDPAddress; }
    [[nodiscard]] ip::udp::endpoint& GetUDPAddr() { return mUDPAddress; }
    [[nodiscard]] ip::tcp::socket& GetTCPSock() { return mSocket; }
    [[nodiscard]] const ip::tcp::socket& GetTCPSock() const { return mSocket; }
    [[nodiscard]] std::string GetRoles() const { return mRole; }
    [[nodiscard]] std::string GetName() const { return mName; }
    void SetUnicycleID(int ID) { mUnicycleID = ID; }
    void SetID(int ID) { mID = ID; }
    [[nodiscard]] int GetOpenCarID() const;
    [[nodiscard]] int GetCarCount() const;
    void ClearCars();
    [[nodiscard]] int GetID() const { return mID; }
    [[nodiscard]] int GetUnicycleID() const { return mUnicycleID; }
    [[nodiscard]] bool IsUDPConnected() const { return mIsUDPConnected; }
    // "Solo TCP" client: its UDP does not work (control packet `Ft`, over TCP). Everything that
    // would go out over UDP goes through its per-client queue (EnqueuePacket) instead.
    // SetTcpOnly() returns true only the first time it is called.
    [[nodiscard]] bool IsTcpOnly() const { return mIsTcpOnly.load(std::memory_order_acquire); }
    [[nodiscard]] bool SetTcpOnly() { return !mIsTcpOnly.exchange(true, std::memory_order_acq_rel); }
    [[nodiscard]] bool IsSynced() const { return mIsSynced; }
    [[nodiscard]] bool IsSyncing() const { return mIsSyncing; }
    [[nodiscard]] bool IsGuest() const { return mIsGuest; }
    void SetIsGuest(bool NewIsGuest) { mIsGuest = NewIsGuest; }
    void SetIsSynced(bool NewIsSynced) { mIsSynced = NewIsSynced; }
    void SetIsSyncing(bool NewIsSyncing) { mIsSyncing = NewIsSyncing; }
    // Hard cap on the bytes queued for one client, whatever the client does: a client that never reads
    // its socket would otherwise make every reliable broadcast (and every `p` reply) pile up in RAM.
    static constexpr size_t kQueueHardCapBytes = 32 * 1024 * 1024;
    // Queues a packet. Thread-safe. When the queue goes over kQueueHardCapBytes the client is
    // disconnected and its queue dropped; packets enqueued after that are discarded.
    void EnqueuePacket(const std::vector<uint8_t>& Packet);
    // Bytes currently waiting in the queue. Producers add under the queue mutex in EnqueuePacket;
    // the single consumer (the Looper) subtracts under the same mutex via the two functions below.
    [[nodiscard]] size_t QueuedBytes() const { return mQueuedBytes.load(std::memory_order_acquire); }
    // Pops the front packet into Out (queue mutex held inside). Returns false if the queue is empty.
    [[nodiscard]] bool DequeuePacket(std::vector<uint8_t>& Out);
    void ClearQueue();
    // True only the first time it is called: lets the server log "dropping" once per client.
    [[nodiscard]] bool MarkQueueDropLogged() { return !mQueueDropLogged.exchange(true, std::memory_order_acq_rel); }
    [[nodiscard]] std::queue<std::vector<uint8_t>>& MissedPacketQueue() { return mPacketsSync; }
    [[nodiscard]] const std::queue<std::vector<uint8_t>>& MissedPacketQueue() const { return mPacketsSync; }
    [[nodiscard]] size_t MissedPacketQueueSize() const { return mPacketsSync.size(); }
    [[nodiscard]] std::mutex& MissedPacketQueueMutex() const { return mMissedPacketsMutex; }
    void SetIsUDPConnected(bool NewIsConnected) { mIsUDPConnected = NewIsConnected; }
    [[nodiscard]] TServer& Server() const;
    void UpdatePingTime();
    int SecondsSinceLastPing();
    void SetMagic(std::vector<uint8_t> magic) { mMagic = std::move(magic); }
    [[nodiscard]] const std::vector<uint8_t>& GetMagic() const { return mMagic; }

private:
    enum class EDisconnectState {
        Connected,
        Disconnecting,
        Disconnected
    };

    void InsertVehicle(int ID, const std::string& Data);

    TServer& mServer;
    bool mIsUDPConnected = false;
    std::atomic<bool> mIsTcpOnly { false };
    bool mIsSynced = false;
    bool mIsSyncing = false;
    mutable std::mutex mMissedPacketsMutex;
    std::queue<std::vector<uint8_t>> mPacketsSync;
    std::atomic<size_t> mQueuedBytes { 0 };
    std::atomic<bool> mQueueDropLogged { false };
    std::atomic<bool> mQueueOverflowed { false };
    std::unordered_map<std::string, std::string> mIdentifiers;
    bool mIsGuest = false;
    mutable std::mutex mVehicleDataMutex;
    mutable std::mutex mVehiclePositionMutex;
    TSetOfVehicleData mVehicleData;
    SparseArray<std::string> mVehiclePosition;
    // Empty until authentication succeeds: TNetwork::TCPRcv uses it to tell unauthenticated clients apart.
    std::string mName;
    // Once disconnect starts, this client is terminal and its socket must be treated as dead.
    std::atomic<EDisconnectState> mDisconnectState { EDisconnectState::Connected };
    ip::tcp::socket mSocket;
    ip::udp::endpoint mUDPAddress {};
    int mUnicycleID = -1;
    std::string mRole;
    std::string mDID;
    int mID = -1;
    std::chrono::time_point<std::chrono::high_resolution_clock> mLastPingTime = std::chrono::high_resolution_clock::now();
    std::vector<uint8_t> mMagic;
};

std::optional<std::weak_ptr<TClient>> GetClient(class TServer& Server, int ID);
