extends SceneTree
const S := preload("res://src/retail_slice/retail_lockstep_session.gd")
const C := preload("res://scripts/modes/randomizer/randomizer_config.gd")
const F := preload("res://tests/randomizer_fixture.gd")
var host
var guest
var raw

func _initialize() -> void:
	call_deferred("_run")

func _pump(cond: Callable) -> bool:
	for i in 20000:
		host.poll()
		guest.poll()
		if cond.call():
			return true
	return false

func _run() -> void:
	var cfg := C.defaults()
	cfg.enabled = true
	cfg.seed = "Arda42"
	cfg.draft = false
	host = S.new(null)
	guest = S.new(null)
	var ok: bool = host.host(0) == OK
	var joined: bool = ok and guest.join("127.0.0.1", host.bound_port) == OK
	var handshake: bool = joined and _pump(func(): return host.handshake_complete and guest.handshake_complete)
	var defaults_plain: bool = var_to_bytes(host.lobby_settings) == var_to_bytes(S.lobby_default_settings())
	var sent: bool = handshake and host.send_lobby_settings("bfme2.map.rivendell", 1200, 1.0, false, true, true, cfg)
	var arrived: bool = sent and _pump(func(): return guest.lobby_settings.get("randomizer", {}).get("seed", "") == "Arda42")
	var byte_equal: bool = arrived and var_to_bytes(host.lobby_settings) == var_to_bytes(guest.lobby_settings)
	var bad := cfg.duplicate(true)
	bad.seed = ""
	var refused_bad: bool = not host.send_lobby_settings("bfme2.map.rivendell", 1200, 1.0, false, true, true, bad)
	# A 9-key spoof from the guest must be rejected and must not alter host settings.
	var before := var_to_bytes(host.lobby_settings)
	var rejects: int = host.rejected_packets
	guest._send_envelope({"kind": "lobby.settings", "map_id": "bfme2.map.rivendell", "resources": 1200, "cp_factor": 1.0,
		"build_plots": false, "allow_custom_heroes": true, "allow_ring_heroes": true, "logic_random_seed": 7, "randomizer": cfg})
	var spoof_rejected: bool = _pump(func(): return host.rejected_packets > rejects) and var_to_bytes(host.lobby_settings) == before
	# A version-3 client with a different balance database is refused at join.
	raw = ENetConnection.new()
	raw.create_host()
	var peer: ENetPacketPeer = raw.connect_to_host("127.0.0.1", host.bound_port)
	var refused_balance := false
	var sent_join := false
	for i in 20000:
		raw.service()
		host.poll()
		if peer.get_state() == ENetPacketPeer.STATE_CONNECTED and not sent_join:
			peer.send(0, var_to_bytes({"kind": "join", "version": 3, "balance": "other-build"}), 1)
			raw.flush()
			sent_join = true
		if peer.get_available_packet_count() > 0:
			var env = bytes_to_var(peer.get_packet())
			if typeof(env) == TYPE_DICTIONARY and String(env.get("kind", "")) == "refuse":
				refused_balance = String(env.get("reason", "")).contains("balance database")
				break
		if i % 100 == 99:
			OS.delay_msec(1)
	refused_balance = refused_balance and host._peer_seats.size() == 1
	# Both lockstep peers run the mode: the same offer, the same choice and the
	# same paid reroll must leave byte-identical authoritative state.
	# A host-side room-setting change rebuilds both simulations in the real app;
	# do the same here so no pre-lobby ticks can differ.
	var host_sim = F.make(F.options())
	var guest_sim = F.make(F.options())
	host_sim.ai_enabled = false
	guest_sim.ai_enabled = false
	var hs = S.new(host_sim)
	var gs = S.new(guest_sim)
	var h_ok: bool = hs.host(0) == OK
	var g_ok: bool = h_ok and gs.join("127.0.0.1", hs.bound_port) == OK
	var hs_ready := false
	if g_ok:
		for i in 20000:
			hs.poll()
			gs.poll()
			if hs.handshake_complete and gs.handshake_complete:
				hs_ready = true
				break
	var producer: int = host_sim.producer_id(0, "barracks")
	var rerolls_before: int = int(host_sim.structures[producer].get("ar_rerolls", 0))
	var mode_serial: int = int(host_sim.randomizer.state.offer_serial)
	var gs_serial: int = int(guest_sim.randomizer.state.offer_serial)
	var rolled: bool = hs_ready and hs.send_lobby_settings("bfme2.map.rivendell", 1200, 1.0, false, true, true, cfg)
	# Prove the wire path, not just a direct call: DRAFT and REROLL travel as lockstep commands.
	hs.submit_local("ar_reroll", {"producer": producer})
	var advanced := false
	for i in 40000:
		hs.poll()
		gs.poll()
		hs.advance_if_ready()
		gs.advance_if_ready()
		if i % 100 == 99:
			OS.delay_msec(1)
		if host_sim.tick_index >= 12:
			advanced = true
			break
	var lockstep_equal: bool = hs_ready and advanced and mode_serial == 0 and gs_serial == 0 and host_sim.state_hash() == guest_sim.state_hash() \
		and host_sim.randomizer.state.offer_serial == guest_sim.randomizer.state.offer_serial \
		and host_sim.last_command_result.get("ok", false) == guest_sim.last_command_result.get("ok", false) \
		and int(host_sim.structures[producer].get("ar_rerolls", 0)) == rerolls_before + 1 \
		and int(guest_sim.structures[producer].get("ar_rerolls", 0)) == rerolls_before + 1
	var seated: bool = host.lobby_seat_count() == 2 if host.has_method("lobby_seat_count") else true
	# Launch echo carries the same settings object byte-for-byte.
	host.send_lobby_profile("Host", "men", 0, true)
	guest.send_lobby_profile("Guest", "men", 1, true)
	var ready: bool = _pump(func(): return host.all_seats_ready())
	var launched: bool = ready and host.send_lobby_launch()
	var echoed: bool = launched and _pump(func(): return guest.lobby_launch_received)
	var echo_equal: bool = echoed and var_to_bytes(guest.lobby_launch_settings) == var_to_bytes(host.lobby_launch_settings) \
		and guest.lobby_launch_settings.get("randomizer", {}).get("seed", "") == "Arda42"
	var ok_all: bool = lockstep_equal and defaults_plain and sent and arrived and byte_equal and refused_bad and spoof_rejected and refused_balance and seated and echo_equal
	print("RANDOMIZER_LOBBY ok=%s lockstep=%s defaults=%s sent=%s arrived=%s bytes=%s bad_refused=%s spoof=%s balance_refused=%s seats=%s echo=%s" % [
		str(ok_all), str(lockstep_equal), str(defaults_plain), str(sent), str(arrived), str(byte_equal), str(refused_bad), str(spoof_rejected), str(refused_balance), str(seated), str(echo_equal)])
	if raw != null:
		raw.destroy()
	if hs != null:
		hs.close()
	if gs != null:
		gs.close()
	host.close()
	guest.close()
	quit(0 if ok_all else 1)
