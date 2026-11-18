extends SceneTree
const F := preload("randomizer_fixture.gd")

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var sim = F.make(F.options())
	var m = sim.randomizer
	var b: Dictionary = sim.structures[sim.producer_id(0, "barracks")]
	var enemy: Dictionary = sim.structures[sim.producer_id(1, "barracks")]
	var ok: bool = b.production == enemy.production and not b.ar_sources.is_empty()
	for unit in b.ar_sources:
		ok = ok and m.db.entries[unit].tier == m.db.entries[b.ar_sources[unit]].tier
	var unit: String = b.production[0]
	var order: Dictionary = sim.queue_unit(0, b.id, unit)
	ok = ok and order.ok and order.item.cost == sim._production_rule_value(b.ar_sources[unit], "cost_rule", "default_cost")
	var before: String = sim.state_hash()
	ok = ok and not m.commands.reroll(m, 1, b.id).ok and before == sim.state_hash()
	var cash: int = sim.resources_for_team(0)
	var cost: int = m.commands.price(m, b)
	var reroll: Dictionary = m.commands.reroll(m, 0, b.id)
	ok = ok and reroll.ok and sim.resources_for_team(0) == cash - cost and m.commands.price(m, b) > cost
	ok = ok and b.queue[0].unit_type == unit and m.commands.reroll(m, 1, enemy.id).ok and b.production == enemy.production
	sim.team_resources[1] = 0
	before = sim.state_hash()
	ok = ok and not m.commands.reroll(m, 1, enemy.id).ok and before == sim.state_hash()
	sim.team_resources[1] = 10000
	m.commands.train_ai(m, 1)
	ok = ok and not enemy.queue.is_empty() and enemy.queue[0].unit_type in enemy.production
	var cfg := F.options()
	cfg.sync_mode = F.Config.SyncMode.INDEPENDENT
	var independent = F.make(cfg)
	ok = ok and independent.structures[b.id].production != independent.structures[enemy.id].production
	var restored = F.make(F.options())
	ok = ok and restored.restore(sim.snapshot()) and restored.state_hash() == sim.state_hash()
	print("RANDOMIZER_PRODUCTION ok=", ok)
	quit(0 if ok else 1)
