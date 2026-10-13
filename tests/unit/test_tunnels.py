"""Server tunnels: naming, reading a profile, the installed copy, and the route safety check."""
from __future__ import annotations

import ipaddress

from server import tunnels
from server.tunnels import Route

PROFILE = """client
dev tun
proto udp
remote vpn.example.net 1194
nobind
<ca>
-----BEGIN CERTIFICATE-----
up /not/a/script/this/is/key/material
-----END CERTIFICATE-----
</ca>
<cert>
x
</cert>
<key>
y
</key>
remote-cert-eku "TLS Web Server Authentication"
"""


def kinds(text: str) -> dict[str, list[str]]:
    a = tunnels.analyze(text)
    return {k: [f.directive for f in a.of(k)]
            for k in ("refuse", "script", "strip", "default_route", "auth") if a.of(k)}


# --------------------------------------------------------------- names

def test_names():
    assert tunnels.instance_name("vps-cybervpn") == "vps-cybervpn"
    assert tunnels.instance_name("My VPN (home)!") == "My-VPN-home"
    assert tunnels.instance_name("///") == "profile"
    assert len(tunnels.instance_name("x" * 100)) == 40
    assert tunnels.unit_name("vps-cybervpn") == "openvpn-client@vps-cybervpn.service"


def test_interface_name_is_ours_and_fits_linux():
    name = tunnels.iface_name("Pz_NXPhRqh0")
    assert name == "vc-Pz_NXPhRqh0" and len(name) <= 15
    assert not name.startswith("tun")  # never collides with a tunnel started by hand
    assert len(tunnels.iface_name("A" * 40)) == 15


def test_owner_marker_round_trip():
    conf, _ = tunnels.render(PROFILE, "abc123")
    assert tunnels.owner_of(conf) == "abc123"
    assert tunnels.owner_of("client\nremote x\n") is None


# --------------------------------------------------------------- reading a profile

def test_clean_profile_has_no_findings():
    assert kinds(PROFILE) == {}


def test_directives_inside_inline_blocks_are_data_not_directives():
    # the "up ..." line above sits inside <ca>: key material, never a script
    assert not tunnels.analyze(PROFILE).scripts


def test_script_lines_need_a_typed_confirm():
    text = PROFILE + "script-security 2\nup /etc/openvpn/up.sh\nplugin /usr/lib/x.so\ntls-verify /x\n"
    assert kinds(text)["script"] == ["script-security", "up", "plugin", "tls-verify"]


def test_script_security_one_is_harmless():
    assert "script" not in kinds(PROFILE + "script-security 1\n")


def test_dashed_and_quoted_and_indented_forms_are_still_seen():
    text = PROFILE + '  --up "/x"\n\t"route-up" /y\n'
    assert kinds(text)["script"] == ["up", "route-up"]


def test_comments_are_ignored():
    assert kinds(PROFILE + "# up /x\n; plugin /y\n") == {}


def test_lines_that_write_files_or_open_ports_are_stripped():
    text = PROFILE + "log /var/log/x\nstatus /tmp/s 10\nwritepid /run/x\nmanagement 127.0.0.1 7505\ndaemon\n"
    assert kinds(text)["strip"] == ["log", "status", "writepid", "management", "daemon"]


def test_username_password_profiles_sign_in_through_the_consoles_file():
    # a bare directive or [inline] marks the profile as signing in; a path to a file the
    # console did not write is still refused
    assert kinds(PROFILE + "auth-user-pass\n")["auth"] == ["auth-user-pass"]
    assert kinds(PROFILE + "auth-user-pass [inline]\n")["auth"] == ["auth-user-pass"]
    assert kinds(PROFILE + "auth-user-pass /root/creds\n")["refuse"] == ["auth-user-pass"]
    assert kinds(PROFILE + "auth-user-pass /root/creds\n").get("auth") is None


def test_an_inline_auth_block_is_found_with_its_credentials():
    text = PROFILE + "<auth-user-pass>\nmyuser\nmypassword\n</auth-user-pass>\nauth-user-pass\n"
    a = tunnels.analyze(text)
    assert a.auth_needed and a.inline_creds == ("myuser", "mypassword")
    lo = len(PROFILE.splitlines()) + 1
    assert a.inline_auth_span == (lo, lo + 3)  # block, user, password, closing tag
    broken = PROFILE + "<auth-user-pass>\nonly-a-username\n</auth-user-pass>\n"
    assert tunnels.analyze(broken).inline_creds is None and tunnels.analyze(broken).auth_needed is False


def test_render_lifts_the_credentials_out_of_the_config():
    text = PROFILE + "<auth-user-pass>\nu\np\n</auth-user-pass>\nauth-user-pass\n"
    a = tunnels.analyze(text)
    conf, notices = tunnels.render(text, "abc123", a, auth_path="/etc/openvpn/client/corp.auth")
    lines = conf.splitlines()
    assert "auth-user-pass /etc/openvpn/client/corp.auth" in lines
    live = [l for l in lines if not l.startswith("#")]               # comments may quote what was removed
    assert not any(l.strip().startswith(("<auth-user-pass>", "</auth-user-pass>")) for l in live)
    assert not any(l.strip() in ("u", "p") for l in live)            # the credentials are not in the config
    assert not any(l.strip() == "auth-user-pass" for l in live)      # no bare directive either
    assert "# [vpn-console] removed (auth): <auth-user-pass>" in conf
    assert any("root-only file" in n for n in notices)


def test_render_without_an_auth_path_keeps_the_directive_for_the_plan():
    conf, _ = tunnels.render(PROFILE + "auth-user-pass\n", "abc123")
    assert "auth-user-pass\n" in conf  # nothing is claimed until credentials exist


def test_auth_file_text_is_two_clean_lines():
    assert tunnels.auth_file_text("u", "p") == "u\np\n"
    import pytest as _pytest
    for bad in (("", "p"), ("u", ""), ("u\nextra", "p"), ("u", "p\r"), ("u" * 257, "p")):
        with _pytest.raises(ValueError):
            tunnels.auth_file_text(*bad)


def test_file_references_are_refused_but_inline_and_dh_none_are_fine():
    assert kinds("client\nca /root/ca.crt\ncert c.crt\nkey k.key\ntls-auth ta.key 1\n")["refuse"] == ["ca", "cert", "key", "tls-auth"]
    assert kinds("client\nca [inline]\ndh none\n") == {}
    assert kinds("client\nconfig other.conf\n")["refuse"] == ["config"]


def test_default_route_lines_are_found():
    text = PROFILE + "redirect-gateway def1\nroute 0.0.0.0 0.0.0.0\nroute 128.0.0.0 128.0.0.0\nroute-ipv6 ::/0\nroute 10.0.0.0 255.0.0.0\n"
    assert kinds(text)["default_route"] == ["redirect-gateway", "route", "route", "route-ipv6"]


def test_connection_blocks_hold_real_directives():
    text = "client\n<connection>\nremote a 1194\nup /x\n</connection>\n"
    assert kinds(text)["script"] == ["up"]


def test_line_numbers_follow_openvpn_newline_rules():
    # form feed is not a line break for OpenVPN, so it must not be one here
    a = tunnels.analyze("client\nfoo\x0cup /x\nup /y\n")
    assert [f.line_no for f in a.scripts] == [4 - 1] and a.scripts[0].text == "up /y"


# --------------------------------------------------------------- the installed copy

def test_render_marks_comments_out_and_adds_tunnel_only_settings():
    text = PROFILE + "redirect-gateway def1\nlog /var/log/x\n"
    conf, notices = tunnels.render(text, "Pz_NXPhRqh0")
    lines = conf.splitlines()
    assert lines[0] == "# vpn-console-managed profile=Pz_NXPhRqh0"
    assert "# [vpn-console] removed (default_route): redirect-gateway def1" in lines
    assert "# [vpn-console] removed (strip): log /var/log/x" in lines
    assert "redirect-gateway def1" not in lines and "log /var/log/x" not in lines
    for must in ("dev vc-Pz_NXPhRqh0", "dev-type tun", 'pull-filter ignore "redirect-gateway"',
                 'pull-filter ignore "route 0.0.0.0"', 'pull-filter ignore "route 128.0.0.0"',
                 'pull-filter ignore "dhcp-option"'):
        assert must in lines
    assert lines[-1] == "script-security 1"  # no scripts approved: none can run, even if one slipped past the scan
    assert any("Default-route lines" in n for n in notices) and any("Removed from the installed copy" in n for n in notices)
    assert conf.endswith("\n")


def test_render_keeps_key_material_untouched():
    conf, _ = tunnels.render(PROFILE, "x")
    assert "-----BEGIN CERTIFICATE-----" in conf and "up /not/a/script/this/is/key/material" in conf


def test_render_leaves_script_security_alone_when_scripts_were_approved():
    conf, _ = tunnels.render(PROFILE + "script-security 2\nup /x\n", "x")
    assert "script-security 1" not in conf.splitlines()
    assert "up /x" in conf.splitlines()


def test_render_keeps_tap_devices_tap():
    conf, _ = tunnels.render("client\ndev tap\nremote a 1\n", "x")
    assert "dev-type tap" in conf.splitlines()


def test_render_handles_crlf_profiles():
    conf, _ = tunnels.render("client\r\nredirect-gateway def1\r\nremote a 1\r\n", "x")
    assert "# [vpn-console] removed (default_route): redirect-gateway def1" in conf.splitlines()


# --------------------------------------------------------------- routes

# /proc/net/route format (hex, little-endian). 10.200.0.0/24 = 0000C80A mask 00FFFFFF, etc.
ROUTES_V4 = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
eth0\t00000000\t0100000A\t0003\t0\t0\t0\t00000000\t0\t0\t0
eth0\t0000000A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0
docker0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
vc-abc\t0001C80A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0
dead0\t0000000B\t00000000\t0000\t0\t0\t0\t00FFFFFF\t0\t0\t0
"""


def test_parse_ipv4_routes():
    routes = tunnels.parse_proc_net_route(ROUTES_V4)
    got = {(str(r.dest), r.iface) for r in routes}
    assert ("0.0.0.0/0", "eth0") in got and ("10.0.0.0/24", "eth0") in got
    assert ("172.17.0.0/16", "docker0") in got and ("10.200.1.0/24", "vc-abc") in got
    assert all(r.iface != "dead0" for r in routes)  # RTF_UP not set
    assert next(r for r in routes if str(r.dest) == "0.0.0.0/0").gateway == "10.0.0.1"


def test_parse_ipv6_routes():
    text = ("20010db8000000000000000000000000 20 00000000000000000000000000000000 00 "
            "00000000000000000000000000000000 00000100 00000001 00000000 00000001 vc-abc\n"
            "00000000000000000000000000000001 80 00000000000000000000000000000000 00 "
            "00000000000000000000000000000000 00000000 00000001 00000000 80200001 lo\n")
    routes = tunnels.parse_proc_net_ipv6_route(text)
    assert [(str(r.dest), r.iface) for r in routes] == [("2001:db8::/32", "vc-abc")]


def net(cidr: str, iface: str) -> Route:
    return Route(ipaddress.ip_network(cidr), iface)


BASE = [net("0.0.0.0/0", "eth0"), net("10.0.0.0/24", "eth0"), net("172.17.0.0/16", "docker0"),
        net("10.112.0.0/12", "tun0")]  # tun0 stands for a tunnel started by hand


def test_a_tunnel_that_only_adds_its_own_networks_is_safe():
    mine = [net("10.200.1.0/24", "vc-abc"), net("192.168.50.0/24", "vc-abc")]
    assert tunnels.route_violations(BASE + mine, "vc-abc") == []


def test_replacing_the_default_route_is_caught_in_every_form():
    for dest in ("0.0.0.0/0", "0.0.0.0/1", "128.0.0.0/1"):
        out = tunnels.route_violations(BASE + [net(dest, "vc-abc")], "vc-abc")
        assert out and "default route" in out[0], dest


def test_overlapping_another_interfaces_route_is_caught_including_other_tunnels():
    out = tunnels.route_violations(BASE + [net("10.112.4.0/24", "vc-abc")], "vc-abc")
    assert out and "10.112.0.0/12" in out[0] and "tun0" in out[0]       # steals a hand-started tunnel's traffic
    out = tunnels.route_violations(BASE + [net("10.0.0.0/8", "vc-abc")], "vc-abc")
    assert out and "10.0.0.0/24" in out[0]                              # swallows this server's own network
    out = tunnels.route_violations(BASE + [net("172.16.0.0/12", "vc-abc")], "vc-abc")
    assert out and "172.17.0.0/16" in out[0]                            # swallows Docker


def test_tailscales_range_is_protected_even_though_it_is_not_in_the_main_table():
    out = tunnels.route_violations(BASE + [net("100.64.0.0/10", "vc-abc")], "vc-abc")
    assert out and "Tailscale" in out[0]
    assert tunnels.route_violations(BASE + [net("100.100.0.0/16", "vc-abc")], "vc-abc")


def test_link_local_and_other_interfaces_own_routes_are_ignored():
    routes = BASE + [net("169.254.0.0/16", "vc-abc"), net("fe80::/64", "vc-abc"), net("fe80::/64", "eth0")]
    assert tunnels.route_violations(routes, "vc-abc") == []


# --------------------------------------------------------------- state

def test_tunnel_summary_states():
    unit = lambda s: {"state": s, "since": "now", "enabled_on_boot": True}  # noqa: E731
    f = lambda u, conf=True, ip="": tunnels.tunnel_summary(u, conf, "openvpn-client@x.service", "vc-x", ip)  # noqa: E731
    assert f(unit("active"), ip="10.0.0.2")["state"] == "connected" and f(unit("active"), ip="10.0.0.2")["ip"] == "10.0.0.2"
    assert f(unit("running"), ip="10.0.0.2")["state"] == "connected"
    # OpenVPN 2.7 reports ready to systemd before it has connected: no address, not connected
    assert f(unit("active"))["state"] == "connecting" and f(unit("active"))["ip"] == ""
    assert f(unit("activating"))["state"] == "connecting"
    assert f(unit("failed"))["state"] == "failed"
    assert f(unit("inactive"))["state"] == "stopped"
    assert f(None)["state"] == "stopped" and f(None, conf=False)["state"] == "none"
    assert f(unit("failed"))["ip"] == "" and f(unit("active"), ip="10.0.0.2")["boot"] is True
