extends VBoxContainer
signal changed
const Config := preload("../randomizer_config.gd")
const LABELS := {"enabled": "Enable Randomizer", "shuffle_units": "Shuffle Units", "shuffle_heroes": "Shuffle Heroes",
	"shuffle_spellbook": "Shuffle Spellbook", "draft": "Enable Draft Mode", "chaos": "Enable Chaos Events"}
var flags := {}
var code := LineEdit.new()
var generate := Button.new()
var sync := OptionButton.new()
var writable := true
var hint := Label.new()

func _ready() -> void:
	name = "AdvancedRandomizer"
	custom_minimum_size.x = 400
	var grid := GridContainer.new()
	grid.columns = 2
	for key in Config.FLAGS:
		var box := CheckBox.new()
		box.text = LABELS[key]
		flags[key] = box
		if key == "enabled":
			add_child(box)
		else:
			grid.add_child(box)
		box.toggled.connect(func(_on): _edited())
	var inputs := HBoxContainer.new()
	add_child(inputs)
	code.placeholder_text = "Seed"
	code.max_length = 32
	code.custom_minimum_size.x = 140
	code.tooltip_text = "1–32 letters or digits; case sensitive"
	inputs.add_child(code)
	code.text_changed.connect(func(_s): _edited())
	generate.text = "Generate Seed"
	inputs.add_child(generate)
	generate.pressed.connect(func(): code.text = Config.new_seed(); _edited())
	sync.add_item("Independent", Config.SyncMode.INDEPENDENT)
	sync.add_item("Mirrored", Config.SyncMode.MIRRORED)
	inputs.add_child(sync)
	sync.item_selected.connect(func(_i): _edited())
	add_child(grid)
	add_child(hint)
	hint.add_theme_color_override("font_color", Color.SALMON)
	apply(Config.defaults())

func values() -> Dictionary:
	var cfg := Config.defaults()
	cfg.seed = code.text
	cfg.sync_mode = sync.get_selected_id()
	for key in flags:
		cfg[key] = flags[key].button_pressed
	return cfg

func apply(cfg: Dictionary) -> void:
	if cfg.is_empty():
		cfg = Config.defaults()
	for key in flags:
		flags[key].set_pressed_no_signal(cfg[key])
	code.text = cfg.seed
	sync.select(sync.get_item_index(cfg.sync_mode))
	_sync_controls()

func valid() -> bool:
	return not flags.enabled.button_pressed or Config.valid(values())

func set_writable(on: bool) -> void:
	writable = on
	_sync_controls()

func _sync_controls() -> void:
	var on: bool = writable and flags.enabled.button_pressed
	for key in flags:
		flags[key].disabled = not (writable if key == "enabled" else on)
	code.editable = on
	generate.disabled = not on
	sync.disabled = not on
	hint.text = "Seed: use 1–32 letters or digits." if not valid() else ""
	hint.visible = not hint.text.is_empty()

func _edited() -> void:
	_sync_controls()
	changed.emit()
