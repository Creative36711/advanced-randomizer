extends RefCounted
## A short-lived world-space projectile. The visual tween never deals damage.
static func present(scene, event: Dictionary) -> void:
	if DisplayServer.get_name() == "headless":
		return
	var p: Vector2 = event.point
	if event.kind == "randomizer.meteor.impact":
		scene._spawn_power_flash(p, Color.CORAL)
		return
	var stone := MeshInstance3D.new()
	var mesh := SphereMesh.new()
	mesh.radius = 0.9
	mesh.height = 2.8
	var fire := StandardMaterial3D.new()
	fire.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	fire.albedo_color = Color.ORANGE_RED
	mesh.material = fire
	stone.mesh = mesh
	scene.add_child(stone)
	var ground := Vector3(p.x, scene._presentation_height(p), p.y)
	stone.position = ground + Vector3(-10, 26, -6)
	var tween := stone.create_tween()
	tween.tween_property(stone, "position", ground, float(event.delay) * scene.simulation.TICK_SECONDS).set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)
	tween.tween_callback(stone.queue_free)
