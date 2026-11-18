class_name SeededRNG
extends RandomNumberGenerator
## One PCG stream for the whole match. Pin the engine version across peers.

func _init(code: String) -> void:
	# Exactly 60 bits: no signed conversion ambiguity, no platform hash().
	seed = code.sha256_text().left(15).hex_to_int()

func weighted_index(weights: Array) -> int:
	var total := 0
	for weight in weights:
		total += int(weight)
	if total <= 0:
		return -1
	var roll := self.randi_range(1, total)
	for i in weights.size():
		roll -= int(weights[i])
		if roll <= 0:
			return i
	return -1
