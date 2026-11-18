extends VBoxContainer
## Mouse input is stopped by buttons only. No clock, RNG or sim mutation in the HUD.
signal command(kind: String, args: Dictionary)
var reroll := Button.new()
var producer := 0

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	position = Vector2(18, 80)
	add_child(reroll)
	reroll.pressed.connect(func(): command.emit("ar_reroll", {"producer": producer}))

func refresh(m, team: int, selected: int) -> void:
	producer = selected
	var b: Dictionary = m.sim.structures.get(selected, {})
	reroll.visible = b.get("team") == team and b.has("ar_original") and b.health > 0 and b.construction_progress >= 1.0
	if reroll.visible:
		var price: int = m.commands.price(m, b)
		reroll.text = "Reroll Production · %d" % price
		reroll.disabled = m.sim.resources_for_team(team) < price
