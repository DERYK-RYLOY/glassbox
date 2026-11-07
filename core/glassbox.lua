-- ============================================================================
-- Glassbox Core (pure Lua, zero dependencies)
-- Goal -> structured plan -> validate -> verify -> explain -> render
-- Also usable as a CLI bridge for the Python MCP server.
-- ============================================================================

local Glassbox = {}
Glassbox.VERSION = "0.1.0"

----------------------------------------------------------------------------
-- Minimal JSON codec (self-contained, no luarocks needed)
----------------------------------------------------------------------------
local JSON = {}

local function skip_ws(s, i)
  local _, j = s:find("^[%s]*", i)
  return (j or i - 1) + 1
end

local function decode_value(s, i)
  i = skip_ws(s, i)
  local c = s:sub(i, i)
  if c == '"' then
    local buf, j = {}, i + 1
    while true do
      local ch = s:sub(j, j)
      if ch == "" then error("unterminated string", 0) end
      if ch == '"' then return table.concat(buf), j + 1 end
      if ch == "\\" then
        local esc = s:sub(j + 1, j + 1)
        if esc == 'n' then buf[#buf+1] = '\n'; j = j + 2
        elseif esc == 't' then buf[#buf+1] = '\t'; j = j + 2
        elseif esc == 'r' then buf[#buf+1] = '\r'; j = j + 2
        elseif esc == 'u' then
          local hex = s:sub(j + 2, j + 5)
          buf[#buf+1] = utf8.char(tonumber(hex, 16)); j = j + 6
        else buf[#buf+1] = esc; j = j + 2 end
      else buf[#buf+1] = ch; j = j + 1 end
    end
  elseif c == '{' then
    local obj, j = {}, i + 1
    j = skip_ws(s, j)
    if s:sub(j, j) == '}' then return obj, j + 1 end
    while true do
      local key, nj = decode_value(s, j)
      j = skip_ws(s, nj)
      assert(s:sub(j, j) == ':', 'expected ":" in object')
      local val, vj = decode_value(s, j + 1)
      obj[key] = val
      j = skip_ws(s, vj)
      local sep = s:sub(j, j)
      if sep == ',' then j = j + 1
      elseif sep == '}' then return obj, j + 1
      else error('expected "," or "}" in object', 0) end
    end
  elseif c == '[' then
    local arr, j = {}, i + 1
    j = skip_ws(s, j)
    if s:sub(j, j) == ']' then return arr, j + 1 end
    while true do
      local val, vj = decode_value(s, j)
      arr[#arr+1] = val
      j = skip_ws(s, vj)
      local sep = s:sub(j, j)
      if sep == ',' then j = j + 1
      elseif sep == ']' then return arr, j + 1
      else error('expected "," or "]" in array', 0) end
    end
  elseif c == 't' and s:sub(i, i + 3) == 'true'  then return true, i + 4
  elseif c == 'f' and s:sub(i, i + 4) == 'false' then return false, i + 5
  elseif c == 'n' and s:sub(i, i + 3) == 'null'  then return nil, i + 4
  else
    local rest = s:sub(i)
    local numstr, nxt = rest:match('^(%-?%d+%.?%d*[eE]?[%+%-]?%d*)()')
    if numstr then return tonumber(numstr), i + nxt - 1 end
    error('unexpected token at position ' .. i, 0)
  end
end

function JSON.decode(s)
  local ok, val = pcall(function()
    local v, j = decode_value(s, 1)
    return v
  end)
  if not ok then return nil, val end
  return val
end

Glassbox.JSON = JSON

local function encode_value(v)
  local t = type(v)
  if t == 'nil' then return 'null'
  elseif t == 'boolean' or t == 'number' then return tostring(v)
  elseif t == 'string' then
    return '"' .. v:gsub('[%z\1-\31\\"]', function(c)
      if c == '\\' then return '\\\\'
      elseif c == '"' then return '\\"'
      elseif c == '\n' then return '\\n'
      elseif c == '\r' then return '\\r'
      elseif c == '\t' then return '\\t'
      else return string.format('\\u%04x', c:byte()) end
    end) .. '"'
  elseif t == 'table' then
    -- array if all integer keys 1..n, or completely empty (we emit [] for empty tables)
    local n, is_array = 0, true
    local empty = next(v) == nil
    for k in pairs(v) do
      if type(k) == 'number' and k == math.floor(k) and k >= 1 then n = n + 1 else is_array = false; break end
    end
    if is_array or empty then
      local parts = {}
      for i = 1, n do parts[#parts+1] = encode_value(v[i]) end
      return '[' .. table.concat(parts, ',') .. ']'
    else
      local parts = {}
      for k, val in pairs(v) do
        parts[#parts+1] = encode_value(tostring(k)) .. ':' .. encode_value(val)
      end
      return '{' .. table.concat(parts, ',') .. '}'
    end
  end
  return 'null'
end

function JSON.encode(v, pretty, indent)
  indent = indent or 0
  local pad = string.rep('  ', indent)
  local pad1 = string.rep('  ', indent + 1)
  local t = type(v)
  if not pretty or t ~= 'table' then return encode_value(v) end
  local is_array = (#v > 0) or (next(v) == nil)
  local parts = {}
  if is_array then
    for _, val in ipairs(v) do
      parts[#parts+1] = pad1 .. JSON.encode(val, pretty, indent + 1)
    end
    return '[\n' .. table.concat(parts, ',\n') .. '\n' .. pad .. ']'
  else
    for k, val in pairs(v) do
      parts[#parts+1] = pad1 .. string.format('%q', tostring(k)) .. ': ' .. JSON.encode(val, pretty, indent + 1)
    end
    return '{\n' .. table.concat(parts, ',\n') .. '\n' .. pad .. '}'
  end
end

----------------------------------------------------------------------------
-- Plan model
-- plan = {
--   title = "...", goal = "...", context = "...", constraints = {...},
--   assumptions = {"..."},
--   steps = { {id, action, rationale, verify, depends_on = {ids}, risk = "low|med|high"} },
--   risks = { {description, mitigation, severity} },
--   success_criteria = {"..."}
-- }
----------------------------------------------------------------------------

local function new_issue(severity, code, message, step_id)
  return { severity = severity, code = code, message = message, step_id = step_id }
end

local function index_steps(plan)
  local by_id = {}
  for _, s in ipairs(plan.steps or {}) do
    if s.id then by_id[tostring(s.id)] = s end
  end
  return by_id
end

function Glassbox.validate_plan(plan)
  local issues = {}
  if type(plan) ~= 'table' then
    return { new_issue('error', 'PLAN_NOT_TABLE', 'plan must be a JSON object') }
  end
  if not plan.title or plan.title == '' then
    issues[#issues+1] = new_issue('error', 'MISSING_TITLE', 'plan.title is required')
  end
  if not plan.goal or plan.goal == '' then
    issues[#issues+1] = new_issue('error', 'MISSING_GOAL', 'plan.goal is required')
  end
  if type(plan.steps) ~= 'table' or #plan.steps == 0 then
    issues[#issues+1] = new_issue('error', 'NO_STEPS', 'plan.steps must be a non-empty array')
    return issues
  end
  local by_id = index_steps(plan)
  local seen = {}
  for _, s in ipairs(plan.steps) do
    local sid = s.id and tostring(s.id) or '?'
    if not s.id then
      issues[#issues+1] = new_issue('error', 'STEP_NO_ID', 'every step needs an id')
    elseif seen[sid] then
      issues[#issues+1] = new_issue('error', 'DUPLICATE_STEP_ID', 'duplicate step id: ' .. sid, sid)
    else
      seen[sid] = true
    end
    if not s.action or s.action == '' then
      issues[#issues+1] = new_issue('error', 'STEP_NO_ACTION', 'step ' .. sid .. ' needs an action', sid)
    end
    if not s.rationale or s.rationale == '' then
      issues[#issues+1] = new_issue('warning', 'STEP_NO_RATIONALE', 'step ' .. sid .. ' has no rationale (the "why")', sid)
    end
    if not s.verify or s.verify == '' then
      issues[#issues+1] = new_issue('warning', 'STEP_NO_VERIFY', 'step ' .. sid .. ' has no verify/acceptance check', sid)
    end
    for _, dep in ipairs(s.depends_on or {}) do
      if not by_id[tostring(dep)] then
        issues[#issues+1] = new_issue('error', 'DANGLING_DEP', 'step ' .. sid .. ' depends on unknown step id: ' .. tostring(dep), sid)
      end
    end
  end
  if type(plan.success_criteria) ~= 'table' or #plan.success_criteria == 0 then
    issues[#issues+1] = new_issue('warning', 'NO_SUCCESS_CRITERIA', 'plan has no success_criteria — how will you know it worked?')
  end
  if type(plan.assumptions) ~= 'table' or #plan.assumptions == 0 then
    issues[#issues+1] = new_issue('info', 'NO_ASSUMPTIONS', 'no assumptions listed — plans fail on hidden assumptions')
  end
  return issues
end

-- Deeper checks: cycles, single points of failure, rollback coverage, risk coverage
function Glassbox.verify_plan(plan)
  local issues = Glassbox.validate_plan(plan)
  local by_id = index_steps(plan)
  local steps = plan.steps or {}

  -- Cycle detection (DFS)
  local WHITE, GRAY, BLACK = 0, 1, 2
  local color = {}
  for _, s in ipairs(steps) do color[tostring(s.id or '?')] = WHITE end
  local function dfs(u)
    color[u] = GRAY
    local s = by_id[u]
    for _, dep in ipairs((s and s.depends_on) or {}) do
      dep = tostring(dep)
      if color[dep] == GRAY then
        issues[#issues+1] = new_issue('error', 'DEPENDENCY_CYCLE', 'dependency cycle involving step: ' .. dep .. ' and step: ' .. u, u)
      elseif color[dep] == WHITE then
        dfs(dep)
      end
    end
    color[u] = BLACK
  end
  for _, s in ipairs(steps) do
    local u = tostring(s.id or '?')
    if color[u] == WHITE then dfs(u) end
  end

  -- Steps with high risk but no mitigation listed anywhere
  local has_rollback_like = false
  for _, s in ipairs(steps) do
    if (s.risk or ''):lower() == 'high' then
      issues[#issues+1] = new_issue('warning', 'HIGH_RISK_STEP', 'step ' .. tostring(s.id) .. ' is marked high risk — ensure it has a rollback/abort path', tostring(s.id))
    end
    local a = (s.action or ''):lower()
    if a:find('rollback') or a:find('revert') or a:find('backup') or a:find('restore') or a:find('snapshot') then
      has_rollback_like = true
    end
  end
  if #steps >= 4 and not has_rollback_like then
    issues[#issues+1] = new_issue('info', 'NO_ROLLBACK_STEP', 'no backup/rollback/restore step detected — consider one for multi-step plans')
  end

  -- Risk severity coverage
  local risk_sev = {}
  for _, r in ipairs(plan.risks or {}) do risk_sev[(r.severity or 'med'):lower()] = true end
  if #(plan.risks or {}) > 0 and not risk_sev['high'] then
    issues[#issues+1] = new_issue('info', 'NO_HIGH_RISK_IDENTIFIED', 'risks listed but none marked high — either nothing is truly high risk, or risks were under-rated')
  end

  -- Single point of failure: one step everything hangs off, no verify
  local dep_count = {}
  for _, s in ipairs(steps) do
    for _, dep in ipairs(s.depends_on or {}) do
      dep_count[tostring(dep)] = (dep_count[tostring(dep)] or 0) + 1
    end
  end
  for id, count in pairs(dep_count) do
    if count >= 3 then
      local s = by_id[id]
      if s and (not s.verify or s.verify == '') then
        issues[#issues+1] = new_issue('warning', 'SPOF_NO_VERIFY', 'step ' .. id .. ' is a dependency of ' .. count .. ' other steps but has no verification', id)
      end
    end
  end
  return issues
end

----------------------------------------------------------------------------
-- Rendering
----------------------------------------------------------------------------

local function cell(s, width)
  s = tostring(s or ''):gsub('\n', ' ')
  if #s > width then s = s:sub(1, width - 1) .. '…' end
  return s .. string.rep(' ', width - #s)
end

function Glassbox.render_table(plan)
  local steps = plan.steps or {}
  local id_w, act_w, rat_w, ver_w = 4, 44, 36, 30
  local sep = '+' .. string.rep('-', id_w + 2) .. '+' .. string.rep('-', act_w + 2) .. '+'
            .. string.rep('-', rat_w + 2) .. '+' .. string.rep('-', ver_w + 2) .. '+'
  local lines = { sep,
    '| ' .. cell('ID', id_w) .. ' | ' .. cell('Action', act_w) .. ' | '
            .. cell('Rationale', rat_w) .. ' | ' .. cell('Verify', ver_w) .. ' |', sep }
  for _, s in ipairs(steps) do
    lines[#lines+1] = '| ' .. cell(s.id, id_w) .. ' | ' .. cell(s.action, act_w) .. ' | '
                    .. cell(s.rationale, rat_w) .. ' | ' .. cell(s.verify, ver_w) .. ' |'
    lines[#lines+1] = sep
  end
  return table.concat(lines, '\n')
end

local function mermaid_id(id)
  return 'n' .. tostring(id):gsub('[^%w_]', '_')
end

function Glassbox.render_mermaid(plan)
  local lines = { 'flowchart TD' }
  for _, s in ipairs(plan.steps or {}) do
    local label = tostring(s.action or ''):gsub('["%[%]|]', ' ')
    if #label > 48 then label = label:sub(1, 47) .. '…' end
    lines[#lines+1] = string.format('  %s["%s"]', mermaid_id(s.id), label)
  end
  for _, s in ipairs(plan.steps or {}) do
    for _, dep in ipairs(s.depends_on or {}) do
      lines[#lines+1] = string.format('  %s --> %s', mermaid_id(dep), mermaid_id(s.id))
    end
  end
  return table.concat(lines, '\n')
end

----------------------------------------------------------------------------
-- Plain-language explanation with receipts
----------------------------------------------------------------------------
function Glassbox.explain_plan(plan)
  local L = {}
  L[#L+1] = 'GLASSBOX PLAIN-LANGUAGE EXPLANATION'
  L[#L+1] = '===================================='
  L[#L+1] = ''
  L[#L+1] = 'WHAT THIS DOES (the 10-second version)'
  L[#L+1] = '  ' .. tostring(plan.goal or plan.title or 'No goal recorded — that is itself a finding.')
  if plan.context and plan.context ~= '' then
    L[#L+1] = ''
    L[#L+1] = 'THE SITUATION'
    L[#L+1] = '  ' .. tostring(plan.context)
  end
  L[#L+1] = ''
  L[#L+1] = 'HOW IT WILL GO, STEP BY STEP'
  for i, s in ipairs(plan.steps or {}) do
    L[#L+1] = string.format('  %d. Step %s — %s', i, tostring(s.id), tostring(s.action))
    if s.rationale and s.rationale ~= '' then
      L[#L+1] = '     Why: ' .. tostring(s.rationale)
    end
    if s.verify and s.verify ~= '' then
      L[#L+1] = '     How we know it worked: ' .. tostring(s.verify)
    end
  end
  if plan.risks and #plan.risks > 0 then
    L[#L+1] = ''
    L[#L+1] = 'WHAT COULD GO WRONG (and the countermeasure)'
    for _, r in ipairs(plan.risks) do
      L[#L+1] = string.format('  - [%s] %s', tostring(r.severity or 'med'):upper(), tostring(r.description or r[1] or 'unspecified risk'))
      if r.mitigation then L[#L+1] = '     Countermeasure: ' .. tostring(r.mitigation) end
    end
  end
  if plan.assumptions and #plan.assumptions > 0 then
    L[#L+1] = ''
    L[#L+1] = 'THE RECEIPTS (assumptions — if any of these is wrong, the plan changes)'
    for i, a in ipairs(plan.assumptions) do
      L[#L+1] = string.format('  %d. %s', i, tostring(a))
    end
  end
  if plan.success_criteria and #plan.success_criteria > 0 then
    L[#L+1] = ''
    L[#L+1] = 'HOW YOU WILL KNOW IT WORKED (definition of done)'
    for i, c in ipairs(plan.success_criteria) do
      L[#L+1] = string.format('  %d. %s', i, tostring(c))
    end
  end
  return table.concat(L, '\n')
end

-- Scored trust report: how much should a human trust this plan?
function Glassbox.trust_report(plan)
  local issues = Glassbox.verify_plan(plan)
  local score = 100
  local counts = { error = 0, warning = 0, info = 0 }
  for _, i in ipairs(issues) do
    counts[i.severity] = (counts[i.severity] or 0) + 1
    if i.severity == 'error' then score = score - 25
    elseif i.severity == 'warning' then score = score - 8
    else score = score - 2 end
  end
  if score < 0 then score = 0 end
  local verdict
  if score >= 85 then verdict = 'SOLID — safe to execute with normal review'
  elseif score >= 60 then verdict = 'WORKABLE — fix the warnings before executing'
  elseif score >= 30 then verdict = 'FRAGILE — redesign before executing'
  else verdict = 'DO NOT EXECUTE — plan has structural errors' end
  return {
    score = score,
    verdict = verdict,
    counts = counts,
    issues = issues,
  }
end

----------------------------------------------------------------------------
-- Plan skeleton factory (what the host AI fills in)
----------------------------------------------------------------------------
function Glassbox.plan_skeleton(goal, context, constraints)
  return {
    title = '',
    goal = goal or '',
    context = context or '',
    constraints = constraints or {},
    assumptions = {},
    steps = {},
    risks = {},
    success_criteria = {},
    _glassbox_instructions = {
      'Fill this plan completely and honestly.',
      'Every step MUST have: id, action, rationale (why this step), verify (how we know it worked), risk (low|med|high).',
      'List depends_on ids for ordering. List assumptions explicitly — plans die from hidden assumptions.',
      'Add risks with severity and mitigation. Add success_criteria.',
      'Then call glassbox_verify_plan on the result before showing it to the user.',
    }
  }
end

----------------------------------------------------------------------------
-- CLI bridge:  lua glassbox.lua <command> [args...] < planfile
----------------------------------------------------------------------------
local function read_all_stdin()
  return io.read('*a')
end

local function die(msg)
  io.stderr:write('glassbox: ' .. tostring(msg) .. '\n')
  os.exit(2)
end

if arg and arg[0] and arg[0]:match('glassbox%.lua$') then
  local cmd = arg[1]
  local input = read_all_stdin()
  local plan, decode_err = JSON.decode(input or '')
  if cmd == 'skeleton' then
    -- skeleton mode takes raw args, not JSON
    local skel = Glassbox.plan_skeleton(arg[2], arg[3], { arg[4] })
    print(JSON.encode(skel, true))
  else
    if not plan then die('invalid plan JSON on stdin: ' .. tostring(decode_err)) end
    if cmd == 'validate' then
      print(JSON.encode({ issues = Glassbox.validate_plan(plan) }, true))
    elseif cmd == 'verify' then
      print(JSON.encode({ issues = Glassbox.verify_plan(plan) }, true))
    elseif cmd == 'trust' then
      print(JSON.encode(Glassbox.trust_report(plan), true))
    elseif cmd == 'table' then
      print(Glassbox.render_table(plan))
    elseif cmd == 'mermaid' then
      print(Glassbox.render_mermaid(plan))
    elseif cmd == 'explain' then
      print(Glassbox.explain_plan(plan))
    else
      die('unknown command: ' .. tostring(cmd))
    end
  end
end

return Glassbox
