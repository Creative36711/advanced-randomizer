extends RefCounted
## Asset-free inputs for the actual Skirmish simulator (like upstream's
## retail_lockstep_determinism_runner). No second implementation of its rules.
const Sim := preload("res://src/retail_slice/retail_slice_sim.gd")
const Manifest := preload("res://src/retail_slice/retail_faction_manifest.gd")
const Config := preload("res://scripts/modes/randomizer/randomizer_config.gd")
const Adapter := preload("res://src/retail_slice/playable_unit_runtime_adapter.gd")

static func options() -> Dictionary:
	var cfg := Config.defaults()
	cfg.enabled = true
	cfg.seed = "Imladris42"
	cfg.sync_mode = Config.SyncMode.MIRRORED
	return cfg

static func make(config: Dictionary):
	var sim := Sim.new()
	var manifest := Manifest.default_manifest()
	for kind in manifest.structure_kinds:
		manifest.structure_armor[kind] = {"default": 1.0}
	var stats := {}
	for spec in [["ElvenLorienArcherHorde", "archery_range", "ranged-infantry"], ["MordorFellBeast", "stable", "monster"], ["ElvenFortressEagle", "stable", "monster"], ["GondorAragorn", "fortress", "hero"], ["IsengardLurtz", "fortress", "hero"]]:
		var id := Adapter._runtime_id(spec[0])
		manifest.unit_production_rules[id] = {"object_id": id, "display_name": spec[0], "producer_kind": spec[1], "category": spec[2], "default_cost": 50, "default_build_ticks": 10, "default_command_points": 5}
		manifest.ai_production_plan.append(id)
	for id in manifest.unit_production_rules:
		var rule: Dictionary = manifest.unit_production_rules[id]
		stats[rule.object_id] = {"horde_id": id, "category": rule.get("category", "infantry"), "member_count": 1, "member_health": 200,
			"member_damage": 10, "speed": 1.0, "acceleration": 1.0, "braking": 1.0, "turn_rate_degrees_per_second": 180.0,
			"vision_range": 1.0, "attack_range": 1.0, "attack_period_ticks": 10, "pre_attack_ticks": 2, "firing_duration_ticks": 2,
			"formation_positions": [Vector3.ZERO], "provenance": {}}
	var rules := {"game": "rotwk", "enable_base_loop": true, "faction_manifest": manifest, "unit_rules": stats,
		"spawn_initial_battalions": false, "starting_resources": 3000, "command_point_cap": 240, "ai_attack_delay_ticks": 4000}
	if not config.is_empty():
		rules.randomizer = config.duplicate(true)
	# Two already-compiled, castable spell rows with the normal ownership tree.
	for id in ["SpellBookHeal", "SpellBookRallyingCall"]:
		var slot := sim._spellbook_order.size() + 1
		var science: String = "SCIENCE_" + id
		sim._spellbook_order.append(id)
		sim._spellbook_powers[id] = {"id": id, "science_id": science, "castable": true, "cost": 1, "purchase_slot": slot, "cast_slot": slot, "effect": {"kind": "heal"}, "reload_ticks": 10}
		sim._spellbook_sciences[science] = {"cost": 1, "slot": slot, "groups": []}
		sim._science_to_power[science] = id
	sim._spellbook_ready = true
	sim.setup({}, rules)
	for team in sim.team_ids():
		sim.team_command_points[team] = 0 # fixture has no starting army
	sim.force_ai_construction_complete()
	return sim
