

def test_live_api_shape_online_and_version():
    """The live API has connectedToControl + clientVersion, no online/version."""
    from server.devicemodel import device_view, fleet_max_version

    live = {"id": "1", "hostname": "vps", "os": "linux", "addresses": [],
            "connectedToControl": True, "clientVersion": "1.104.1-t7f4efe814-g8da26756c",
            "authorized": True, "user": "u@example.com", "tags": []}
    view = device_view(live, fleet_max_version([live]))
    assert view["online"] is True
    assert view["version"] == "1.104.1"
    assert fleet_max_version([live]) == "1.104.1"
    assert device_view({**live, "connectedToControl": False}, "")["online"] is False
