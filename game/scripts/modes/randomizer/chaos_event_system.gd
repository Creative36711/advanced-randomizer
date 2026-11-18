class_name ChaosEventSystem
extends RefCounted

func setup(m) -> void:
	m.state.chaos = {"next": m.ticks(m.db.balance.event_interval_s), "announced": "", "active": "", "until": 0,
		"wave": 0, "meteors": []}

func tick(m) -> void:
	var c: Dictionary = m.state.chaos
	var now: int = m.state.clock
	if now >= c.until:
		c.active = ""
	if now == c.next - m.ticks(m.db.balance.warning_s):
		var pool: Array = m.db.balance.events.filter(func(e): return e.id != "wings" or not flyers(m).is_empty())
		c.announced = pool[m.rng.weighted_index(pool.map(func(e): return int(e.weight)))].id
		m.sim._emit_event("randomizer.warning", 0, 0, {"event": c.announced, "start": c.next})
	if now == c.next:
		launch(m, c.announced)
		c.announced = ""
		c.next += m.ticks(m.db.balance.event_interval_s)
	if c.active == "haste":
		var extra := work_ticks(m) - 1
		if extra > 0:
			for id in m.sim.structure_ids():
				var queue: Array = m.sim.structures[id].get("queue", [])
				if queue.is_empty():
					continue
				var advance := mini(extra, maxi(0, int(queue[0].complete_tick) - int(m.sim.tick_index)))
				for item in queue:
					item.start_tick -= advance
					item.complete_tick -= advance
	while not c.meteors.is_empty() and c.meteors[0].tick <= now:
		var shot: Dictionary = c.meteors.pop_front()
		impact(m, shot.point)

func launch(m, event: String) -> void:
	var c: Dictionary = m.state.chaos
	c.wave += 1
	c.active = event
	c.until = m.state.clock + m.ticks(4) # keep instant events visible briefly
	match event:
		"collapse": c.until = m.state.clock + m.ticks(m.db.balance.collapse_duration_s)
		"haste": c.until = m.state.clock + m.ticks(m.db.balance.haste_duration_s)
		"wings":
			var pool := flyers(m)
			if not pool.is_empty():
				var shared: int = m.rng.randi_range(0, pool.size() - 1)
				for team in m.sim.team_ids():
					var index := shared if m.mirrored() else int(m.rng.randi_range(0, pool.size() - 1))
					m.spawn(team, pool[index])
		"betrayal": _betray(m)
		"meteors":
			for i in int(m.db.balance.meteor_count):
				var p := strike_point(m)
				var delay := 6 + 2 * i
				c.meteors.append({"tick": m.state.clock + delay, "point": p})
				m.sim._emit_event("randomizer.meteor.incoming", 0, 0, {"point": p, "delay": delay})
	m.sim._emit_event("randomizer.wave", 0, 0, {"wave": c.wave, "event": event})

func flyers(m) -> Array:
	return m.db.pool("unit", 3, m.units, "flying")

func _betray(m) -> void:
	var transfers := []
	var teams: Array = m.sim.team_ids()
	var shared_slot: int = m.rng.randi()
	for team in teams:
		var candidates := []
		for id in m.sim.living_ids(team):
			var e: Dictionary = m.sim.entities[id]
			if not e.get("is_builder", false) and e.get("category", "") != "hero" and m.db.entries.get(e.get("unit_type", ""), {}).get("kind") == "unit":
				candidates.append(id)
		if candidates.is_empty():
			continue
		var enemies := teams.filter(func(t): return m.sim._is_hostile(team, t))
		var dest: int = m.sim.CREEP_TEAM if enemies.is_empty() else enemies[m.rng.randi_range(0, enemies.size() - 1)]
		var slot: int = shared_slot % candidates.size() if m.mirrored() else m.rng.randi_range(0, candidates.size() - 1)
		transfers.append([candidates[slot], dest])
	# Freeze candidates before any transfer; a defector cannot be picked twice.
	for move in transfers:
		if m.sim.set_entity_team(move[0], move[1]).ok:
			m.sim.issue_stop([int(move[0])] as Array[int], move[1])

func strike_point(m) -> Vector2:
	var outline: PackedVector2Array = m.sim.playable_outline
	var box: Rect2
	if outline.size() >= 3:
		box = Rect2(outline[0], Vector2.ZERO)
		for point in outline:
			box = box.expand(point)
	else:
		# Asset-free / tiny maps carry no polygon. Include all starting bases.
		box = Rect2(m.sim._team_center(m.sim.team_ids()[0]), Vector2.ZERO)
		for team in m.sim.team_ids():
			box = box.expand(m.sim._team_center(team))
		box = box.grow(16)
	for attempt in 48:
		var p := Vector2(m.rng.randi_range(floori(box.position.x * 100), ceili(box.end.x * 100)),
			m.rng.randi_range(floori(box.position.y * 100), ceili(box.end.y * 100))) / 100.0
		if outline.size() < 3 or Geometry2D.is_point_in_polygon(p, outline):
			return p
	return outline[0]

func impact(m, point: Vector2) -> void:
	var radius: float = m.db.balance.meteor_radius
	var damage: int = int(m.db.balance.meteor_damage)
	for id in m.sim.entity_ids():
		if point.distance_squared_to(m.sim.entities[id].position) <= radius * radius:
			m.sim._apply_area_damage_to_battalion(id, damage, "flame")
	for id in m.sim.structure_ids():
		if point.distance_squared_to(m.sim.structures[id].position) <= radius * radius:
			m.sim._apply_area_damage_to_structure(id, damage, "flame")
	m.sim._emit_event("randomizer.meteor.impact", 0, 0, {"point": point})

func cost(m, base: int) -> int:
	return roundi(base * float(m.db.balance.collapse_price_percent) / 100.0) if active(m, "collapse") else base

func speed(m) -> float:
	return float(m.db.balance.collapse_speed_percent) / 100.0 if active(m, "collapse") else 1.0

func work_ticks(m) -> int:
	if not active(m, "haste"):
		return 1
	# Integer work budget also handles balance edits such as +50% without a float clock.
	var pct := int(m.db.balance.haste_percent)
	var t := int(m.state.clock)
	return (t * pct) / 100 - ((t - 1) * pct) / 100

func active(m, id: String) -> bool:
	return m.config.chaos and m.state.get("chaos", {}).get("active", "") == id
