-- ============================================================================
-- Iron Swarm v2 - recursive 10-agent reasoning engine (pure Lua + Python transport)
--
-- Architecture (per pass):
--   3 SCOUTS   | gather: facts / prior-art / failure-modes
--   5 ANALYSTS | dissect: correctness / security / performance / maintainability / risk-cost
--   1 ARCHITECT   design: one unified GB1 STEP plan
--   1 VERIFIER    audit: GB-flavored verdict -- GV|PASS|... or GV|REVISE|...
--
-- The loop is the product: if the verifier says REVISE, its findings are fed
-- BACK into the architect for another pass. Bounded by max_passes. Converges
-- or exhausts budget -- and reports which, with receipts.
--
-- Agents are real LLM calls via python/llm_bridge.py (concurrent,
-- OpenAI-compatible endpoints). This file owns everything else: prompts,
-- GB1 codec, loop, convergence detection, plan synthesis, trust scoring.
--
-- GB1 wire format:
--   GB1/1            frame header          GV|PASS|<reason>   verifier verdict
--   FACT|<0-100>|<statement>               RISK|<l|m|h>|<desc>|<mitigation>
--   STEP|<id>|<action>|<rationale>|<verify>|<risk l|m|h>|<deps csv>
--   END              frame trailer
-- ============================================================================

local IS = { VERSION = "2.0.0", AGENT_COUNT = 10 }

local script_path = arg and arg[0] or "iron_swarm.lua"
local core_dir = script_path:match("^(.*)[/\\]") or "."
local Glassbox = dofile(core_dir .. "/glassbox.lua")
local JSON = Glassbox.JSON

----------------------------------------------------------------------------
-- Agent definitions (exactly 10)
----------------------------------------------------------------------------

local ROLES = {
  { key = "scout-facts", phase = "scout", system =
      "You are SCOUT-FACTS. Gather verifiable facts, constraints and APIs relevant to the task. " ..
      "Do not opine. Reply ONLY in GB1: FACT lines with confidence 0-100." },
  { key = "scout-prior-art", phase = "scout", system =
      "You are SCOUT-PRIOR-ART. Find existing solutions, libraries, patterns and precedents. " ..
      "Reply ONLY in GB1: FACT lines, confidence 0-100, naming concrete tools and approaches." },
  { key = "scout-failure-modes", phase = "scout", system =
      "You are SCOUT-FAILURE-MODES. Enumerate how solutions to this task typically fail in production. " ..
      "Reply ONLY in GB1: RISK lines, severity l|m|h, one mitigation each." },
  { key = "analyst-correctness", phase = "analyst", system =
      "You are ANALYST-CORRECTNESS. Judge the findings for technical correctness and internal " ..
      "consistency. Output GB1: FACT lines for confirmed correct points; RISK lines for flaws." },
  { key = "analyst-security", phase = "analyst", system =
      "You are ANALYST-SECURITY. Audit for auth, injection, secrets, supply-chain and data-exposure " ..
      "holes. Output GB1: RISK lines with severity and mitigation. If clean, one FACT|90|no critical issues." },
  { key = "analyst-performance", phase = "analyst", system =
      "You are ANALYST-PERFORMANCE. Audit for scale, latency, resource and hot-path issues. " ..
      "Output GB1: RISK lines for flaws, FACT lines for viable performance patterns." },
  { key = "analyst-maintainability", phase = "analyst", system =
      "You are ANALYST-MAINTAINABILITY. Audit for complexity, testability, operability and handoff " ..
      "cost. Output GB1: RISK lines with concrete simplifications." },
  { key = "analyst-risk-cost", phase = "analyst", system =
      "You are ANALYST-RISK-COST. Audit schedule, dependencies, cost and blast radius. " ..
      "Output GB1: RISK lines with severity. Explicitly rank the top 3 biggest risks." },
  { key = "architect", phase = "architect", system =
      "You are the ARCHITECT. Design the solution to the task from the findings and analysis. " ..
      "If REVISION FEEDBACK is present, you MUST address every point in it. " ..
      "Reply ONLY in GB1: STEP lines with id/action/rationale/verify/risk(l|m|h)/deps(csv). " ..
      "Every step needs rationale and a concrete verification." },
  { key = "verifier", phase = "verifier", system =
      "You are the VERIFIER. Audit the architect's STEP plan against the analysis with total rigor. " ..
      "Output EXACTLY ONE verdict line: GV|PASS|<one-line reason>  -- or --  GV|REVISE|<one-line reason>. " ..
      "If REVISE, follow with RISK lines (l|m|h) describing exactly what must change and how. " ..
      "PASS only if the plan is genuinely executable, verified, and addresses the top risks." },
}

local PHASE_SCOUT, PHASE_ANALYST = "scout", "analyst"

----------------------------------------------------------------------------
-- GB1 codec
----------------------------------------------------------------------------

local function split_pipe(line)
  local parts = {}
  for field in line:gmatch("([^|]*)") do parts[#parts + 1] = field end
  return parts
end

function IS.parse_gb1(text)
  local records = {}
  for raw in (text or ""):gmatch("[^\n]+") do
    local line = raw:gsub("^%s+", ""):gsub("%s+$", "")
    if line ~= "" and line ~= "GB1/1" and line ~= "END" then
      local f = split_pipe(line)
      local kind = f[1]
      if kind == "FACT" then
        records[#records + 1] = { kind = "FACT", confidence = tonumber(f[2]) or 0, statement = f[3] or "" }
      elseif kind == "RISK" then
        records[#records + 1] = { kind = "RISK", severity = f[2] or "m", description = f[3] or "", mitigation = f[4] or "" }
      elseif kind == "STEP" then
        records[#records + 1] = { kind = "STEP", id = f[2], action = f[3], rationale = f[4],
                                  verify = f[5], risk = f[6] or "med", deps = f[7] or "" }
      elseif kind == "GV" then
        records[#records + 1] = { kind = "GV", verdict = (f[2] or ""):upper(), reason = f[3] or "" }
      end
    end
  end
  return records
end

local function gb1_frame(task_id, verb, payload)
  return string.format("GB1/1\nTASK|%s|%s|%s\nEND", task_id, verb, payload)
end

local function merge_findings(outputs)
  local blocks = {}
  for role, out in pairs(outputs) do
    blocks[#blocks + 1] = string.format("# %s\n%s", role, out)
  end
  table.sort(blocks)
  return table.concat(blocks, "\n\n")
end

----------------------------------------------------------------------------
-- Bridge: concurrent LLM calls via python/llm_bridge.py
----------------------------------------------------------------------------

local function bridge_path()
  return core_dir .. "/../python/llm_bridge.py"
end

local function thinker_gate_path()
  return core_dir .. "/../python/thinker_gate.py"
end

local function _temp_file(suffix)
  local tmp = os.getenv("TEMP") or os.getenv("TMP") or "."
  local name = string.format("%s/glassbox_%d_%s_%s.json", tmp, os.time(), tostring(math.random(1, 1e9)), suffix)
  return name
end

-- Call the Tiny Thinker gate (python subprocess). Fail-open: returns nil on any error.
local function call_thinker(task, items, threshold)
  math.randomseed(os.time() + os.clock() * 1000)
  local req_file, res_file = _temp_file("treq"), _temp_file("tres")
  local fh = io.open(req_file, "w")
  if not fh then return nil end
  fh:write(JSON.encode({ task = task, items = items, keep_threshold = threshold or 0.30 }))
  fh:close()
  local py = os.getenv("GLASSBOX_PYTHON") or "python"
  local ok = os.execute(string.format('%s "%s" < "%s" > "%s"', py, thinker_gate_path(), req_file, res_file))
  os.remove(req_file)
  if not ok then
    os.remove(res_file)
    return nil
  end
  local rfh = io.open(res_file, "r")
  local raw = rfh and rfh:read("*a") or nil
  if rfh then rfh:close() end
  os.remove(res_file)
  if not raw then return nil end
  local data = JSON.decode(raw)
  return data
end

local function gb1_content_lines(outputs)
  local items, meta = {}, {}
  for role, out in pairs(outputs) do
    for raw in (out or ""):gmatch("[^\n]+") do
      local line = raw:gsub("^%s+", ""):gsub("%s+$", "")
      if line:match("^FACT|") or line:match("^RISK|") then
        items[#items + 1] = line
        meta[#meta + 1] = role
      end
    end
  end
  return items, meta
end

local function call_agents(requests)
  -- requests: { {role, system, user, max_tokens?}, ... } - sent concurrently
  math.randomseed(os.time() + os.clock() * 1000)
  local req_file, res_file = _temp_file("req"), _temp_file("res")

  local fh = assert(io.open(req_file, "w"))
  fh:write(JSON.encode({ agents = requests }))
  fh:close()

  local py = os.getenv("GLASSBOX_PYTHON") or "python"
  local ok, why = os.execute(string.format('%s "%s" < "%s" > "%s"', py, bridge_path(), req_file, res_file))
  os.remove(req_file)
  if not ok then
    os.remove(res_file)
    error("llm_bridge failed: " .. tostring(why), 0)
  end

  local rfh = assert(io.open(res_file, "r"))
  local raw = rfh:read("*a")
  rfh:close()
  os.remove(res_file)

  local data, err = JSON.decode(raw)
  if not data then error("llm_bridge returned invalid JSON: " .. tostring(err), 0) end
  return data.results or {}, data
end

----------------------------------------------------------------------------
-- One pass
----------------------------------------------------------------------------

local function role_index()
  local by_key = {}
  for _, r in ipairs(ROLES) do by_key[r.key] = r end
  return by_key
end

local PHASES = { PHASE_SCOUT, "analyst", "architect", "verifier" }

local function agents_in_phase(phase)
  local out = {}
  for _, r in ipairs(ROLES) do
    if r.phase == phase then out[#out + 1] = r end
  end
  return out
end

local function run_pass(state, pass_no)
  local brief = string.format("TASK %s: %s\nCONTEXT: %s", state.task_id, state.task, state.context)

  -- Phase 1: scouts (3 agents, one concurrent bridge call)
  local findings = {}
  local requests = {}
  for _, r in ipairs(agents_in_phase(PHASE_SCOUT)) do
    requests[#requests + 1] = { role = r.key, system = r.system,
                                user = gb1_frame(state.task_id, "GATHER", brief), max_tokens = 700 }
  end
  local scout_out, meta = call_agents(requests)
  for role, out in pairs(scout_out) do findings[role] = out end

  -- Tiny Thinker gate: drop noise GB1 lines before analysts spend tokens on them
  local thinker_stats = nil
  if state.use_thinker then
    local items, owners = gb1_content_lines(findings)
    if #items > 0 then
      local gate = call_thinker(state.task, items, state.thinker_threshold)
      if gate and gate.kept_indices then
        local kept = {}
        local by_role = {}
        for _, idx in ipairs(gate.kept_indices) do
          local line = items[idx + 1]  -- Lua arrays are 1-based; json is 0-based
          local role = owners[idx + 1]
          if line and role then
            by_role[role] = by_role[role] or {}
            by_role[role][#by_role[role] + 1] = line
          end
        end
        local rebuilt = {}
        for role, lines in pairs(by_role) do
          rebuilt[role] = table.concat(lines, "\n")
        end
        if next(rebuilt) ~= nil then
          findings = rebuilt
          thinker_stats = gate.stats
        end
      else
        thinker_stats = { note = "thinker gate unavailable - findings unfiltered (fail-open)" }
      end
    end
  end
  local merged_findings = merge_findings(findings)

  -- Phase 2: analysts (5 agents, one concurrent bridge call)
  requests = {}
  local analyst_user = gb1_frame(state.task_id, "ANALYZE",
    brief .. "\nFINDINGS:\n" .. merged_findings)
  for _, r in ipairs(agents_in_phase("analyst")) do
    requests[#requests + 1] = { role = r.key, system = r.system,
                                user = analyst_user, max_tokens = 800 }
  end
  local analyst_out = call_agents(requests)
  local merged_analysis = merge_findings(analyst_out)

  -- Phase 3: architect - with verifier feedback from previous passes
  local architect_user = brief .. "\nANALYSIS:\n" .. merged_analysis
  if state.feedback and state.feedback ~= "" then
    architect_user = architect_user .. "\nREVISION FEEDBACK (you MUST address every item):\n" .. state.feedback
  end
  local architect_role = role_index()["architect"]
  local arch_out, _ = call_agents({ { role = "architect", system = architect_role.system,
                                      user = gb1_frame(state.task_id, "DESIGN", architect_user),
                                      max_tokens = 1500 } })
  local artifact = arch_out.architect or "GB1/1\nEND"

  -- Phase 4: verifier - the convergence gate
  local verifier_role = role_index()["verifier"]
  local ver_out = call_agents({ { role = "verifier", system = verifier_role.system,
                                  user = gb1_frame(state.task_id, "VERIFY",
                                    brief .. "\nANALYSIS:\n" .. merged_analysis ..
                                    "\nPLAN UNDER AUDIT:\n" .. artifact),
                                  max_tokens = 900 } })
  local verdict_raw = ver_out.verifier or ""
  local records = IS.parse_gb1(verdict_raw)

  local verdict, reason, feedback_lines = "REVISE", "verifier unparseable - treating as REVISE", {}
  for _, rec in ipairs(records) do
    if rec.kind == "GV" then verdict, reason = rec.verdict or "REVISE", rec.reason or "" end
    if rec.kind == "RISK" then
      feedback_lines[#feedback_lines + 1] = string.format("- [%s] %s (fix: %s)", rec.severity, rec.description, rec.mitigation)
    end
  end
  if #feedback_lines == 0 and verdict == "REVISE" then
    feedback_lines[#feedback_lines + 1] = "- [m] " .. reason .. " (fix: tighten the plan, add verifications and rollback)"
  end

  state.history[#state.history + 1] = {
    pass = pass_no,
    verdict = verdict,
    reason = reason,
    scouts = findings,
    analysts = analyst_out,
    artifact = artifact,
    verifier = verdict_raw,
    thinker = thinker_stats,
  }
  state.agents_run = state.agents_run + 3 + 5 + 1 + 1
  state.feedback = table.concat(feedback_lines, "\n")
  state.artifact = artifact
  state.analysis = merged_analysis
  state.findings = merged_findings
  state.final_verdict = verdict

  return verdict
end

----------------------------------------------------------------------------
-- STEP lines -> Glassbox plan schema -> trust report
----------------------------------------------------------------------------

local function severity_to_risk(s)
  local m = { l = "low", m = "medium", h = "high" }
  return m[s] or "medium"
end

local function artifact_to_plan(state)
  local plan = {
    title = ("Iron Swarm design: " .. (state.task:sub(1, 80))),
    goal = state.task,
    context = state.context,
    assumptions = {},
    steps = {},
    risks = {},
    success_criteria = {},
  }
  for _, rec in ipairs(IS.parse_gb1(state.artifact)) do
    if rec.kind == "STEP" then
      local deps = {}
      for dep in (rec.deps or ""):gmatch("[^,%s]+") do deps[#deps + 1] = dep:match("%S+") end
      plan.steps[#plan.steps + 1] = {
        id = tostring(rec.id), action = rec.action, rationale = rec.rationale,
        verify = rec.verify, risk = severity_to_risk(rec.risk), depends_on = deps,
      }
    elseif rec.kind == "RISK" then
      plan.risks[#plan.risks + 1] = { description = rec.description,
                                      mitigation = rec.mitigation,
                                      severity = severity_to_risk(rec.severity) }
    end
  end
  for _, rec in ipairs(IS.parse_gb1(state.analysis)) do
    if rec.kind == "RISK" then
      plan.risks[#plan.risks + 1] = { description = rec.description,
                                      mitigation = rec.mitigation,
                                      severity = severity_to_risk(rec.severity) }
    end
  end
  if #plan.steps > 0 then
    plan.success_criteria = { "all steps' verify lines pass", "top risks mitigated per plan" }
  end
  return plan
end

----------------------------------------------------------------------------
-- Public API: recursive run
----------------------------------------------------------------------------

function IS.run(opts)
  local state = {
    task = assert(opts.task, "opts.task required"),
    context = opts.context or "",
    task_id = "T" .. tostring(math.floor(os.time())):sub(-6),
    history = {}, feedback = nil, agents_run = 0,
  }
  local max_passes = tonumber(opts.max_passes) or 3
  state.use_thinker = opts.use_thinker and true or false
  state.thinker_threshold = tonumber(opts.thinker_threshold) or 0.60
  local started = os.clock()

  local converged, passes = false, 0
  for pass = 1, max_passes do
    passes = pass
    local verdict = run_pass(state, pass)
    if verdict == "PASS" then converged = true break end
  end

  local plan = artifact_to_plan(state)
  local trust = plan.steps and #plan.steps > 0 and Glassbox.trust_report(plan) or nil

  return {
    mode = "iron-swarm-v2",
    task = state.task,
    task_id = state.task_id,
    converged = converged,
    passes = passes,
    max_passes = max_passes,
    agents_run = state.agents_run,
    agent_definition = "3 scouts + 5 analysts + architect + verifier, repeated until PASS or budget",
    elapsed_s = math.floor((os.clock() - started) * 10) / 10,
    final_verdict = state.final_verdict,
    final_artifact = state.artifact,
    synthesized_plan = plan,
    trust_report = trust,
    pass_history = (function()
      local h = {}
      for _, p in ipairs(state.history) do
        h[#h + 1] = { pass = p.pass, verdict = p.verdict, reason = p.reason }
      end
      return h
    end)(),
    receipts = state.history,
    honesty = "Produced by Iron Swarm v2 (10 agents per pass, recursive). Receipts per pass are included.",
  }
end

----------------------------------------------------------------------------
-- CLI: echo '{"task":..., "context":..., "max_passes":3}' | lua iron_swarm.lua run
----------------------------------------------------------------------------

if arg and arg[1] == "run" then
  local raw = io.read("*a")
  local opts, err = JSON.decode(raw or "")
  if not opts then
    io.stderr:write("iron_swarm: invalid JSON input: " .. tostring(err) .. "\n")
    os.exit(2)
  end
  local ok, result = pcall(IS.run, opts)
  if not ok then
    io.stderr:write("iron_swarm: " .. tostring(result) .. "\n")
    os.exit(1)
  end
  print(JSON.encode(result, true))
end

return IS
