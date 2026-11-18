extends SceneTree
const F := preload("randomizer_fixture.gd")

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var sim = F.make(F.options())
	var m = sim.randomizer
	var ok: bool = m.state.offers.is_empty()
	sim._emit_event("construction.completed", 0, sim.fortress_id(0), {"team": 0, "structure_kind": "fortress"})
	sim.tick()
	var offer: Dictionary = m.state.offers[0]
	var seen := {}
	for card in offer.cards:
		seen[card.id] = true
	ok = ok and seen.size() == 3 and offer == m.state.offers[1] and not sim.clock_paused
	ok = ok and not m.draft.choose(m, 0, offer.serial + 1, 0).ok
	var elf := F.Adapter._runtime_id("ElvenLorienArcherHorde")
	for i in 4:
		m.spawn(0, elf)
		if i == 2:
			ok = ok and not m.draft.archer_synergy(m, 0)
	ok = ok and m.draft.archer_synergy(m, 0) and m.draft.synergy_factor(m, true, ["leadership"]) == 130
	ok = ok and m.draft.reward(m, 0, {"kind": "buff", "id": "archer"})
	ok = ok and m.draft.damage_factor(m, {"unit_type": elf, "team": 0}) >= 1.15
	ok = ok and m.draft.choose(m, 0, offer.serial, 1).ok and not m.draft.choose(m, 0, offer.serial, 1).ok
	var hero := F.Adapter._runtime_id("GondorAragorn")
	ok = ok and m.spawn(1, hero) and not m.spawn(1, hero)
	ok = ok and m.spells.grant(m, 1, "SpellBookHeal") and sim.has_power(1, "SpellBookHeal")
	sim.ai_enabled = false
	m.state.clock = offer.deadline - 1
	sim.tick()
	ok = ok and m.state.offers.is_empty()
	print("RANDOMIZER_DRAFT ok=", ok)
	quit(0 if ok else 1)
