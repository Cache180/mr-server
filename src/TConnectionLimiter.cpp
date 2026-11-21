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

#include "TConnectionLimiter.h"
#include <mutex>
#include <optional>
#include "Common.h"

TConnectionLimiter::TConnectionLimiter(size_t maxPerIp, size_t maxGlobal, size_t maxPreAuthPerIp, size_t maxPreAuthGlobal)
    : mMaxPerIp(maxPerIp)
    , mMaxGlobal(maxGlobal)
    , mMaxPreAuthPerIp(maxPreAuthPerIp)
    , mMaxPreAuthGlobal(maxPreAuthGlobal) {
    if (maxPerIp == 0) {
        beammp_errorf("Max connections count per IP is set to zero; the server would reject ALL connections");
        throw std::runtime_error("Invalid maximum connections per IP setting");
    }
    if (maxGlobal == 0) {
        beammp_errorf("Max connection count is set to zero; the server would reject ALL connections");
        throw std::runtime_error("Invalid maximum connections setting");
    }
    if (maxPreAuthPerIp == 0 || maxPreAuthGlobal == 0) {
        beammp_errorf("Max pre-authentication connection count is set to zero; the server would reject ALL connections");
        throw std::runtime_error("Invalid maximum pre-authentication connections setting");
    }
}

std::optional<TConnectionLimiter::TGuard> TConnectionLimiter::TryAcquire(const std::string& ip) {
    std::unique_lock Lock { mMutex };
    if (mGlobal >= mMaxGlobal) return std::nullopt;
    if (mPreAuthGlobal >= mMaxPreAuthGlobal) return std::nullopt;
    const auto PreAuthIt = mPreAuthPerIp.find(ip);
    if (PreAuthIt != mPreAuthPerIp.end() && PreAuthIt->second >= mMaxPreAuthPerIp) return std::nullopt;
    // `It` is the inserted element (so if insertion worked, its 0), or its the element that
    // was already there, in which case we must check the ip connection limit
    auto [It, _] = mPerIp.try_emplace(ip, 0);
    if (It->second >= mMaxPerIp) {
        return std::nullopt;
    }
    // now increment the counter finally
    ++It->second;
    ++mGlobal;
    ++mPreAuthPerIp[ip];
    ++mPreAuthGlobal;
    // RAII guard will drop the count once destructed
    return TGuard(this, ip);
}

TConnectionLimiter::TStats TConnectionLimiter::GetStats() {
    std::unique_lock Lock { mMutex };
    TStats Stats;
    Stats.CurrentGlobal = mGlobal;
    Stats.MaxGlobal = mMaxGlobal;
    Stats.ActiveIpBuckets = mPerIp.size();
    Stats.MaxPerIp = mMaxPerIp;
    for (const auto& [_, Count] : mPerIp) {
        if (Count > Stats.CurrentMaxPerIp) {
            Stats.CurrentMaxPerIp = Count;
        }
        if (Count >= mMaxPerIp) {
            ++Stats.SaturatedIpBuckets;
        }
    }
    return Stats;
}

TConnectionLimiter::TGuard::TGuard(TConnectionLimiter* owner, std::string ip)
    : mOwner(owner)
    , mIp(std::move(ip))
    , mPreAuth(true) {
    beammp_debugf("Acquired connection guard for {}", mIp);
}

TConnectionLimiter::TGuard& TConnectionLimiter::TGuard::operator=(TGuard&& other) noexcept {
    // identity check
    if (this != &other) {
        Release();
        mOwner = other.mOwner;
        mIp = std::move(other.mIp);
        mPreAuth = other.mPreAuth;
        other.mOwner = nullptr;
        other.mPreAuth = false;
        // setting this so its obvious when this happens, instead of being UB or empty string
        other.mIp = "<moved-from>";
    }
    return *this;
}

void TConnectionLimiter::TGuard::EndPreAuth() {
    if (mOwner && mPreAuth) {
        mPreAuth = false;
        mOwner->EndPreAuth(mIp);
    }
}

void TConnectionLimiter::TGuard::Release() {
    if (mOwner) {
        mOwner->Release(mIp, mPreAuth);
        mOwner = nullptr;
        mPreAuth = false;
        beammp_debugf("Released connection guard for {}", mIp);
    }
}

TEST_CASE("TConnectionLimiter pre-authentication quotas") {
    TConnectionLimiter Limiter(10, 128, 3, 32);
    std::vector<TConnectionLimiter::TGuard> Held;
    for (int i = 0; i < 3; ++i) {
        auto Guard = Limiter.TryAcquire("198.51.100.7");
        REQUIRE(Guard.has_value());
        Held.push_back(std::move(*Guard));
    }
    SUBCASE("the fourth pre-auth connection of one IP is rejected, other IPs are not") {
        CHECK_FALSE(Limiter.TryAcquire("198.51.100.7").has_value());
        CHECK(Limiter.TryAcquire("198.51.100.8").has_value());
    }
    SUBCASE("authenticated connections do not consume the pre-auth quota") {
        for (auto& Guard : Held)
            Guard.EndPreAuth();
        // 3 authenticated, 0 pre-auth: three more pre-auth fit, a fourth does not
        std::vector<TConnectionLimiter::TGuard> More;
        for (int i = 0; i < 3; ++i) {
            auto Guard = Limiter.TryAcquire("198.51.100.7");
            REQUIRE(Guard.has_value());
            More.push_back(std::move(*Guard));
        }
        CHECK_FALSE(Limiter.TryAcquire("198.51.100.7").has_value());
        for (auto& Guard : More)
            Guard.EndPreAuth();
        // 6 authenticated: the per-IP total of 10 still applies
        for (int i = 0; i < 4; ++i) {
            auto Guard = Limiter.TryAcquire("198.51.100.7");
            REQUIRE(Guard.has_value());
            Guard->EndPreAuth();
            More.push_back(std::move(*Guard));
        }
        CHECK_FALSE(Limiter.TryAcquire("198.51.100.7").has_value());
        CHECK(Limiter.GetStats().CurrentMaxPerIp == 10);
    }
    SUBCASE("EndPreAuth is idempotent and a moved guard counts once") {
        Held[0].EndPreAuth();
        Held[0].EndPreAuth();
        auto Moved = std::move(Held[1]);
        Moved.EndPreAuth();
        // two of the three pre-auth slots were freed, not more
        auto First = Limiter.TryAcquire("198.51.100.7");
        auto Second = Limiter.TryAcquire("198.51.100.7");
        auto Third = Limiter.TryAcquire("198.51.100.7");
        CHECK(First.has_value());
        CHECK(Second.has_value());
        CHECK_FALSE(Third.has_value());
    }
    SUBCASE("releasing a pre-auth guard frees its pre-auth slot and its total") {
        Held.pop_back();
        CHECK(Limiter.GetStats().CurrentGlobal == 2);
        auto Fresh = Limiter.TryAcquire("198.51.100.7");
        CHECK(Fresh.has_value());
        CHECK(Limiter.GetStats().CurrentGlobal == 3);
    }
}

TEST_CASE("TConnectionLimiter global pre-authentication quota") {
    TConnectionLimiter Limiter(10, 128, 3, 32);
    std::vector<TConnectionLimiter::TGuard> Held;
    for (int i = 0; i < 32; ++i) {
        auto Guard = Limiter.TryAcquire("198.51.100." + std::to_string(i));
        REQUIRE(Guard.has_value());
        Held.push_back(std::move(*Guard));
    }
    CHECK_FALSE(Limiter.TryAcquire("203.0.113.1").has_value());
    Held[0].EndPreAuth();
    CHECK(Limiter.TryAcquire("203.0.113.1").has_value());
}
