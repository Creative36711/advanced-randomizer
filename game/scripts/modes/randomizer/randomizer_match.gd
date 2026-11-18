extends RefCounted
const Config := preload("randomizer_config.gd")
const RNG := preload("seeded_rng.gd")
const Registry := preload("tier_registry.gd")
const Commands := preload("command_set_shuffler.gd")
const Chaos := preload("chaos_event_system.gd")
const Draft := preload("draft_manager.gd")
const Spells := preload("spellbook_shuffler.gd")

var owner_ref: WeakRef
var sim:
	get: return owner_ref.get_ref()
var config: Dictionary
var db := Registry.new()
var rng: RNG
var commands := Commands.new()
var chaos := Chaos.new()
var draft := Draft.new()
var spells := Spells.new()
var state := {}
var units := {} # compiled, producible units; never draw an unmounted template

func _init(owner_sim, options: Dictionary) -> void:
	owner_ref = weakref(owner_sim)
	config = options.duplicate(true)
	rng = RNG.new(config.seed)

func mirrored() -> bool:
	return config.sync_mode == Config.SyncMode.MIRRORED

func seat_offset(team: int) -> int:
	return 0 if mirrored() else sim.team_ids().find(team)

func collect() -> void:
	for id in db.ids:
		var rule: Dictionary = sim._unit_production_rules.get(id, {})
		if not rule.is_empty() and not rule.get("is_ring_hero", false) and sim._rules.get("unit_rules", {}).has(rule.object_id):
			units[id] = rule
	spells.collect(self)

func start() -> void:
	state.clock = 0
	draft.setup(self)
	chaos.setup(self)
	collect()
	commands.setup(self)
	spells.shuffle(self)

func tick() -> void:
	state.clock += 1
	if config.chaos:
		chaos.tick(self)
	if config.draft:
		draft.tick(self)
	for id in sim.structure_ids():
		commands.attach(self, sim.structures[id])

func unit_price(source: String) -> int:
	return sim._production_rule_value(source, "cost_rule", "default_cost")

func snapshot() -> Dictionary:
	return {"balance": db.digest, "rng": rng.state, "state": state}

func restore(data: Dictionary) -> void:
	collect()
	rng.state = data.rng
	state = data.state

func ticks(seconds: float) -> int:
	return maxi(1, roundi(seconds / sim.TICK_SECONDS))

func tags(row: Dictionary) -> Array:
	return db.entries.get(row.get("unit_type", ""), {}).get("tags", [])

func fortress(team: int) -> Dictionary:
	for id in sim.living_structure_ids(team):
		var b: Dictionary = sim.structures[id]
		if b.structure_kind == "fortress" and b.get("construction_progress", 0.0) >= 1.0:
			return b
	return {}

func spawn(team: int, unit: String) -> bool:
	var fort := fortress(team)
	if fort.is_empty() or not units.has(unit) or (db.entries[unit].kind == "hero" and sim.hero_unavailable(team, unit)):
		return false
	var rule: Dictionary = units[unit]
	var id: int = sim._next_dynamic_id[team]
	sim._next_dynamic_id[team] = id + 1
	var pos := Vector2(fort.position).move_toward(fort.rally, sim.PRODUCTION_EXIT_RADIUS)
	sim._add_battalion(id, team, pos, rule.display_name, rule.object_id, unit, 0)
	if not sim.entities.has(id):
		return false
	sim._emit_event("randomizer.spawn", fort.id, id, {"team": team, "unit_type": unit})
	return true
