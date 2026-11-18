class_name TierRegistry
extends RefCounted

const SOURCE := "res://scripts/modes/randomizer/data/tiers_db.json"
const Adapter := preload("res://src/retail_slice/playable_unit_runtime_adapter.gd")
const FACTIONS := ["angmar", "dwarves", "elves", "isengard", "men", "mordor", "wild"]
var entries := {} # keyed by the actual object/spell id used by RetailSliceSim
var balance := {}
var ids: Array = []
var digest := ""
var error := ""

func _init() -> void:
	var text := FileAccess.get_file_as_string(SOURCE)
	var doc = JSON.parse_string(text)
	if not doc is Dictionary or doc.get("version") != 1 or not doc.get("entries") is Array or not doc.get("balance") is Dictionary:
		error = "Invalid tiers_db.json"
		return
	for row in doc.entries:
		if not row is Dictionary or row.get("faction") not in FACTIONS or row.get("kind") not in ["unit", "hero", "spell"] or not row.get("id") is String or row.id.is_empty() or not row.get("tags") is Array or row.tags.is_empty():
			error = "Invalid tier entry: %s" % str(row)
			return
		var tier := int(row.get("tier", 0))
		var weight := int(row.get("weight", 1))
		if tier != row.tier or tier < 1 or tier > 4 or weight < 1 or weight > 1000:
			error = "Invalid tier/weight: " + row.id
			return
		var key: String = row.id if row.kind == "spell" else Adapter._runtime_id(row.id)
		if entries.has(key):
			error = "Duplicate tier id: " + key
			return
		row.tier = tier
		row.weight = weight
		entries[key] = row
	ids = entries.keys()
	ids.sort()
	balance = doc.balance
	digest = text.sha256_text()

func pool(kind: String, tier: int, available: Dictionary, tag := "") -> Array:
	# Exclude unavailable/unconverted templates, never substitute another tier.
	var result := []
	for id in ids:
		var row: Dictionary = entries[id]
		if row.kind == kind and row.tier == tier and available.has(id) and (tag.is_empty() or tag in row.tags):
			result.append(id)
	return result
