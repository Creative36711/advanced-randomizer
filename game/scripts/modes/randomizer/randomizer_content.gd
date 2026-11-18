extends RefCounted
## Expand only the loader's pool, not the teams in a match. Missing packs are
## skipped; assets must pass the same fieldability checks as a normal faction.
const Registry := preload("tier_registry.gd")

static func options(scene) -> Dictionary:
	var gs = scene.get_node_or_null("/root/GameState") if scene.is_inside_tree() else null
	return gs.retail_randomizer if gs != null else {}

static func manifests(scene, restore_faction: String) -> Array:
	var seats: Array = scene._team_faction_manifests.values()
	if not options(scene).get("enabled", false):
		return seats
	if scene.randomizer_rosters.is_empty():
		for faction in Registry.FACTIONS:
			var manifest: Dictionary = scene._resolve_faction_manifest(faction)
			if not manifest.has("_error"):
				scene.randomizer_rosters.append(manifest)
		scene._classify_faction_units(restore_faction)
	return seats + scene.randomizer_rosters

static func add_rules(scene, rules: Dictionary) -> void:
	var config := options(scene)
	if not config.get("enabled", false):
		return
	rules.randomizer = config.duplicate(true)
	rules.logic_random_seed = String(config.seed).sha256_text().left(15).hex_to_int()
	if config.shuffle_spellbook or config.draft:
		var books := []
		for faction in Registry.FACTIONS:
			var doc: Dictionary = scene._faction_spellbook_document(faction)
			if not doc.is_empty():
				books.append(doc)
		rules.randomizer_spellbooks = books
