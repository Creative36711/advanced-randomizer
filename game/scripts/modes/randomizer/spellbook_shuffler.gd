extends RefCounted
## Copy compiled effects, not their faction's prerequisite graph. A replacement
## occupies the original slot/science, so the rest of the tree stays reachable.
var library := {}

func collect(m) -> void:
	library.clear()
	_collect_tree(m.sim._spellbook_global_bundle())
	for team in m.sim.team_ids():
		_collect_tree(m.sim._team_tree(team))
	var probe = m.sim.get_script().new()
	probe._rules = m.sim._rules
	for doc in m.sim._rules.get("randomizer_spellbooks", []):
		if probe.configure_spellbook_runtime(doc):
			_collect_tree(probe._team_tree(0))

func _collect_tree(tree: Dictionary) -> void:
	for id in tree.get("order", []):
		var row: Dictionary = tree.powers[id]
		if not library.has(id) and row.get("castable", false) and not row.get("nonpressable", false):
			library[id] = row.duplicate(true)

func shuffle(m) -> void:
	if not m.config.shuffle_spellbook or library.is_empty():
		return
	for team in m.sim.team_ids():
		var tree: Dictionary = m.sim._team_tree(team).duplicate(true)
		var offsets := {}
		var powers := {}
		var order: Array[String] = []
		for old in tree.order:
			var row: Dictionary = tree.powers[old].duplicate(true)
			var pick: String = old
			if m.db.entries.has(old) and library.has(old):
				var key := "spell" + str(m.db.entries[old].tier)
				var deck: Array = m.state.decks[key]
				var off := int(offsets.get(key, m.seat_offset(team)))
				pick = deck[off % deck.size()]
				offsets[key] = off + 1
				var cast: Dictionary = library[pick].duplicate(true)
				for field in ["purchase_slot", "cast_slot", "science_id", "cost"]:
					cast[field] = row[field]
				row = cast
			powers[pick] = row
			order.append(pick)
			tree.science_to_power[row.science_id] = pick
		tree.powers = powers
		tree.order = order
		m.sim._team_spellbooks[team] = tree

func grant(m, team: int, id: String) -> bool:
	if not library.has(id) or m.sim.has_power(team, id):
		return false
	var tree: Dictionary = m.sim._team_tree(team).duplicate(true)
	if not tree.powers.has(id):
		var row: Dictionary = library[id].duplicate(true)
		var slot := 1
		for power in tree.powers.values():
			slot = maxi(slot, int(power.purchase_slot) + 1)
		row.purchase_slot = slot
		row.cast_slot = slot
		row.cost = 0
		row.science_id = "AR_DRAFT_" + id
		tree.powers[id] = row
		tree.order.append(id)
		tree.sciences[row.science_id] = {"cost": 0, "slot": slot, "groups": []}
		tree.science_to_power[row.science_id] = id
	var science: String = tree.powers[id].science_id
	tree.ready = true
	m.sim._team_spellbooks[team] = tree
	m.sim.purchased_powers[team].append(id)
	if science not in m.sim._team_sciences[team]:
		m.sim._team_sciences[team].append(science)
	return true

func hud_rows(tree: Dictionary) -> Array:
	var rows := []
	for id in tree.order:
		var p: Dictionary = tree.powers[id]
		var icons: Array = p.get("icon_ids", [])
		rows.append({"power_id": id, "icon_id": icons[0] if not icons.is_empty() else id,
			"cost": p.cost, "purchase_slot": p.purchase_slot, "label": String(id).trim_prefix("SpellBook").capitalize(), "tooltip": ""})
	return rows
