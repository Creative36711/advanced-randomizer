extends SceneTree
const Config := preload("res://scripts/modes/randomizer/randomizer_config.gd")
const RNG := preload("res://scripts/modes/randomizer/seeded_rng.gd")
const Registry := preload("res://scripts/modes/randomizer/tier_registry.gd")

func _initialize() -> void:
	var config := Config.defaults()
	config.seed = Config.new_seed()
	var valid := Config.valid(config)
	config.seed = "!"
	var db := Registry.new()
	var a := RNG.new("MiddleEarth")
	var b := RNG.new("MiddleEarth")
	var other := RNG.new("Mordor")
	var different := false
	for i in 100:
		var draw := a.weighted_index([10, 20, 30])
		valid = valid and draw == b.weighted_index([10, 20, 30])
		different = different or draw != other.weighted_index([10, 20, 30])
	var factions := {}
	for row in db.entries.values():
		factions[row.faction] = true
	var ok := valid and different and not Config.valid(config) and factions.size() == 7 and db.error.is_empty()
	print("RANDOMIZER_CORE ok=", ok, " templates=", db.ids.size())
	quit(0 if ok else 1)
