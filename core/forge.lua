-- ============================================================================
-- The Forge — combinatorial creativity engine (pure Lua)
--
-- Generates NOVEL idea scaffolds by forcing collisions the LLM's next-token
-- distribution would never propose on its own. The LLM instantiates the ideas;
-- this engine exists to make it REACH further than it otherwise would.
--
-- Operator families (all traceable: idea -> operator -> parents -> scores):
--   BLEND    Koestler bisociation / conceptual blending: field A x field B applied to task
--   SCAMPER  7 mutations of the task's core action
--   NEGATE   invert the task's hidden load-bearing assumption
--   ALT      abstraction ladder: zoom out 3 altitudes, zoom in 1
--   FOCUS    constraint subtraction: delete the hardest constraint, redesign
--
-- Output: JSON dossier of IDEA records or raw GB1. Deterministic given a seed.
-- ============================================================================

local Forge = { VERSION = "1.0.0" }

local script_path = arg and arg[0] or "forge.lua"
local core_dir = script_path:match("^(.*)[/\\]") or "."
local Glassbox = dofile(core_dir .. "/glassbox.lua")
local JSON = Glassbox.JSON

----------------------------------------------------------------------------
-- Concept domains (broad, divergent, embedded) — the blend parents
----------------------------------------------------------------------------
local DOMAINS = {
  "evolutionary biology", "jazz improvisation", "mycology", "ant colony foraging",
  "immunology", "fermentation", "origami", "fluid dynamics", "game theory", "mythology",
  "cathedral architecture", "submarine design",
  "bee dance communication", "tides and lunar cycles", "coral reef ecology",
  "fermenting kimchi", "aviation turbulence handling", "mycorrhizal trade networks",
  "tide pools", "honeycomb lattices", "avalanche dynamics", "moss succession",
  "murmuration of starlings", "hydrothermal vents", "Zen gardens", "brood parasitism",
  "fungal decomposition", "lighthouse signaling", "songline cartography", "glacial erosion",
  "feral street networks", "octopus cognition", "lichen symbiosis", "tradewinds",
  "seed dormancy", "chromatophores", "midden archaeology", "drought adaptation",
  "volcanic soil", "bird migration", "estuarine gradients", "spiral galaxy arms",
  "karst cave systems", "bamboo rapid growth", "tide estuaries", "mangrove roots",
  "photosynthesis", "ice sheet acoustics", "desert blooms", "antimatter containment",
  "bee waggle dances", "estuary silting", "storm chasing",
}

local SCAMPER = {
  { op = "SUBSTITUTE",  q = "Replace the core mechanism of the task with an equivalent from a hostile or alien context" },
  { op = "COMBINE",     q = "Fuse the task with the nearest adjacent craft of an expert you never hire" },
  { op = "ADAPT",       q = "Transplant a solution proven in a completely different scale or century" },
  { op = "MODIFY",      q = "Exaggerate one parameter 10x and miniaturize another to 1/10th" },
  { op = "PUT-TO-USE",  q = "Reassign the task's output to a user who was never considered" },
  { op = "ELIMINATE",   q = "Remove the most sacred component; solve the remainder with what stays" },
  { op = "REVERSE",     q = "Invert the direction of flow: output becomes input, failure becomes feature" },
}

local function rng_factory(seed)
  local s = seed % 2147483647
  if s <= 0 then s = s + 2147483646 end
  return function(n)
    s = (s * 48271) % 2147483647
    return (s % n) + 1
  end
end

local function pick(rand, t)
  return t[rand(#t)]
end

local function idea(id, op, parents, spark, seed_rationale)
  return { id = id, operator = op, parents = parents, spark = spark, seed_rationale = seed_rationale }
end

----------------------------------------------------------------------------
-- Candidate generation (deterministic given seed)
----------------------------------------------------------------------------

function Forge.generate(task, opts)
  opts = opts or {}
  local rand = rng_factory(tonumber(opts.seed) or tonumber(tostring(os.time()):sub(-9)))
  local per_family = tonumber(opts.per_family) or 3
  local ideas, id = {}, 0
  local task_l = (task or ""):gsub("^%s+", ""):gsub("%s+$", "")

  -- BLEND: far-field collisions
  local used = {}
  for _ = 1, per_family do
    local a, b = pick(rand, DOMAINS), pick(rand, DOMAINS)
    local guard = 0
    while a == b and guard < 10 do b = pick(rand, DOMAINS); guard = guard + 1 end
    local key = a .. "|" .. b
    if not used[key] then
      used[key] = true
      id = id + 1
      ideas[#ideas + 1] = idea(id, "BLEND", { a, b },
        string.format("Apply %s × %s to: %s", a, b, task_l),
        "Koestler bisociation: force-fit two matrices that share no shelf")
    end
  end

  -- SCAMPER: orthogonal mutations of the task itself
  for _, s in ipairs(SCAMPER) do
    id = id + 1
    ideas[#ideas + 1] = idea(id, "SCAMPER/" .. s.op, { task_l },
      string.format("%s — for: %s", s.q, task_l), "SCAMPER: systematic mutation, not vibes")
  end

  -- NEGATE: invert the load-bearing assumption
  id = id + 1
  ideas[#ideas + 1] = idea(id, "NEGATE", { task_l },
    string.format("Assume the OPPOSITE of the most obvious constraint inside: %s — then design as if it were law", task_l),
    "Negation: the trap-door under the safest assumption")

  -- ALT: abstraction ladder up 3, down 1
  id = id + 1
  ideas[#ideas + 1] = idea(id, "ALT-ZOOM-OUT", { task_l },
    string.format("Zoom out 3 levels from '%s': what if this is a symptom of a civilizational pattern, not an engineering problem?", task_l),
    "Ladder of abstraction: flee the solution space, find a bigger one")
  id = id + 1
  ideas[#ideas + 1] = idea(id, "ALT-ZOOM-IN", { task_l },
    string.format("Zoom in 3 levels into '%s': what is the atomic unit nobody has modeled?", task_l),
    "Ladder of abstraction: find the invisible primitive")

  -- FOCUS: constraint subtraction
  id = id + 1
  ideas[#ideas + 1] = idea(id, "FOCUS-SUBTRACT", { task_l },
    string.format("Delete the hardest, scariest constraint from '%s'. Redesign freely. Reintroduce it only at the end", task_l),
    "Constraint subtraction: the wall you're designing around may be imaginary")

  return ideas
end

----------------------------------------------------------------------------
-- Output
----------------------------------------------------------------------------

function Forge.dossier(task, opts)
  opts = opts or {}
  local ideas = Forge.generate(task, opts)
  return {
    task = task,
    seed = opts.seed,
    idea_count = #ideas,
    ideas = ideas,
    protocol = {
      "For each idea: instantiate it in 2-4 sentences (mechanism, not metaphor).",
      "Pre-mortem each: what does it break FIRST?",
      "Cross-pollinate the top 2 by the Thinker's coherence ranking; hybridize survivors.",
      "Discard nothing without a written reason — killed ideas are data.",
    },
    honesty = "These are operator-generated scaffolds (bisociation/SCAMPER/negation/altitude), " ..
              "not finished ideas. The LLM must instantiate each. The Thinker gate ranks coherence; " ..
              "it cannot guarantee novelty or correctness.",
  }
end

if arg and arg[1] == "run" then
  local raw = io.read("*a")
  local req = JSON.decode(raw or "")
  if not req then
    io.stderr:write("forge: invalid JSON input\n")
    os.exit(2)
  end
  print(JSON.encode(Forge.dossier(req.task, req), true))
end

return Forge
