class_name CommandSetShuffler
extends RefCounted

# A tier deck is drawn without replacement; all seats have the same tier budget.
# Rotating the first deal gives Independent seats distinct picks where the pool allows.
func deal(m) -> Dictionary:
	var decks := {}
	for kind in ["unit", "hero", "spell"]:
		var source: Dictionary = m.spells.library if kind == "spell" else m.units
		for tier in range(1, 5):
			var pool: Array = m.db.pool(kind, tier, source)
			var deck := []
			while not pool.is_empty():
				var weights := pool.map(func(id): return m.db.entries[id].weight)
				deck.append(pool.pop_at(m.rng.weighted_index(weights)))
			decks[kind + str(tier)] = deck
	return decks

func setup(m) -> void:
	m.state.decks = deal(m)
	m.state.mirror_cursor = m.rng.state
	for id in m.sim.structure_ids():
		attach(m, m.sim.structures[id])

func attach(m, building: Dictionary) -> void:
	if building.has("ar_original") or not m.sim.team_ids().has(building.get("team")):
		return
	var slots: Array = building.get("production", [])
	if not slots.any(func(id): return _eligible(m, id)):
		return
	building.ar_original = slots.duplicate()
	building.ar_rerolls = 0
	building.ar_cursor = m.state.mirror_cursor
	_replace(m, building, m.state.decks)

func _eligible(m, id: String) -> bool:
	var row: Dictionary = m.db.entries.get(id, {})
	return m.units.has(id) and not row.is_empty() and ((row.kind == "unit" and m.config.shuffle_units) or (row.kind == "hero" and m.config.shuffle_heroes))

func _replace(m, building: Dictionary, decks: Dictionary) -> void:
	var offsets := {}
	var replacements := {}
	var slots: Array[String] = []
	for original in building.ar_original:
		var pick: String = original
		if _eligible(m, original):
			var row: Dictionary = m.db.entries[original]
			var key: String = row.kind + str(row.tier)
			var deck: Array = decks[key]
			var index := int(offsets.get(key, String(building.structure_kind).hash() + m.seat_offset(building.team)))
			pick = deck[posmod(index, deck.size())]
			offsets[key] = index + 1
			replacements[pick] = original
		slots.append(pick)
	building.production = slots
	building.ar_sources = replacements # original price, training time, upgrade gate and socket

func price(m, building: Dictionary) -> int:
	return int(m.db.balance.reroll_base) + int(building.get("ar_rerolls", 0)) * int(m.db.balance.reroll_step)

func reroll(m, team: int, id: int) -> Dictionary:
	var b: Dictionary = m.sim.structures.get(id, {})
	if b.get("team") != team or not b.has("ar_original") or b.get("health", 0) <= 0 or b.get("construction_progress", 0.0) < 1.0 or m.sim.winner != -1:
		return {"ok": false, "reason": "producer-unavailable"}
	var cost := price(m, b)
	var money := int(m.sim.resources_for_team(team))
	if money < cost:
		return {"ok": false, "reason": "insufficient-resources"}
	# Replay the common cursor for corresponding mirrored buildings. No extra
	# generators or unbounded history of other players' rerolls is needed.
	var cursor: int = m.rng.state
	if m.mirrored():
		m.rng.state = b.ar_cursor
	_replace(m, b, deal(m))
	if m.mirrored():
		b.ar_cursor = m.rng.state
		m.rng.state = cursor
	b.ar_rerolls += 1
	m.sim.team_resources[team] = money - cost
	return {"ok": true, "cost": cost}

func train_ai(m, team: int) -> void:
	# Ask the building, not the old faction plan. queue_unit remains the sole
	# authority for cost, CP, uniqueness, tech, completion and eventual spawn.
	for id in m.sim.living_structure_ids(team):
		var b: Dictionary = m.sim.structures[id]
		if not b.get("queue", []).is_empty():
			continue
		var slots: Array = b.get("production", [])
		for i in slots.size():
			var slot: String = slots[(i + int(b.get("ar_ai_index", 0))) % slots.size()]
			if not m.units.has(slot):
				continue
			if m.sim.queue_unit(team, id, slot).ok:
				b.ar_ai_index = slots.find(slot) + 1
				break

func radial_entry(m, b: Dictionary, unit: String, locked: Array, button: Button, queue: Dictionary) -> Dictionary:
	var source: String = b.ar_sources[unit]
	var rule: Dictionary = m.sim._unit_production_rules[source]
	var slot := int(m.sim.structure_command_slot(b.id, rule.get("command_id", "")))
	var label := String(m.sim.production_rule_display_name(unit))
	var icon = button.icon if button else null
	return {"command_kind": "hero" if m.db.entries[unit].kind == "hero" else "train", "id": unit,
		"icon": icon, "text": label if icon == null else "", "label": label, "tooltip": label,
		"enabled": unit not in locked, "slot": slot if slot > 0 else rule.get("command_slot", 0),
		"cost": m.unit_price(source), "command_points": m.sim.unit_command_point_cost(unit), "queue_row": queue}
