extends SceneTree
const P := preload("res://scripts/modes/randomizer/ui/lobby_panel.gd")
const C := preload("res://scripts/modes/randomizer/randomizer_config.gd")

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var panel = P.new()
	root.add_child(panel)
	await process_frame
	var off: Dictionary = panel.values()
	var defaults_off: bool = not off.enabled and C.valid(off) and off.seed == C.defaults().seed
	panel.flags.enabled.button_pressed = true
	panel.changed.emit()
	var enabled_valid: bool = panel.values().enabled and panel.valid()
	panel.code.text = "bad seed!"
	panel.code.text_changed.emit(panel.code.text)
	var bad_rejected: bool = not panel.valid() and panel.hint.visible
	panel.generate.pressed.emit()
	var generated: String = panel.values().seed
	var alnum_ok: bool = C.valid(panel.values()) and generated.length() >= 8
	panel.sync.select(panel.sync.get_item_index(C.SyncMode.MIRRORED))
	var mirrored: bool = panel.values().sync_mode == C.SyncMode.MIRRORED
	panel.set_writable(false)
	var read_only: bool = panel.flags.shuffle_units.disabled and not panel.code.editable
	panel.set_writable(true)
	# Host settings -> controls, as a guest receives them.
	var cfg := C.defaults()
	cfg.enabled = true
	cfg.seed = "Guest99"
	cfg.draft = true
	panel.apply(cfg)
	var applied: bool = var_to_bytes(panel.values()) == var_to_bytes(cfg)
	# Disabled mode means "no settings on the wire at all".
	panel.flags.enabled.button_pressed = false
	var disabled_wire: bool = C.valid(panel.values()) and not panel.values().enabled
	panel.queue_free()
	await process_frame
	var ok: bool = defaults_off and enabled_valid and bad_rejected and alnum_ok and mirrored and read_only and applied and disabled_wire
	print("RANDOMIZER_LOBBY_PANEL ok=%s off=%s valid=%s bad=%s seed=%s mirrored=%s readonly=%s applied=%s disabled=%s" % [
		str(ok), str(defaults_off), str(enabled_valid), str(bad_rejected), generated, str(mirrored), str(read_only), str(applied), str(disabled_wire)])
	quit(0 if ok else 1)
