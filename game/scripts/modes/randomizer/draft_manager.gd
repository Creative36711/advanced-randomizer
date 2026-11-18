class_name DraftManager
extends RefCounted

func setup(m) -> void:
	m.state.offers = {}
	m.state.waiting = {} # counters, not an unbounded list of card objects
	m.state.offer_serial = 0
	m.state.buffs = {}

func trigger(m, team: int) -> void:
	if not m.config.draft:
		return
	var key := -1 if m.mirrored() else team
	m.state.waiting[key] = int(m.state.waiting.get(key, 0)) + 1

func tick(m) -> void:
	var teams: Array = m.sim.team_ids()
	if m.state.clock % m.ticks(m.db.balance.draft_interval_s) == 0:
		for team in teams:
			trigger(m, team)
			if m.mirrored():
				break
	for team in teams:
		var offer: Dictionary = m.state.offers.get(team, {})
		if offer.is_empty():
			continue
		if m.state.clock >= offer.deadline or (m.sim.ai_enabled and m.sim.team_is_ai(team)):
			# Timeout/AI is part of the simulation on every peer. Skip a hero
			# already hired (or a spell bought) since the cards were dealt.
			for i in offer.cards.size():
				if choose(m, team, offer.serial, i).ok:
					break
			m.state.offers.erase(team)
	var keys: Array = m.state.waiting.keys()
	keys.sort()
	for key in keys:
		var seats: Array = teams if key == -1 else [key]
		if seats.any(func(t): return m.state.offers.has(t)):
			continue
		m.state.waiting[key] -= 1
		if m.state.waiting[key] == 0:
			m.state.waiting.erase(key)
		var cards := deal(m, seats)
		m.state.offer_serial += 1
		for team in seats:
			m.state.offers[team] = {"serial": m.state.offer_serial, "cards": cards.duplicate(true),
				"deadline": m.state.clock + m.ticks(m.db.balance.draft_timeout_s)}

func archer_synergy(m, team: int) -> bool:
	var count := 0
	for id in m.sim.living_ids(team):
		if "archer" in m.tags(m.sim.entities[id]):
			count += 1 # battalions, not members
	return count > int(m.db.balance.archer_threshold)

func deal(m, seats: Array) -> Array:
	var boosted := seats.any(func(t): return archer_synergy(m, t))
	var choices := []
	var weights := []
	var tier_weights: Array = m.db.balance.draft_tier_weights
	for id in m.db.ids:
		var row: Dictionary = m.db.entries[id]
		var kind: String = row.kind
		if kind == "spell":
			if not m.spells.library.has(id) or seats.any(func(t): return m.sim.has_power(t, id)):
				continue
		elif not m.units.has(id) or seats.any(func(t): return m.fortress(t).is_empty()):
			continue
		elif kind == "hero" and seats.any(func(t): return m.sim.hero_unavailable(t, id)):
			continue
		choices.append({"kind": kind, "id": id, "tier": row.tier})
		weights.append(int(row.weight) * int(tier_weights[row.tier - 1]) * synergy_factor(m, boosted, row.tags))
	for tag in m.db.balance.buff_tags:
		choices.append({"kind": "buff", "id": tag, "tier": 1})
		weights.append(int(tier_weights[0]) * synergy_factor(m, boosted, [tag]))
	var cards := []
	for i in 3:
		var index: int = m.rng.weighted_index(weights)
		cards.append(choices.pop_at(index))
		weights.remove_at(index)
	return cards

func synergy_factor(m, active: bool, tags: Array) -> int:
	return 100 + int(m.db.balance.synergy_bonus_percent) if active and ("archer" in tags or "leadership" in tags) else 100

func choose(m, team: int, serial: int, index: int) -> Dictionary:
	var offer: Dictionary = m.state.offers.get(team, {})
	if m.sim.winner != -1 or offer.get("serial", -1) != serial or index < 0 or index >= offer.get("cards", []).size():
		return {"ok": false, "reason": "stale-offer"}
	var card: Dictionary = offer.cards[index]
	if not reward(m, team, card):
		return {"ok": false, "reason": "reward-unavailable"}
	m.state.offers.erase(team)
	m.sim._emit_event("randomizer.drafted", 0, 0, {"team": team, "reward": card.id, "offer": serial})
	return {"ok": true}

func reward(m, team: int, card: Dictionary) -> bool:
	match card.kind:
		"hero", "unit": return m.spawn(team, card.id)
		"spell": return m.spells.grant(m, team, card.id)
		"buff":
			if not m.state.buffs.has(team):
				m.state.buffs[team] = {}
			var buffs: Dictionary = m.state.buffs[team]
			buffs[card.id] = int(buffs.get(card.id, 0)) + int(m.db.balance.buff_percent)
			return true
	return false

func damage_factor(m, row: Dictionary) -> float:
	var bonuses: Dictionary = m.state.buffs.get(row.get("team", -1), {})
	var percent := 100
	for tag in m.tags(row):
		percent += int(bonuses.get(tag, 0))
	return percent / 100.0
