-- MR Server, a BeamMP-Server fork for Muertazos Racing.
-- Copyright (C) 2026 Muertazos Racing
-- Licensed under AGPL-3.0-or-later, see the LICENSE file.
--
-- Plugin SOLO PARA CI (test/mr/test_transport.py y test_handshake.py): el workflow lo copia a
-- Resources/Server/MrCiTransport/. No forma parte del binario ni de ninguna entrega.

function MrCiOnTransport(pid, kind)
    print("MRCI transport name=" .. MP.GetPlayerName(pid) .. " kind=" .. kind)
    -- eventos fiables hacia el cliente, en orden
    MP.TriggerClientEvent(pid, "mrci1", "a")
    MP.TriggerClientEvent(pid, "mrci2", "b")
    MP.TriggerClientEvent(pid, "mrci3", "c")
end

function MrCiEcho(pid, data)
    MP.TriggerClientEvent(pid, "mrciPong", data)
end

function MrCiIsConnected(pid, data)
    MP.TriggerClientEvent(pid, "mrciConn", tostring(MP.IsPlayerConnected(pid)))
end

-- Retiene la autenticacion de los nombres "PilotoLento*" 2 s (test_handshake.py: entradas simultaneas)
function MrCiOnPlayerAuth(name)
    if string.sub(name, 1, 11) == "PilotoLento" then
        MP.Sleep(2000)
    end
end

function onInit()
    MP.RegisterEvent("onPlayerAuth", "MrCiOnPlayerAuth")
    MP.RegisterEvent("onPlayerTransport", "MrCiOnTransport")
    MP.RegisterEvent("mrciEcho", "MrCiEcho")
    MP.RegisterEvent("mrciIsConn", "MrCiIsConnected")
end
