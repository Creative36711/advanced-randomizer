extends SceneTree
const F := preload("res://tests/randomizer_fixture.gd")

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var a = F.make(F.options())
	a.advance(2500)
	var bytes: PackedByteArray = a.snapshot()
	var b = F.make(F.options())
	var c = F.make(F.options())
	var first: bool = b.restore(bytes)
	var second: bool = c.restore(bytes)
	var hashes: bool = first and second and b.state_hash() == c.state_hash() and b.state_hash() == a.state_hash()
	var books: bool = first and b.randomizer != null and b.randomizer.state.get("books", {}).size() == 2
	# Twin continuations must run the identical draft/chaos timeline from RNG state alone.
	b.advance(320)
	c.advance(320)
	var stable: bool = hashes and b.state_hash() == c.state_hash() \
		and var_to_bytes(b.randomizer.snapshot()) == var_to_bytes(c.randomizer.snapshot())
	print("RANDOMIZER_PERSISTENCE ok=%s restore=%s/%s books=%s" % [str(books and stable), str(first), str(second), str(books)])
	quit(0 if books and stable else 1)
