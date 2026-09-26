from mirage.camera import order_devices


def test_indices_follow_uid_order_and_virtual_camera_is_hidden():
    devices = [
        ("HD-камера FaceTime", "EAB7", True),
        ("Камера (iPhone)", "40BA", False),
        ("OBS Virtual Camera", "7626", False),
    ]
    cams = order_devices(devices)
    assert [c.name for c in cams] == ["HD-камера FaceTime", "Камера (iPhone)"]
    # OpenCV order by uid: 40BA=0, 7626=1 (OBS, hidden), EAB7=2
    assert cams[0].index == 2 and cams[1].index == 0


def test_builtin_first_then_by_index():
    cams = order_devices([("USB Cam", "B", False), ("Desk View", "A", False), ("FaceTime", "C", True)])
    assert [c.name for c in cams] == ["FaceTime", "Desk View", "USB Cam"]


def test_empty():
    assert order_devices([]) == []
