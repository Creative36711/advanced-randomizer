extends SceneTree
const F := preload("randomizer_fixture.gd")

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var cfg := F.options()
	cfg.draft = false
	var sim = F.make(cfg)
	sim.ai_enabled = false
	var m = sim.randomizer
	var c: Dictionary = m.state.chaos
	m.state.clock = 1649
	sim.tick()
	var expected: String = c.announced
	var ok: bool = expected != "" and c.next - m.state.clock == 150
	m.state.clock = 1799
	sim.tick()
	ok = ok and c.active == expected and c.wave == 1 and c.announced == ""
	var count0: int = sim.entities.size()
	m.chaos.launch(m, "wings")
	ok = ok and sim.entities.size() == count0 + 2
	var original := {}
	for team in sim.team_ids():
		var units: Array = sim.living_ids(team)
		var flying: Dictionary = sim.entities[units.back()]
		ok = ok and m.db.entries[flying.unit_type].tier == 3 and "flying" in m.tags(flying)
		original[team] = units
	m.chaos.launch(m, "betrayal")
	for team in sim.team_ids():
		var moved: Array = original[team].filter(func(id): return sim.entities[id].team != team)
		ok = ok and moved.size() == 1
	var b: Dictionary = sim.structures[sim.producer_id(0, "barracks")]
	var src: String = b.ar_sources[b.production[0]]
	var base := int(sim._unit_production_rules[src].default_cost)
	m.chaos.launch(m, "collapse")
	ok = ok and m.unit_price(src) == roundi(base * 0.6) and is_equal_approx(m.chaos.speed(m), 0.8)
	m.state.clock = c.until - 1
	sim.tick()
	ok = ok and m.unit_price(src) == base and m.chaos.speed(m) == 1.0
	var order: Dictionary = sim.queue_unit(0, b.id, b.production[0])
	m.chaos.launch(m, "haste")
	var due: int = b.queue[0].complete_tick
	sim.tick()
	ok = ok and order.ok and b.queue[0].complete_tick == due - 1 and m.chaos.work_ticks(m) == 2
	m.state.clock = c.until - 1
	sim.tick()
	ok = ok and m.chaos.work_ticks(m) == 1
	m.chaos.launch(m, "meteors")
	ok = ok and c.meteors.size() == 6
	var hp: int = b.health
	m.chaos.impact(m, b.position)
	ok = ok and b.health == hp - int(m.db.balance.meteor_damage)
	sim.advance(17)
	ok = ok and c.meteors.is_empty()
	print("RANDOMIZER_CHAOS ok=", ok)
	quit(0 if ok else 1)
