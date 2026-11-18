class_name RandomizerConfig
extends RefCounted
## The host serializes primitives, never a Resource instance or a local RNG state.

enum SyncMode { INDEPENDENT, MIRRORED }
const FLAGS := ["enabled", "shuffle_units", "shuffle_heroes", "shuffle_spellbook", "draft", "chaos"]
const ALPHABET := "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

static func defaults() -> Dictionary:
	return {"version": 1, "enabled": false, "seed": "Arda", "sync_mode": SyncMode.INDEPENDENT,
		"shuffle_units": true, "shuffle_heroes": true, "shuffle_spellbook": true, "draft": true, "chaos": true}

static func valid(raw: Variant) -> bool:
	if not raw is Dictionary or raw.size() != defaults().size() or raw.get("version") != 1:
		return false
	for flag in FLAGS:
		if not raw.get(flag) is bool:
			return false
	if not raw.get("sync_mode") is int or raw.sync_mode not in SyncMode.values():
		return false
	if not raw.get("seed") is String or raw.seed.is_empty() or raw.seed.length() > 32:
		return false
	for ch in raw.seed:
		if not ALPHABET.contains(ch):
			return false
	return true

static func new_seed() -> String:
	# Lobby only. Entropy never enters a running simulation.
	var text := ""
	for byte in Crypto.new().generate_random_bytes(12):
		text += ALPHABET[byte % ALPHABET.length()]
	return text
