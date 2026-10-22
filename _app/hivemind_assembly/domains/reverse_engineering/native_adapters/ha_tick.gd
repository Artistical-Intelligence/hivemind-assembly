extends Node
# Hivemind Assembly tick adapter for Godot 4 projects (protocol 1).
#
# HA adds this autoload to a runtime copy of a project and runs it with a fixed frame
# rate. At the start of every physics frame the adapter sends the previous frame's
# declared state values (and a scaled frame) over a local socket, then waits for the
# next input record and presses or releases the mapped keys and actions before the
# frame's physics and processing run. The global random generator is seeded before
# the main scene loads and again when play starts. Nothing happens unless HA set
# HA_TICK_CONFIG.

const MAGIC := "HATK"

var _peer := StreamPeerTCP.new()
var _config := {}
var _inputs := []
var _held := []
var _events := []
var _ticks := 0
var _live := false


func _enter_tree() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	var raw := OS.get_environment("HA_TICK_CONFIG")
	if raw == "":
		return
	_config = JSON.parse_string(Marshalls.base64_to_utf8(raw))
	seed(int(_config.get("seed", 0)))
	_inputs = _config.get("inputs", [])
	_held.resize(_inputs.size())
	_held.fill(false)
	_events.resize(_inputs.size())
	if not _connect():
		get_tree().quit(70)
		return
	_live = true
	get_tree().physics_frame.connect(_on_physics_frame)


func _connect() -> bool:
	var port := int(OS.get_environment("HA_TICK_PORT"))
	if _peer.connect_to_host("127.0.0.1", port) != OK:
		return false
	var deadline := Time.get_ticks_msec() + 10000
	while _peer.get_status() == StreamPeerTCP.STATUS_CONNECTING and Time.get_ticks_msec() < deadline:
		_peer.poll()
		OS.delay_msec(1)
	if _peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return false
	_peer.set_no_delay(true)
	var hello := MAGIC.to_ascii_buffer()
	hello.append(1)
	hello.append_array(Marshalls.base64_to_raw(OS.get_environment("HA_TICK_TOKEN_B64")))
	return _peer.put_data(hello) == OK


func _read(count: int) -> PackedByteArray:
	if count == 0:
		return PackedByteArray()
	_peer.poll()
	var result: Array = _peer.get_data(count)
	if result[0] != OK or (result[1] as PackedByteArray).size() != count:
		return PackedByteArray()
	return result[1]


func _on_physics_frame() -> void:
	if not _live:
		return
	if _ticks > 0:
		_send_record()
	var kind := _read(1)
	if kind.size() != 1 or kind[0] != 73:  # "I"; "E" or a closed socket ends play.
		_live = false
		get_tree().quit(0)
		return
	var record := _read(int(_config.get("record_bytes", 1)))
	if record.size() == 0:
		_live = false
		get_tree().quit(0)
		return
	if _ticks == 0:
		# Games often call randomize() while loading; play starts from a known seed.
		seed(int(_config.get("seed", 0)))
	_apply(record)
	_ticks += 1


func _event_for(index: int) -> InputEvent:
	# An action is pressed the way a player presses it, with its first key binding,
	# so key-only paths such as button shortcuts see it too. Actions without a key
	# binding fall back to an action event.
	if _events[index] != null:
		return _events[index]
	var item: Dictionary = _inputs[index]
	var event: InputEvent = null
	if item.has("action"):
		for bound in InputMap.action_get_events(StringName(item["action"])):
			if bound is InputEventKey:
				event = bound.duplicate()
				break
		if event == null:
			var action := InputEventAction.new()
			action.action = StringName(item["action"])
			event = action
	else:
		var key := InputEventKey.new()
		var code := OS.find_keycode_from_string(str(item["key"]))
		key.keycode = code
		key.physical_keycode = code
		event = key
	_events[index] = event
	return event


func _apply(record: PackedByteArray) -> void:
	for index in _inputs.size():
		var want := ((record[index >> 3] >> (index & 7)) & 1) == 1
		if want == _held[index]:
			continue
		_held[index] = want
		var event := _event_for(index).duplicate()
		event.pressed = want
		if event is InputEventAction:
			event.strength = 1.0 if want else 0.0
		Input.parse_input_event(event)
	# Deliver now so this frame's physics and processing see the new input.
	Input.flush_buffered_events()


func _send_record() -> void:
	var payload := PackedByteArray()
	for segment in _config.get("segments", []):
		if segment["kind"] == "state":
			payload.append_array(_state_bytes(segment))
		else:
			payload.append_array(_frame_bytes(int(segment["width"]), int(segment["height"])))
	var header := PackedByteArray([84, 0, 0, 0, 0, 0, 0, 0, 0])  # "T", tick, length
	header.encode_u32(1, _ticks - 1)
	header.encode_u32(5, payload.size())
	_peer.put_data(header + payload)


func _value(field: Dictionary) -> Variant:
	if field.has("group"):
		return get_tree().get_nodes_in_group(StringName(field["group"])).size()
	var node := get_tree().root.get_node_or_null(NodePath(field["node"]))
	if node == null:
		return field.get("missing", 0)
	if field.has("property"):
		var value = node.get_indexed(NodePath(field["property"]))
		return field.get("missing", 0) if value == null else value
	return 1


func _state_bytes(segment: Dictionary) -> PackedByteArray:
	var buffer := PackedByteArray()
	buffer.resize(int(segment["bytes"]))
	for field in segment["fields"]:
		var value = _value(field)
		if value is bool:
			value = 1 if value else 0
		elif not (value is int or value is float):
			value = field.get("missing", 0)
		var offset := int(field["offset"])
		match field["type"]:
			"f32":
				buffer.encode_float(offset, float(value))
			"f64":
				buffer.encode_double(offset, float(value))
			"i8":
				buffer.encode_s8(offset, int(value))
			"u8":
				buffer.encode_u8(offset, int(value))
			"i16":
				buffer.encode_s16(offset, int(value))
			"u16":
				buffer.encode_u16(offset, int(value))
			"i32":
				buffer.encode_s32(offset, int(value))
			"u32":
				buffer.encode_u32(offset, int(value))
			"i64":
				buffer.encode_s64(offset, int(value))
			_:
				buffer.encode_u64(offset, int(value))
	return buffer


func _frame_bytes(width: int, height: int) -> PackedByteArray:
	var texture := get_viewport().get_texture()
	var image: Image = texture.get_image() if texture != null else null
	if image == null or image.is_empty():
		var blank := PackedByteArray()
		blank.resize(width * height * 4)
		return blank
	image.convert(Image.FORMAT_RGBA8)
	image.resize(width, height, Image.INTERPOLATE_BILINEAR)
	return image.get_data()
