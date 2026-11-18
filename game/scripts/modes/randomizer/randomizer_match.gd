extends RefCounted
const Config := preload("randomizer_config.gd")
const RNG := preload("seeded_rng.gd")
const Registry := preload("tier_registry.gd")
const Commands := preload("command_set_shuffler.gd")
const Spells := preload("spellbook_shuffler.gd")

var owner_ref: WeakRef
var sim:
	get: return owner_ref.get_ref()
var config: Dictionary
var db := Registry.new()
var rng: RNG
var commands := Commands.new()
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
	collect()
	commands.setup(self)
	spells.shuffle(self)

func tick() -> void:
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
