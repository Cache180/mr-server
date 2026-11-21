// BeamMP, the BeamNG.drive multiplayer mod.
// Copyright (C) 2026 BeamMP Ltd., BeamMP team and contributors.
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

#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>

class TConnectionLimiter {
public:
    struct TStats {
        size_t CurrentGlobal = 0;
        size_t MaxGlobal = 0;
        size_t ActiveIpBuckets = 0;
        size_t CurrentMaxPerIp = 0;
        size_t MaxPerIp = 0;
        size_t SaturatedIpBuckets = 0;
    };

    class TGuard {
    public:
        TGuard() = default;
        TGuard(TConnectionLimiter* owner, std::string ip);

        TGuard(const TGuard&) = delete;
        TGuard& operator=(const TGuard&) = delete;

        ~TGuard() { Release(); }

        // not threadsafe
        TGuard(TGuard&& other) noexcept { *this = std::move(other); }
        // not threadsafe
        TGuard& operator=(TGuard&& other) noexcept;

        // The connection stops counting against the pre-authentication quotas (it keeps counting
        // against the global and per-IP totals until the guard is released). Idempotent.
        // not threadsafe
        void EndPreAuth();

    private:
        friend class TConnectionLimiter;

        // not threadsafe
        void Release();

        TConnectionLimiter* mOwner { nullptr };
        std::string mIp;
        bool mPreAuth { false };
    };

    // maxPreAuthPerIp / maxPreAuthGlobal bound the connections that were accepted but have not called
    // TGuard::EndPreAuth() yet; they are always a subset of the totals maxPerIp / maxGlobal.
    TConnectionLimiter(size_t maxPerIp, size_t maxGlobal, size_t maxPreAuthPerIp, size_t maxPreAuthGlobal);

    [[nodiscard]] std::optional<TGuard> TryAcquire(const std::string& ip);
    [[nodiscard]] TStats GetStats();

private:
    static void DecrementIp(std::unordered_map<std::string, size_t>& Map, const std::string& ip) {
        auto It = Map.find(ip);
        if (It != Map.end()) {
            // this guard exists to avoid underflow in case something goes wrong and this gets called too many times
            if (It->second > 0)
                --It->second;
            if (It->second == 0)
                Map.erase(It);
        }
    }

    // needs mMutex held
    void EndPreAuthLocked(const std::string& ip) {
        DecrementIp(mPreAuthPerIp, ip);
        // this guard exists to avoid underflow in case something goes wrong and this gets called too many times
        if (mPreAuthGlobal > 0)
            --mPreAuthGlobal;
    }

    void EndPreAuth(const std::string& ip) {
        std::unique_lock Lock { mMutex };
        EndPreAuthLocked(ip);
    }

    void Release(const std::string& ip, bool preAuth) {
        std::unique_lock Lock { mMutex };
        DecrementIp(mPerIp, ip);
        // this guard exists to avoid underflow in case something goes wrong and this gets called too many times
        if (mGlobal > 0)
            --mGlobal;
        if (preAuth)
            EndPreAuthLocked(ip);
    }

    const size_t mMaxPerIp;
    const size_t mMaxGlobal;
    const size_t mMaxPreAuthPerIp;
    const size_t mMaxPreAuthGlobal;

    std::mutex mMutex { };
    std::unordered_map<std::string, size_t> mPerIp { };
    size_t mGlobal = 0;
    std::unordered_map<std::string, size_t> mPreAuthPerIp { };
    size_t mPreAuthGlobal = 0;
};
