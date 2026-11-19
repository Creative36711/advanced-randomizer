extends SceneTree

## Снимки панели рандомайзера и лобби — глазами агента.
##
##   tools/sandbox/shots.sh /tmp/play [каталог-вывода]
##
## Пишет PNG в реальном разрешении игры (stretch отключён, пиксель в пиксель):
##   randomizer_host.png    панель, режим хоста
##   randomizer_guest.png   панель, режим гостя (всё заблокировано)
##   lobby.png              лобби с закрытым окном
##   lobby_randomizer.png   лобби с открытым окном рандомайзера
##
## Панель ловится по СВОЕМУ имени узла (lobby_panel.gd ставит name
## "AdvancedRandomizer"), а не по тексту кнопки: кнопку переименуют — снимок
## не сломается.

const LOBBY_SIZE := Vector2(800, 504)
var out_dir := "/tmp/shots"


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			out_dir = arg.trim_prefix("--out=")
	DirAccess.make_dir_recursive_absolute(out_dir)
	# Без этого UI масштабируется под размер окна и текст мылится.
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
	RenderingServer.set_default_clear_color(Color(0.05, 0.08, 0.06))
	_run.call_deferred()


func _run() -> void:
	var theme: Theme = load("res://src/ui/openbfme_theme.gd").create_theme(null)
	await _panel_shots(theme)
	await _lobby_shots(theme)
	quit()


func _panel_shots(theme: Theme) -> void:
	for host in [true, false]:
		var panel: Control = load("res://scripts/modes/randomizer/ui/lobby_panel.gd").new()
		panel.theme = theme
		panel.add_theme_constant_override("separation", 8)
		root.add_child(panel)
		panel.position = Vector2(40, 120)
		panel.apply({
			"version": 1, "enabled": true, "seed": "Arda", "sync_mode": 0,
			"shuffle_units": true, "shuffle_heroes": true, "shuffle_spellbook": true,
			"draft": true, "chaos": true,
		})
		panel.set_writable(host)
		await _settle()
		var wanted: Vector2i = Vector2i(panel.get_combined_minimum_size() + Vector2(48, 48))
		_save("randomizer_%s" % ("host" if host else "guest"),
			Rect2i(28, 108, wanted.x, wanted.y))
		root.remove_child(panel)
		panel.free()
		await process_frame


func _lobby_shots(theme: Theme) -> void:
	var lobby: Control = load("res://src/ui/multiplayer_lobby.gd").new()
	lobby.theme = theme
	lobby.position = Vector2.ZERO
	lobby.size = LOBBY_SIZE
	root.add_child(lobby)
	await process_frame
	# Состояние хоста: попап открывается только у того, кто правит настройки.
	lobby.call("_set_settings_editable", true)
	lobby.call("_refresh_buttons")
	await _settle()
	_save("lobby", Rect2i(0, 0, int(LOBBY_SIZE.x), int(LOBBY_SIZE.y)))

	var popup: PopupPanel = null
	for child in lobby.get_children():
		if child is PopupPanel:
			popup = child
			break
	if popup == null:
		print("SHOT_FAIL попап рандомайзера не найден в лобби")
		return
	# Нажимаем кнопку, а не дёргаем popup() напрямую — проверяем настоящий путь.
	for child in lobby.get_children():
		if child is Button and (child as Button).text.begins_with("Randomizer"):
			(child as Button).pressed.emit()
			break
	await _settle()
	print("POPUP pos=%s size=%s панель=%s" % [popup.position, popup.size, LOBBY_SIZE])
	_geometry_report(lobby, popup)
	_save("lobby_randomizer", Rect2i(0, 0, int(LOBBY_SIZE.x), int(LOBBY_SIZE.y)))


## Геометрия проверяется числами, а не на глаз: попап обязан вмещать панель
## целиком и стоять внутри лобби, а кнопка — не вылезать за панель. Именно
## эти два дефекта просмотрели, пока не появились снимки.
func _geometry_report(lobby: Control, popup: PopupPanel) -> void:
	var out := "GEOM панель=%s" % lobby.size
	for child in lobby.get_children():
		if child is Button and (child as Button).text.begins_with("Randomizer"):
			var b := child as Button
			var edge := b.position.x + b.size.x
			out += "\nGEOM кнопка pos=%s size=%s край=%.0f вылезает=%s" % [
				b.position, b.size, edge, str(edge > lobby.size.x or b.position.y < 0.0)]
	var holds := popup.size.x >= 536 and popup.size.y >= 287
	var inside: bool = popup.position.x >= 0.0 and popup.position.y >= 0.0 \
		and popup.position.x + popup.size.x <= lobby.size.x \
		and popup.position.y + popup.size.y <= lobby.size.y
	out += "\nGEOM попап pos=%s size=%s вмещает=%s внутри=%s" % [
		popup.position, popup.size, str(holds), str(inside)]
	print(out)


func _settle() -> void:
	for i in 4:
		await process_frame


func _save(name: String, region: Rect2i) -> void:
	var image := root.get_texture().get_image()
	if image == null:
		print("SHOT_FAIL ", name, " (нет изображения)")
		return
	var r := Rect2i(region.position, Vector2i(
		mini(region.size.x, image.get_width() - region.position.x),
		mini(region.size.y, image.get_height() - region.position.y)))
	if r.size.x > 0 and r.size.y > 0:
		image = image.get_region(r)
	var path := "%s/%s.png" % [out_dir, name]
	image.save_png(path)
	print("SHOT ", path, " ", image.get_width(), "x", image.get_height())
