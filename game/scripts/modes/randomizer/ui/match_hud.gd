extends VBoxContainer
## Mouse input is stopped by buttons only. No clock, RNG or sim mutation in the HUD.
signal command(kind: String, args: Dictionary)
var reroll := Button.new()
var producer := 0

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	position = Vector2(18, 80)
	add_child(reroll)
	build_draft()
	reroll.pressed.connect(func(): command.emit("ar_reroll", {"producer": producer}))

func refresh(m, team: int, selected: int) -> void:
	producer = selected
	refresh_draft(m, team)
	refresh_book(m, team)
	var b: Dictionary = m.sim.structures.get(selected, {})
	reroll.visible = b.get("team") == team and b.has("ar_original") and b.health > 0 and b.construction_progress >= 1.0
	if reroll.visible:
		var price: int = m.commands.price(m, b)
		reroll.text = "Reroll Production · %d" % price
		reroll.disabled = m.sim.resources_for_team(team) < price

const ICONS := {"unit": preload("icons/unit.svg"), "hero": preload("icons/hero.svg"), "spell": preload("icons/spell.svg"), "buff": preload("icons/buff.svg")}
const ACTION := {"unit": "Spawn Squad", "hero": "Summon Hero", "spell": "Grant Spell", "buff": "Global Buff"}
var draft_box := VBoxContainer.new()
var countdown := Label.new()
var cards := HBoxContainer.new()
var shown := -1
var book_order := []

func build_draft() -> void:
	add_child(draft_box)
	draft_box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	draft_box.add_child(countdown)
	draft_box.add_child(cards)
	cards.mouse_filter = Control.MOUSE_FILTER_IGNORE
	for index in 3:
		var button := Button.new()
		button.custom_minimum_size = Vector2(160, 60)
		button.pressed.connect(func(): command.emit("ar_draft", {"offer": shown, "index": index}))
		cards.add_child(button)

func refresh_draft(m, team: int) -> void:
	var offer: Dictionary = m.state.offers.get(team, {})
	draft_box.visible = not offer.is_empty()
	if offer.is_empty():
		shown = -1
		return
	countdown.text = "Choose one · auto-pick in %ds" % ceili(float(offer.deadline - m.state.clock) * m.sim.TICK_SECONDS)
	if shown == offer.serial:
		return
	shown = offer.serial
	for i in 3:
		var card: Dictionary = offer.cards[i]
		var label: String = m.db.entries.get(card.id, {}).get("id", card.id)
		if card.kind == "buff":
			label = "%s damage +%d%%" % [label.capitalize(), m.db.balance.buff_percent]
		else:
			label = label.trim_prefix("SpellBook").capitalize()
		var button := cards.get_child(i) as Button
		button.icon = ICONS[card.kind]
		button.text = "%s · T%d\n%s" % [ACTION[card.kind], card.tier, label]
		button.tooltip_text = button.text.replace("\n", ": ")

func refresh_book(m, team: int) -> void:
	var tree: Dictionary = m.sim._team_tree(team)
	if tree.order != book_order:
		book_order = tree.order.duplicate()
		var hud = get_parent()
		hud._spellbook_power_rows = m.spells.hud_rows(tree)
		hud._configure_orb_rows()
