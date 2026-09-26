-- eu_poster.lua — wireless EU -> gtnh-eu-dash. EU ONLY.
-- Runs standalone on any OC computer with an Internet Card + Adapter
-- facing the LSC controller. No NIDAS dependency; can share the machine.
--
-- Install on the OC computer:
--   wget <pastebin-or-url-of-this-file> eu_poster.lua   (or edit + paste)
--   edit eu_poster.lua   -- set URL + TOKEN below, then save
--   eu_poster            -- runs forever until Ctrl+C

local URL = "https://energy.example.com/ingest"  -- CHANGE: your dashboard URL
local TOKEN = "PASTE-TOKEN-HERE"                  -- CHANGE: must match server TOKEN
local INTERVAL = 10                               -- seconds between posts
-- If this computer sees more than one gt_* component (e.g. NIDAS shares it),
-- set ADDRESS to the LSC adapter's component address (find via component.list()).
local ADDRESS = nil

local component = require("component")
local internet = require("internet")

local lsc
if ADDRESS then
  lsc = component.proxy(ADDRESS)
else
  lsc = component.gt_machine
end
assert(lsc, "no gt_machine component found: is the Adapter touching the LSC controller?")

while true do
  local ok, err = pcall(function()
    local info = lsc.getSensorInformation()
    assert(type(info) == "table" and #info > 20,
      "sensorInformation has " .. tostring(#(info or {})) .. " lines, expected 20+ (is this the LSC controller?)")
    -- wirelessEU lives at index 23 on 2.9 builds; keep as RAW DIGITS:
    -- Lua doubles lose precision past 2^53, so never tonumber() it.
    local raw = tostring(info[23] or "")
    local digits = raw:gsub("[^0-9]", "")
    assert(#digits > 0, "no digits at sensorInformation[23], got: " .. raw)
    local body = string.format('{"wireless_eu":"%s"}', digits)
    internet.request(URL, body,
      { ["Content-Type"] = "application/json", ["Authorization"] = "Bearer " .. TOKEN },
      "POST")()
  end)
  if not ok then print("post failed: " .. tostring(err)) end
  os.sleep(INTERVAL)
end
