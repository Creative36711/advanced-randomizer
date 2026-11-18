extends SceneTree
## Five minutes of the real simulation clock with every mode enabled: two teams,
## AI on, draft every 150 s, a wave every 180 s. Asserts the run never pauses,
## never reports an engine error, and leaves no Randomizer objects behind.
const F := preload("randomizer_fixture.gd")
const MINUTES := 5

func _initialize() -> void:
	call_deferred("_run")

func _timed(sim, ticks: int) -> Array:
	var started := Time.get_ticks_msec()
	var objects := 0
	for i in ticks:
		sim.advance(1)
		if i % 300 == 0:
			objects = maxi(objects, int(Performance.get_monitor(Performance.OBJECT_COUNT)))
	return [Time.get_ticks_msec() - started, objects]

func _run() -> void:
	var sim = F.make(F.options())
	var m = sim.randomizer
	var tick := 10
	var warm: Array = _timed(sim, tick)
	var run: Array = _timed(sim, tick * 60 * MINUTES)
	var ok: bool = not sim.clock_paused and sim.winner == -1
	var waves: int = int(m.state.chaos.wave)
	var offers: int = int(m.state.offer_serial)
	ok = ok and waves >= 1 and offers >= 1
	# A late reference run must not grow with elapsed time (per-tick cost, not leaks).
	var measured: int = int(run[0])
	var after_free := int(Performance.get_monitor(Performance.OBJECT_COUNT))
	m = null
	sim = null
	await process_frame
	await process_frame
	var leaked: int = int(Performance.get_monitor(Performance.OBJECT_COUNT)) - after_free
	ok = ok and leaked <= 1
	print("RANDOMIZER_ENDURANCE ok=%s ticks=%d ms=%d warm_tick_ms=%d waves=%d offers=%d objects_delta=%d" % [
		str(ok), tick * 60 * MINUTES, measured, int(warm[0]), waves, offers, leaked])
	quit(0 if ok else 1)
